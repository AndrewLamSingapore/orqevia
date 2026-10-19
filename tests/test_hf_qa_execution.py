"""Offline QA admission/failover fixtures, not live provider qualification."""
import hashlib
import json
from dataclasses import replace

from fastapi import HTTPException
import httpx
import pytest

from app.hf_qa_execution import QAReservation, execute_direct_qa
from app.hf_serverless import HFServerlessQA
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import ProviderFailure


CONTEXT = 'My name is Clara and I live in Berkeley.'
QUESTION = 'What is my name?'
SPAN = {'answer': 'Clara', 'score': .97, 'start': 11, 'end': 16}
TASK = 'b3c60f03-e8e5-4f19-a0b4-c085ffbb0a01'
RESERVATION = '0f0f204b-5bcd-4e64-82d0-8309d7ca9941'
ROUTER_TASK = '694c4f70-fd1f-4e56-b3f3-715720839741'
MODEL = 'google/gemma-3-4b-it:deepinfra'


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


@pytest.fixture(autouse=True)
def isolated_owner(monkeypatch):
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'offline-owner-fixture')


def binding_hash(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def fixture(*, response=None, exception=None, resolver=None, fallback=True):
    clock = Clock()
    calls, phases, router_calls = [], [], []

    def handler(request):
        calls.append(request)
        if exception is not None:
            raise exception
        return response if response is not None else httpx.Response(200, json=SPAN)

    qa = HFServerlessQA(secret_resolver=resolver or (lambda _: 'fixture-only'),
        transport=httpx.MockTransport(handler))

    def admit(binding, previous, phase):
        phases.append((phase, dict(binding)))
        return QAReservation(reservation_id=RESERVATION,
            binding_sha256=binding_hash(binding), price_contract_sha256='a' * 64,
            expires_monotonic=binding['deadline_monotonic'] + 1,
            direct_maximum_charge_usd='.001',
            router_maximum_charge_usd='.001' if fallback else '0',
            hf_router_provider_id='hf-router-approved' if fallback else None,
            hf_router_model=MODEL if fallback else None)

    def router(**kwargs):
        router_calls.append(kwargs)
        return {'result': 'Clara', 'agent_id': kwargs['binding']['agent_id'],
            'parent_task_id': kwargs['binding']['task_id'], 'task_id': ROUTER_TASK,
            'request_binding_sha256': kwargs['request_binding_sha256'],
            'reservation_id': kwargs['reservation'].reservation_id,
            'provider': 'hf-router-approved', 'model': MODEL,
            'actual_cost_usd': .00001}

    arguments = dict(authorization='Bearer offline-owner-fixture', agent_id='a18',
        task_id=TASK, context=CONTEXT, question=QUESTION,
        data_classification='CLOUD_PERMITTED', max_cost_usd='.01',
        admit=admit, execute_hf_router=router, qa=qa, clock=clock)
    return arguments, calls, phases, router_calls, clock


def test_missing_real_price_contract_denies_before_secrets_or_network():
    def denied(_):
        pytest.fail('No real price contract may read credentials')
    arguments, calls, phases, router_calls, _ = fixture(resolver=denied)
    arguments['admit'] = None
    with pytest.raises(ProviderFailure, match='QA_PRICE_CONTRACT_UNAVAILABLE') as error:
        execute_direct_qa(**arguments)
    assert error.value.pre_execution is True
    assert calls == phases == router_calls == []


def test_owner_authentication_is_required_before_admission():
    arguments, calls, phases, router_calls, _ = fixture()
    arguments['authorization'] = 'Bearer unrelated-fixture'
    with pytest.raises(HTTPException) as error:
        execute_direct_qa(**arguments)
    assert error.value.status_code == 401 and calls == phases == router_calls == []


@pytest.mark.parametrize('changes', [
    {'agent_id': 'prime'}, {'agent_id': 'test'}, {'agent_id': 'a999'},
    {'agent_id': []}, {'task_id': 'not-a-uuid'}, {'max_cost_usd': 0},
    {'max_cost_usd': True}, {'max_cost_usd': 'NaN'},
    {'data_classification': 'LOCAL_ONLY'}, {'context': 'password=private-fixture'},
    {'context': 'x' * 2049}, {'timeout_seconds': 31},
    {'primary_timeout_seconds': True}, {'primary_timeout_seconds': 31},
    {'cancelled': []},
])
def test_identity_disclosure_and_task_bounds_fail_before_admission(changes):
    arguments, calls, phases, router_calls, _ = fixture()
    arguments.update(changes)
    with pytest.raises(ProviderFailure):
        execute_direct_qa(**arguments)
    assert calls == phases == router_calls == []


@pytest.mark.parametrize('field,value', [
    ('reservation_id', 'invalid'), ('binding_sha256', 'b' * 64),
    ('price_contract_sha256', ''), ('price_contract_sha256', 'NaN'),
    ('expires_monotonic', 100.0), ('expires_monotonic', float('nan')),
    ('expires_monotonic', True), ('direct_maximum_charge_usd', '0'),
    ('direct_maximum_charge_usd', '.02'), ('router_maximum_charge_usd', 'Infinity'),
    ('hf_router_provider_id', 'hf-router-approved/other'),
    ('hf_router_model', 'google/gemma-3-4b-it'),
    ('hf_router_model', 'https://arbitrary.invalid/model'),
])
def test_missing_stale_unbound_or_overbudget_reservation_denies_dispatch(field, value):
    arguments, calls, phases, router_calls, _ = fixture()
    trusted_admit = arguments['admit']
    arguments['admit'] = lambda *args: replace(trusted_admit(*args), **{field: value})
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        execute_direct_qa(**arguments)
    assert calls == router_calls == []


def test_direct_success_is_bound_but_not_automatically_qualified_or_metrically_invented():
    arguments, calls, phases, router_calls, _ = fixture()
    result = execute_direct_qa(**arguments)
    assert len(calls) == 1 and router_calls == []
    assert [item[0] for item in phases] == ['reserve', 'direct']
    assert result['answer'] == 'Clara' and result['route'] == 'DIRECT_HF'
    assert result['agent_id'] == 'a18' and result['task_id'] == TASK
    assert result['request_binding_sha256'] == binding_hash(phases[0][1])
    assert result['reservation_id'] == RESERVATION and result['price_contract_sha256'] == 'a' * 64
    assert result['fallback_failures'] == [] and result['automatic_qualification'] is False
    assert result['l7_awarded'] is False
    for field in ('cost_usd', 'input_tokens', 'output_tokens', 'tokens_per_second',
                  'time_to_first_token_ms', 'total_chain_cost_usd'):
        assert result[field] is None
    receipt = json.dumps(result)
    assert 'fixture-only' not in receipt and CONTEXT not in receipt and QUESTION not in receipt


@pytest.mark.parametrize('response,code', [
    (httpx.Response(429, json={}), 'RATE_LIMIT'),
    (httpx.Response(503, json={'error': {'code': 'model_at_capacity'}}), 'CAPACITY'),
])
def test_rejected_direct_admission_runs_one_explicit_task_equivalent_router(response, code):
    arguments, calls, phases, router_calls, _ = fixture(response=response)
    result = execute_direct_qa(**arguments)
    assert len(calls) == len(router_calls) == 1
    assert [item[0] for item in phases] == ['reserve', 'direct', 'hf_router']
    assert result['route'] == 'HF_ROUTER' and result['answer'] == 'Clara'
    assert result['fallback_failures'] == [{'provider': HFServerlessQA.CIRCUIT_ID, 'code': code}]
    assert result['router_task_id'] == ROUTER_TASK
    assert result['router_cost_estimate_usd'] == .00001 and result['total_chain_cost_usd'] is None
    call = router_calls[0]
    assert 0 < call['timeout_seconds'] <= 30
    assert json.loads(call['prompt'].split('QA_INPUT_JSON: ', 1)[1]) == {
        'context': CONTEXT, 'question': QUESTION}
    assert call['reservation'].hf_router_model == MODEL


@pytest.mark.parametrize('fallback', [True, False])
def test_missing_direct_credential_only_allows_separately_approved_router(fallback):
    arguments, calls, phases, router_calls, _ = fixture(resolver=lambda _: None, fallback=fallback)
    if fallback:
        assert execute_direct_qa(**arguments)['route'] == 'HF_ROUTER'
        assert len(router_calls) == 1
    else:
        with pytest.raises(ProviderFailure, match='CREDENTIAL_UNAVAILABLE'):
            execute_direct_qa(**arguments)
        assert router_calls == []
    assert calls == []


@pytest.mark.parametrize('response', [
    httpx.Response(200, json={**SPAN, 'answer': 'wrong'}),
    httpx.Response(200, content=b'{"answer":"Clara","answer":"wrong"}'),
    httpx.Response(500, json={'error': 'ambiguous admitted work'}),
    httpx.Response(429, json={**SPAN, 'error': 'contradictory completed response'}),
    httpx.Response(429, content=b'not-json'),
    httpx.Response(503, json={**SPAN, 'error': {'code': 'model_at_capacity'}}),
    httpx.Response(503, json={'error': 'unspecified'}),
    httpx.Response(401, json={'error': 'credential rejected'}),
])
def test_ambiguous_partial_malformed_or_auth_failure_never_replays(response):
    arguments, calls, phases, router_calls, _ = fixture(response=response)
    with pytest.raises(ProviderFailure) as error:
        execute_direct_qa(**arguments)
    assert error.value.pre_execution is False and len(calls) == 1 and router_calls == []


def test_transport_ambiguity_never_replays():
    arguments, calls, phases, router_calls, _ = fixture(exception=httpx.ReadTimeout('private fixture'))
    with pytest.raises(ProviderFailure, match='PROVIDER_TIMEOUT'):
        execute_direct_qa(**arguments)
    assert len(calls) == 1 and router_calls == []


def test_admission_is_revalidated_and_no_rebinding_allowed():
    arguments, calls, phases, router_calls, _ = fixture()
    trusted_admit = arguments['admit']
    def revoked(binding, previous, phase):
        permit = trusted_admit(binding, previous, phase)
        return replace(permit, price_contract_sha256='b' * 64) if phase == 'direct' else permit
    arguments['admit'] = revoked
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        execute_direct_qa(**arguments)
    assert len(phases) == 2 and calls == router_calls == []


def test_fallback_authority_is_revalidated_before_disclosure():
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    trusted_admit = arguments['admit']
    def revoked(binding, previous, phase):
        permit = trusted_admit(binding, previous, phase)
        return replace(permit, hf_router_model='other/model:provider') if phase == 'hf_router' else permit
    arguments['admit'] = revoked
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        execute_direct_qa(**arguments)
    assert len(calls) == 1 and router_calls == []


@pytest.mark.parametrize('changes', [
    {'agent_id': 'a17'}, {'parent_task_id': ROUTER_TASK}, {'task_id': 'bad'},
    {'task_id': None}, {'agent_id': None}, {'request_binding_sha256': 'b' * 64},
    {'request_binding_sha256': None}, {'reservation_id': TASK},
    {'reservation_id': None}, {'model': 'other/model:provider'},
    {'provider': 'hf-router-other'},
])
def test_wrong_agent_task_context_reservation_or_route_is_rejected(changes):
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    trusted_router = arguments['execute_hf_router']
    arguments['execute_hf_router'] = lambda **kwargs: {**trusted_router(**kwargs), **changes}
    with pytest.raises(ProviderFailure, match='QA_ROUTER_IDENTITY_MISMATCH'):
        execute_direct_qa(**arguments)
    assert len(calls) == len(router_calls) == 1


@pytest.mark.parametrize('value', [None, float('nan'), True, '.002', -1])
def test_router_cost_must_be_known_and_within_its_separate_cap(value):
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    trusted_router = arguments['execute_hf_router']
    arguments['execute_hf_router'] = lambda **kwargs: {**trusted_router(**kwargs), 'actual_cost_usd': value}
    with pytest.raises(ProviderFailure, match='QA_ROUTER_COST_NOT_VERIFIED'):
        execute_direct_qa(**arguments)
    assert len(calls) == len(router_calls) == 1


@pytest.mark.parametrize('value', ['wrong', '', ' ', '\ud800', {'answer': 'Clara'}])
def test_router_requires_exact_nonempty_source_span(value):
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    trusted_router = arguments['execute_hf_router']
    arguments['execute_hf_router'] = lambda **kwargs: {**trusted_router(**kwargs), 'result': value}
    with pytest.raises(ProviderFailure, match='INVALID_QA_ANSWER_SPAN'):
        execute_direct_qa(**arguments)
    assert len(calls) == len(router_calls) == 1


def test_raw_router_exception_is_sanitized_without_third_route():
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    def failed_router(**kwargs):
        router_calls.append(kwargs)
        raise RuntimeError('Bearer private-fixture-token')
    arguments['execute_hf_router'] = failed_router
    with pytest.raises(ProviderFailure, match='QA_ROUTER_EXECUTION_FAILURE') as error:
        execute_direct_qa(**arguments)
    assert 'private' not in str(error.value) and len(calls) == len(router_calls) == 1


def test_shared_deadline_excludes_late_direct_result_without_fallback():
    arguments, calls, phases, router_calls, clock = fixture()
    original_handler = arguments['qa'].transport.handler
    def late(request):
        response = original_handler(request)
        clock.value += 31
        return response
    arguments['qa'].transport = httpx.MockTransport(late)
    with pytest.raises(ProviderFailure, match='TASK_TIMEOUT'):
        execute_direct_qa(**arguments)
    assert len(calls) == 1 and router_calls == []


def test_shared_deadline_rechecked_after_direct_failure_before_fallback():
    arguments, calls, phases, router_calls, clock = fixture(response=httpx.Response(429, json={}))
    original_handler = arguments['qa'].transport.handler
    def late(request):
        response = original_handler(request)
        clock.value += 30
        return response
    arguments['qa'].transport = httpx.MockTransport(late)
    with pytest.raises(ProviderFailure, match='TASK_TIMEOUT'):
        execute_direct_qa(**arguments)
    assert len(calls) == 1 and router_calls == []


@pytest.mark.parametrize('state', [True, 'false', None])
def test_precancel_or_malformed_cancellation_state_prevents_dispatch(state):
    arguments, calls, phases, router_calls, _ = fixture()
    arguments['cancelled'] = lambda: state
    with pytest.raises(ProviderFailure) as error:
        execute_direct_qa(**arguments)
    assert error.value.code in {'CANCELLED', 'CANCELLATION_STATE_INVALID'}
    assert calls == phases == router_calls == []


def test_cancel_after_dispatch_never_becomes_safe_fallback():
    arguments, calls, phases, router_calls, _ = fixture(response=httpx.Response(429, json={}))
    arguments['cancelled'] = lambda: bool(calls)
    circuits = ProviderCircuits()
    arguments['circuits'] = circuits
    with pytest.raises(ProviderFailure, match='CANCELLED') as error:
        execute_direct_qa(**arguments)
    assert error.value.pre_execution is False and len(calls) == 1 and router_calls == []
    state = circuits.snapshot(HFServerlessQA.CIRCUIT_ID)
    assert state['active_permits'] == 0
    assert state['consecutive_provider_failures'] == 0


def test_direct_threshold_open_suppression_and_new_half_open_recovery():
    arguments, calls, phases, router_calls, clock = fixture(response=httpx.Response(429, json={}))
    circuits = ProviderCircuits(failure_threshold=2, cooldown_seconds=10, clock=clock)
    arguments['circuits'] = circuits
    for _ in range(2):
        assert execute_direct_qa(**arguments)['route'] == 'HF_ROUTER'
    assert len(calls) == 2 and circuits.snapshot(HFServerlessQA.CIRCUIT_ID)['circuit_state'] == 'OPEN'
    result = execute_direct_qa(**arguments)
    assert len(calls) == 2 and result['fallback_failures'][0]['code'] == 'PROVIDER_CIRCUIT_OPEN'
    clock.value += 10
    def recovered(request):
        calls.append(request)
        return httpx.Response(200, json=SPAN)
    arguments['qa'].transport = httpx.MockTransport(recovered)
    result = execute_direct_qa(**arguments)
    assert result['route'] == 'DIRECT_HF' and result['circuit_recovery_probe'] is True
    assert len(calls) == len(router_calls) == 3
    state = circuits.snapshot(HFServerlessQA.CIRCUIT_ID)
    assert state['circuit_state'] == 'CLOSED' and state['consecutive_provider_failures'] == 0


def test_malformed_half_open_result_does_not_claim_recovery_or_replay():
    arguments, calls, phases, router_calls, clock = fixture(response=httpx.Response(429, json={}))
    circuits = ProviderCircuits(failure_threshold=1, cooldown_seconds=10, clock=clock)
    arguments['circuits'] = circuits
    execute_direct_qa(**arguments)
    clock.value += 10
    def malformed(request):
        calls.append(request)
        return httpx.Response(200, json={**SPAN, 'end': 12})
    arguments['qa'].transport = httpx.MockTransport(malformed)
    with pytest.raises(ProviderFailure, match='INVALID_QA_ANSWER_SPAN'):
        execute_direct_qa(**arguments)
    assert len(calls) == 2 and len(router_calls) == 1
    state = circuits.snapshot(HFServerlessQA.CIRCUIT_ID)
    assert state['circuit_state'] == 'OPEN' and state['active_permits'] == 0
