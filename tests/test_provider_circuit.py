import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.provider_circuit import CircuitRejected, ProviderCircuits


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def fixture(**kwargs):
    clock = Clock()
    return ProviderCircuits(clock=clock, failure_threshold=2,
                            cooldown_seconds=10, **kwargs), clock


def open_circuit(circuits):
    for _ in range(2):
        circuits.fail(circuits.acquire('hf-router'), 'RATE_LIMIT', pre_execution=True)


def test_closed_success_and_consecutive_fault_threshold():
    circuits, clock = fixture()
    circuits.fail(circuits.acquire('hf-router'), 'RATE_LIMIT', pre_execution=True)
    assert circuits.snapshot('hf-router')['consecutive_provider_failures'] == 1
    circuits.succeed(circuits.acquire('hf-router'))
    assert circuits.snapshot('hf-router')['consecutive_provider_failures'] == 0
    open_circuit(circuits)
    state = circuits.snapshot('hf-router')
    assert state['circuit_state'] == 'OPEN' and state['retry_after_seconds'] == 10
    with pytest.raises(CircuitRejected, match='PROVIDER_CIRCUIT_OPEN'):
        circuits.acquire('hf-router')
    clock.now += 9.999
    with pytest.raises(CircuitRejected, match='PROVIDER_CIRCUIT_OPEN'):
        circuits.acquire('hf-router')


def test_one_half_open_probe_and_successful_recovery_at_deadline():
    circuits, clock = fixture()
    open_circuit(circuits)
    clock.now += 10
    probe = circuits.acquire('hf-router')
    assert probe.recovery_probe and circuits.snapshot('hf-router')['circuit_state'] == 'HALF_OPEN'
    with pytest.raises(CircuitRejected, match='PROVIDER_CIRCUIT_OPEN'):
        circuits.acquire('hf-router')
    circuits.succeed(probe)
    assert circuits.snapshot('hf-router')['circuit_state'] == 'CLOSED'
    assert not circuits.acquire('hf-router').recovery_probe


def test_failed_probe_reopens_with_new_cooldown():
    circuits, clock = fixture()
    open_circuit(circuits)
    clock.now += 10
    circuits.fail(circuits.acquire('hf-router'), 'PROVIDER_TIMEOUT')
    state = circuits.snapshot('hf-router')
    assert state['circuit_state'] == 'OPEN' and state['retry_after_seconds'] == 10
    assert state['last_failure_pre_execution'] is False and not state['replay_authorized']


@pytest.mark.parametrize('code', [
    'CANCELLED', 'TASK_TIMEOUT', 'CREDENTIAL_UNAVAILABLE', 'DATA_LOCALITY',
    'HF_BUDGET_NOT_RESERVED', 'FALLBACK_POLICY_DENIED', 'OUTPUT_BUDGET_EXHAUSTED',
    'private token=never-record-this', None, [], {'raw': 'never-record-this'},
])
def test_local_or_unknown_failures_do_not_count_or_leak(code):
    circuits, clock = fixture()
    circuits.fail(circuits.acquire('hf-router'), code, pre_execution=True)
    state = circuits.snapshot('hf-router')
    assert state['circuit_state'] == 'CLOSED'
    assert state['consecutive_provider_failures'] == 0 and state['last_failure_code'] is None
    assert 'never-record-this' not in json.dumps(state)
    open_circuit(circuits)
    clock.now += 10
    circuits.fail(circuits.acquire('hf-router'), code)
    state = circuits.snapshot('hf-router')
    assert state['circuit_state'] == 'OPEN' and state['consecutive_provider_failures'] == 2
    assert circuits.acquire('hf-router').recovery_probe


def test_cancelled_probe_releases_without_claiming_recovery():
    circuits, clock = fixture()
    open_circuit(circuits)
    clock.now += 10
    circuits.abandon(circuits.acquire('hf-router'))
    assert circuits.snapshot('hf-router')['circuit_state'] == 'OPEN'
    assert circuits.snapshot('hf-router')['consecutive_provider_failures'] == 2
    assert circuits.acquire('hf-router').recovery_probe


def test_late_concurrent_success_cannot_close_newly_open_circuit():
    circuits, clock = fixture()
    late = circuits.acquire('hf-router')
    open_circuit(circuits)
    circuits.succeed(late)
    assert circuits.snapshot('hf-router')['circuit_state'] == 'OPEN'
    assert circuits.snapshot('hf-router')['active_permits'] == 0


def test_late_fault_cannot_reopen_recovered_generation():
    circuits, clock = fixture()
    late = circuits.acquire('hf-router')
    open_circuit(circuits)
    clock.now += 10
    circuits.succeed(circuits.acquire('hf-router'))
    circuits.fail(late, 'PROVIDER_TIMEOUT')
    assert circuits.snapshot('hf-router')['circuit_state'] == 'CLOSED'
    assert circuits.snapshot('hf-router')['consecutive_provider_failures'] == 0


def test_parallel_recovery_admission_has_exactly_one_probe():
    circuits, clock = fixture()
    open_circuit(circuits)
    clock.now += 10

    def attempt(_):
        try:
            return circuits.acquire('hf-router')
        except CircuitRejected:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        permits = [x for x in executor.map(attempt, range(16)) if x is not None]
    assert len(permits) == 1 and permits[0].recovery_probe
    assert circuits.snapshot('hf-router')['active_permits'] == 1
    circuits.succeed(permits[0])


def test_per_provider_isolation_and_bounded_registry_inflight():
    circuits, _ = fixture(max_providers=2, max_inflight_per_provider=1)
    first = circuits.acquire('hf-router')
    with pytest.raises(CircuitRejected, match='CIRCUIT_INFLIGHT_LIMIT'):
        circuits.acquire('hf-router')
    other = circuits.acquire('other-cloud')
    with pytest.raises(CircuitRejected, match='CIRCUIT_REGISTRY_FULL'):
        circuits.acquire('third-cloud')
    circuits.succeed(first)
    circuits.fail(circuits.acquire('hf-router'), 'CAPACITY', pre_execution=True)
    circuits.fail(circuits.acquire('hf-router'), 'CAPACITY', pre_execution=True)
    circuits.succeed(other)
    assert circuits.snapshot('other-cloud')['circuit_state'] == 'CLOSED'
    assert circuits.snapshot('hf-router')['circuit_state'] == 'OPEN'


def test_forged_cross_instance_and_duplicate_permits_rejected():
    circuits, _ = fixture()
    permit = circuits.acquire('hf-router')
    for forged in (replace(permit), replace(permit, provider_id='other'), None):
        with pytest.raises(CircuitRejected, match='CIRCUIT_PERMIT_INVALID'):
            circuits.succeed(forged)
    other, _ = fixture()
    with pytest.raises(CircuitRejected, match='CIRCUIT_PERMIT_INVALID'):
        other.succeed(permit)
    assert circuits.snapshot('hf-router')['active_permits'] == 1
    circuits.succeed(permit)
    with pytest.raises(CircuitRejected, match='CIRCUIT_PERMIT_INVALID'):
        circuits.abandon(permit)


@pytest.mark.parametrize('value', [True, -1, float('nan'), float('inf'), '100'])
def test_invalid_clock_fails_closed_without_dispatch(value):
    circuits = ProviderCircuits(clock=lambda: value)
    with pytest.raises(CircuitRejected, match='CIRCUIT_CLOCK_INVALID'):
        circuits.acquire('hf-router')


def test_backwards_clock_and_malformed_admission_classification_rejected():
    circuits, clock = fixture()
    permit = circuits.acquire('hf-router')
    with pytest.raises(ValueError, match='admission classification'):
        circuits.fail(permit, 'RATE_LIMIT', pre_execution='false')
    assert circuits.snapshot('hf-router')['active_permits'] == 1
    clock.now -= 1
    with pytest.raises(CircuitRejected, match='CIRCUIT_CLOCK_INVALID'):
        circuits.acquire('hf-router')


@pytest.mark.parametrize('provider', ['', '../hf-token', 'https://provider', 'x' * 101, None])
def test_provider_id_rejects_paths_urls_unbounded_input(provider):
    circuits, _ = fixture()
    with pytest.raises(CircuitRejected, match='CIRCUIT_PROVIDER_INVALID'):
        circuits.acquire(provider)


def test_existing_dispatch_id_bound_is_supported():
    circuits, _ = fixture()
    permit=circuits.acquire('x'*100)
    circuits.succeed(permit)


@pytest.mark.parametrize('kwargs', [
    {'failure_threshold': True}, {'failure_threshold': 0}, {'max_providers': 129},
    {'max_inflight_per_provider': 65}, {'cooldown_seconds': 0},
    {'cooldown_seconds': float('nan')}, {'cooldown_seconds': True}, {'clock': None},
])
def test_configuration_is_bounded_and_strict(kwargs):
    with pytest.raises(ValueError):
        ProviderCircuits(**kwargs)
