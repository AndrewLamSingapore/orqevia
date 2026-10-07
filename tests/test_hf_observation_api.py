"""Small read-only HF inspection fixtures; no inference, network or credentials."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest

from app import hf_observation_api as observation
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import HuggingFaceProvider


AUTH = 'Bearer fixture-hf-inspection'
NOW = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_SPINE_TOKEN', AUTH[7:])
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path / 'does-not-exist'))
    monkeypatch.setattr(observation, '_now', lambda: NOW)
    entry = {'id': 'hf-fixture', 'model': 'fixture/model:provider',
             'provider_kind': 'huggingface', 'enabled': True,
             'qualification_status': 'QUALIFIED', 'secret_ref': 'file:HF_TOKEN',
             'endpoint': HuggingFaceProvider.ENDPOINT, 'location': 'cloud'}
    entries = [entry]
    monkeypatch.setattr(observation, 'load_catalog', lambda: entries)
    circuits = ProviderCircuits(clock=lambda: 0.0, failure_threshold=1)
    monkeypatch.setattr(observation.cloud_execution, 'PROVIDER_CIRCUITS', circuits)
    calls = []
    def adapter(item):
        calls.append(item['id'])
        return HuggingFaceProvider('file:HF_TOKEN', secret_resolver=lambda ref: 'PRIVATE_TOKEN_SENTINEL')
    monkeypatch.setattr(observation.cloud_execution, 'adapter_for', adapter)
    return entries, circuits, calls, tmp_path / 'does-not-exist'


def _digest(attempt):
    unsigned = {key: value for key, value in attempt.items() if key != 'evidence_sha256'}
    attempt['evidence_sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _lens_fixture():
    task_id = str(uuid.uuid4())
    attempt = {'attempt_id': uuid.uuid4().hex, 'queue_job_id': str(uuid.uuid4()),
        'agent_id': 'a20', 'requested_provider': 'hf-fixture',
        'requested_model': 'fixture/model:provider', 'selected_provider': 'hf-fixture',
        'selected_model': 'fixture/model:provider', 'tier': 'MINI', 'success': True,
        'failure_code': None, 'fallback_route': [], 'error_classifications': [],
        'retries': 0, 'total_tokens': 8, 'cached_tokens': 0, 'cost_usd': .000001,
        'elapsed_seconds': .5, 'job_started_at': '2026-10-07T00:59:58+00:00',
        'job_completed_at': '2026-10-07T00:59:59+00:00'}
    _digest(attempt)
    value = {'record_id': f'objective:{task_id}:r0', 'task_id': task_id, 'revision': 0,
        'source': 'PRIME_OBJECTIVE_STORE', 'integrity': 'VALID', 'currentness': 'CURRENT',
        'verification': 'UNVERIFIED', 'result_state': 'COMPLETED',
        'observed': {'task_id': task_id, 'revision': 0, 'agent_ids': ['a20'],
            'execution_state': 'COMPLETED', 'inference_attempts': {
                'schema_version': 'jarvis.inference-attempts.v1', 'source': 'COMPUTE_LEDGER',
                'verification': 'UNVERIFIED', 'digest_scope': 'SANITIZED_PROJECTION_NOT_SIGNATURE',
                'status': 'OBSERVED', 'attempts': [attempt]}},
        'proof': {'producer': 'PRIME_OBJECTIVE_STORE', 'captured_at': '2026-10-07T00:59:59+00:00',
            'currentness_basis': 'OBJECTIVE_SNAPSHOT_EQUALITY', 'time_freshness': 'UNKNOWN',
            'unproven': ['independent_claim_verification', 'production_acceptance',
                         'source_revision_binding', 'runtime_image_binding']}}
    return task_id, value, attempt


def test_wrong_auth_before_catalog_credentials_or_store(setup, monkeypatch):
    monkeypatch.setattr(observation, 'load_catalog', lambda: pytest.fail('must not inspect'))
    with pytest.raises(HTTPException) as error:
        observation.inspect_hf('Bearer incorrect')
    assert error.value.status_code == 401
    assert not setup[3].exists()


def test_readiness_is_not_health_and_no_secret_endpoint_or_store(setup):
    entries, circuits, calls, root = setup
    permit = circuits.acquire('hf-fixture')
    circuits.fail(permit, 'CAPACITY', pre_execution=True)
    report = observation.inspect_hf(AUTH)
    assert calls == ['hf-fixture'] and not root.exists()
    assert report['schema_version'] == 'jarvis.hf-observation.v1'
    provider = report['providers'][0]
    assert provider['readiness'] == 'READY' and provider['circuit']['circuit_state'] == 'OPEN'
    assert report['provider_health'] == provider['provider_health'] == 'UNMEASURED'
    assert report['network_probe_performed'] is False
    assert report['verification'] == 'UNVERIFIED'
    encoded = json.dumps(report)
    for forbidden in ('PRIVATE_TOKEN_SENTINEL', 'https://', 'secret_ref', '/run/secrets', 'file:HF_TOKEN'):
        assert forbidden not in encoded


def test_cached_bounded_lens_is_validated_without_reopening_store(setup, monkeypatch):
    task, evidence, _ = _lens_fixture()
    monkeypatch.setattr(observation, '_read_lens', lambda *_: pytest.fail('must reuse bounded read'))
    report = observation.inspect_hf(AUTH, task, lens_observation=evidence)
    assert report['objective_evidence']['integrity'] == 'VALID'
    assert report['objective_evidence']['independent_signature'] == 'UNVERIFIED'
    evidence['task_id'] = str(uuid.uuid4())
    report = observation.inspect_hf(AUTH, task, lens_observation=evidence)
    assert report['objective_evidence']['status'] == 'INVALID'


def test_cached_lens_never_bypasses_owner_authentication(setup, monkeypatch):
    task, evidence, _ = _lens_fixture()
    monkeypatch.setattr(observation, 'load_catalog', lambda: pytest.fail('auth must precede inspection'))
    with pytest.raises(HTTPException) as failure:
        observation.inspect_hf('Bearer wrong', task, lens_observation=evidence)
    assert failure.value.status_code == 401


def test_disabled_and_non_hf_entries_do_not_resolve_credentials(setup):
    entries, _, calls, root = setup
    entries[0]['enabled'] = False
    entries.append({'id': 'other', 'model': 'other-model', 'provider_kind': 'chat_completions'})
    report = observation.inspect_hf(AUTH)
    assert len(report['providers']) == 1 and report['providers'][0]['readiness'] == 'DISABLED'
    assert calls == [] and not root.exists()


def test_no_hf_registration_and_missing_objective_remain_missing(setup):
    setup[0].clear()
    report = observation.inspect_hf(AUTH, str(uuid.uuid4()))
    assert report['registration_status'] == 'NOT_CONFIGURED'
    assert report['providers'] == []
    assert report['objective_evidence']['status'] == 'MISSING'
    assert not setup[3].exists()


@pytest.mark.parametrize('field,value', [('id', 'https://SECRET'), ('enabled', 'true'),
                                       ('model', 'PRIVATE/secret'), ('model', 'https://SECRET')])
def test_invalid_catalog_does_not_export_arbitrary_strings(setup, field, value):
    setup[0][0][field] = value
    report = observation.inspect_hf(AUTH)
    assert report['registration_status'] == 'UNAVAILABLE' and report['providers'] == []
    assert 'SECRET' not in json.dumps(report)


def test_untrusted_readiness_or_circuit_payload_is_not_health(setup, monkeypatch):
    monkeypatch.setattr(observation.cloud_execution, 'adapter_for', lambda entry: SimpleNamespace(
        health=lambda: {'readiness': 'READY', 'provider_health': 'PASS',
                        'network_probe_performed': False, 'token': 'PRIVATE_RAW_SENTINEL'}))
    report = observation.inspect_hf(AUTH)
    assert report['providers'][0]['readiness'] == 'UNKNOWN'
    assert report['provider_health'] == 'UNMEASURED'
    assert 'PRIVATE_RAW_SENTINEL' not in json.dumps(report)


def test_objective_binding_digest_currentness_and_unknown_flags(setup, monkeypatch):
    task_id, value, attempt = _lens_fixture()
    monkeypatch.setattr(observation, '_read_lens', lambda tid, auth: copy.deepcopy(value))
    report = observation.inspect_hf(AUTH, task_id)
    observed = report['objective_evidence']
    assert observed['status'] == 'OBSERVED' and observed['hf_attempts'] == [attempt]
    assert observed['objective_id'] == task_id and observed['capture_age_seconds'] == 1
    assert observed['verification'] == observed['independent_signature'] == 'UNVERIFIED'
    assert observed['production_acceptance'] == observed['runtime_binding'] == 'UNVERIFIED'
    assert observed['time_freshness'] == 'UNKNOWN'
    value['currentness'] = 'STALE'
    value['proof']['captured_at'] = '2026-10-01T00:00:00+00:00'
    stale = observation.inspect_hf(AUTH, task_id)['objective_evidence']
    assert stale['currentness'] == 'STALE' and stale['capture_age_seconds'] > 86400
    assert stale['time_freshness'] == 'UNKNOWN'


@pytest.mark.parametrize('mutation', ['producer', 'task', 'agent', 'verified', 'future',
                                    'unsafe', 'timestamp_bytes', 'requested_route'])
def test_mismatched_unsafe_or_unsupported_evidence_fails_closed(setup, monkeypatch, mutation):
    task_id, value, attempt = _lens_fixture()
    if mutation == 'producer':
        value['proof']['producer'] = 'PRIVATE_RAW_SENTINEL'
    elif mutation == 'task':
        value['observed']['task_id'] = str(uuid.uuid4())
    elif mutation == 'agent':
        value['observed']['agent_ids'] = ['a18']
    elif mutation == 'verified':
        value['verification'] = 'VERIFIED'
    elif mutation == 'future':
        value['proof']['captured_at'] = '2099-01-01T00:00:00+00:00'
    elif mutation == 'unsafe':
        attempt['raw_prompt'] = 'PRIVATE_RAW_SENTINEL'
        _digest(attempt)
    elif mutation == 'timestamp_bytes':
        attempt['job_started_at'] = '2026-10-07T08:59:58+08:00'
    else:
        attempt['requested_provider'] = 'PRIVATE_RAW_SENTINEL'
        _digest(attempt)
    monkeypatch.setattr(observation, '_read_lens', lambda tid, auth: value)
    report = observation.inspect_hf(AUTH, task_id)
    assert report['objective_evidence']['status'] == 'INVALID'
    assert report['objective_evidence']['verification'] == 'UNVERIFIED'
    assert 'PRIVATE_RAW_SENTINEL' not in json.dumps(report)


def test_tampered_existing_lens_does_not_become_current(setup, monkeypatch):
    task_id, _, _ = _lens_fixture()
    value = {'record_id': f'objective:{task_id}:r0', 'integrity': 'INVALID',
             'currentness': 'UNKNOWN', 'verification': 'UNVERIFIED'}
    monkeypatch.setattr(observation, '_read_lens', lambda tid, auth: value)
    report = observation.inspect_hf(AUTH, task_id)['objective_evidence']
    assert report['status'] == report['integrity'] == 'INVALID'
    assert report['currentness'] == 'UNKNOWN'


def test_bad_task_identity_returns_sanitized_not_found(setup):
    with pytest.raises(HTTPException) as error:
        observation.inspect_hf(AUTH, '../PRIVATE_RAW_SENTINEL')
    assert error.value.status_code == 404
    assert 'PRIVATE_RAW_SENTINEL' not in error.value.detail
