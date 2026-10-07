"""Independent small security checks: no lifespan, worker, provider or network."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest


PATH = '/control/api/gods-eye'
TOKEN = 'gods-eye-independent-synthetic-operator'


def tree_bytes(root: Path):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def assert_empty_queue_read_has_no_domain_mutation(root: Path, before):
    after = tree_bytes(root)
    # SQLite mode=ro may create coordination SHM and a zero-byte WAL for an
    # otherwise dormant WAL-mode database. This is not a write to queue rows,
    # and immutable=1 would be unsafe for the actual concurrently changing DB.
    assert set(after) - set(before) <= {'queue.db-shm', 'queue.db-wal'}
    assert {name: after[name] for name in before} == before
    wal = root / 'queue.db-wal'
    if wal.exists():
        assert wal.stat().st_size == 0
    shm = root / 'queue.db-shm'
    if shm.exists():
        assert shm.stat().st_size == 32768


@pytest.fixture
def surface(monkeypatch, tmp_path):
    data = tmp_path / 'synthetic-data'
    monkeypatch.setenv('PRIME_DATA_DIR', str(data))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(data / 'queue.db'))
    monkeypatch.setenv('PRIME_SPINE_TOKEN', TOKEN)
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'a' * 40)
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('HF_TOKEN', 'DO_NOT_EXPORT_HF_SECRET_SENTINEL')
    from app import production_entry as entry
    from app import compute_queue_api as compute
    from app.action_records import close_ledgers
    from app.job_queue import JobQueue
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(compute, 'queue', JobQueue(str(data / 'queue.db'), compute.POLICY))
    close_ledgers()
    # No context manager: running the application lifespan would start workers.
    client = TestClient(entry.app, base_url='http://127.0.0.1:8000',
                        client=('127.0.0.1', 45120))
    yield entry, client, data
    client.close()
    close_ledgers()


@pytest.mark.parametrize('headers', [
    {'Host': 'attacker.invalid'},
    {'Host': '127.0.0.1@attacker.invalid'},
    {'Origin': 'http://attacker.invalid'},
    {'Origin': 'http://localhost:8000'},
    {'Origin': 'https://127.0.0.1:8000'},
    {'Origin': 'http://127.0.0.1:9999'},
    {'Origin': 'null'},
    {'Sec-Fetch-Site': 'cross-site'},
    {'Sec-Fetch-Site': 'same-site'},
    [('Host', '127.0.0.1:8000'), ('Host', 'attacker.invalid')],
    [('Origin', 'http://127.0.0.1:8000'), ('Origin', 'http://attacker.invalid')],
])
def test_untrusted_transport_denied_before_domain_reads(surface, headers):
    _, client, data = surface
    before = tree_bytes(data)
    response = client.get(PATH, headers=headers)
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'no-store'
    assert tree_bytes(data) == before
    assert TOKEN not in response.text


def test_missing_server_side_operator_configuration_is_not_anonymous_access(surface, monkeypatch):
    _, client, data = surface
    before = tree_bytes(data)
    monkeypatch.delenv('PRIME_SPINE_TOKEN')
    response = client.get(PATH)
    assert response.status_code == 503
    assert tree_bytes(data) == before
    assert TOKEN not in response.text


@pytest.mark.parametrize('headers', [
    {'X-Forwarded-For': '127.0.0.1'},
    {'X-Real-IP': '127.0.0.1', 'X-Forwarded-Host': '127.0.0.1:8000'},
    {'Forwarded': 'for=127.0.0.1;host=127.0.0.1:8000;proto=https'},
])
def test_remote_peer_cannot_gain_operator_access_from_forwarding(surface, headers):
    entry, _, data = surface
    before = tree_bytes(data)
    client = TestClient(entry.app, base_url='http://127.0.0.1:8000',
                        client=('192.0.2.81', 45121))
    try:
        response = client.get(PATH, headers=headers)
    finally:
        client.close()
    assert response.status_code == 403
    assert tree_bytes(data) == before


def test_post_cannot_turn_readonly_snapshot_into_a_mutation(surface):
    _, client, data = surface
    before = tree_bytes(data)
    response = client.post(PATH, headers={'Origin': 'http://127.0.0.1:8000'},
                           json={'dispatch': True, 'model': 'not-permitted'})
    # The mounted Direct app returns 404 for unsupported verbs; either form
    # denies the mutation without creating a task or changing a domain store.
    assert response.status_code in (404, 405)
    assert tree_bytes(data) == before


def test_authorized_snapshot_read_has_no_secret_or_domain_creation(surface, monkeypatch):
    from app import gods_eye_api as api
    _, client, data = surface
    monkeypatch.setattr(api, '_CACHE', None)
    before = tree_bytes(data)
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert_empty_queue_read_has_no_domain_mutation(data, before)
    assert TOKEN not in response.text
    assert 'DO_NOT_EXPORT_HF_SECRET_SENTINEL' not in response.text
    result = response.json()
    assert len(result['agents']) == 21
    assert result['access_scope'] == 'LOOPBACK_OPERATOR_NOT_PWA_IDENTITY_PROOF'
    assert result['runtime']['identity_verification'] == 'UNVERIFIED'
    assert result['certification']['l7_count'] is None
    assert all(row['l7_status'] == 'UNKNOWN' for row in result['agents'])
    assert result['hugging_face']['registration_status'] == 'UNKNOWN'


def test_ordinary_snapshot_never_reads_protected_domains(surface, monkeypatch):
    from app import gods_eye_api as api, hf_observation_api
    from app.agent_certification import AgentCertificationRegistry
    monkeypatch.setattr(api, '_CACHE', None)
    monkeypatch.setattr(AgentCertificationRegistry, 'matrix', lambda *_: pytest.fail('Protected certification must not be read'))
    monkeypatch.setattr(hf_observation_api, 'inspect_hf', lambda *a, **k: pytest.fail('Protected HF must not be read'))
    response = surface[1].get(PATH)
    assert response.status_code == 200
    assert response.json()['protected_domain_access'] == 'NOT_REQUESTED'


@pytest.mark.parametrize('suffix', ['', '/why?agent_id=a20', '/dependencies?subject=result-1'])
def test_wrong_supplied_bearer_cannot_fall_back_to_ambient_operator_access(surface, suffix):
    response = surface[1].get(PATH + suffix, headers={'Authorization': 'Bearer wrong'})
    assert response.status_code == 401


def test_protected_cache_never_leaks_to_ordinary_dashboard_read(surface, monkeypatch):
    from app import gods_eye_api as api
    monkeypatch.setattr(api, '_CACHE', None)
    explicit = surface[1].get(PATH, headers={'Authorization': 'Bearer ' + TOKEN})
    assert explicit.status_code == 200
    assert explicit.json()['protected_domain_access'] == 'EXPLICIT_BEARER'
    ordinary = surface[1].get(PATH)
    assert ordinary.status_code == 200
    assert ordinary.json()['protected_domain_access'] == 'NOT_REQUESTED'
    assert ordinary.json()['certification']['l7_count'] is None


@pytest.mark.parametrize('endpoint,parameters', [
    ('why', {'agent_id': 'a20 . ?x ?p ?o'}),
    ('why', {'agent_id': '../../private'}),
    ('why', {'agent_id': 'a20' + 'x' * 4096}),
    ('dependencies', {'subject': 'result:bad UNION {?s ?p ?o}'}),
])
def test_fixed_semantic_queries_reject_arbitrary_query_subject(surface, monkeypatch, endpoint, parameters):
    from app import gods_eye_api as api
    _, client, data = surface
    monkeypatch.setattr(api, '_CACHE', None)
    before = tree_bytes(data)
    response = client.get(PATH + '/' + endpoint, params=parameters)
    assert response.status_code == 422
    assert_empty_queue_read_has_no_domain_mutation(data, before)
    assert TOKEN not in response.text
    assert response.json()['detail'] == 'Semantic subject unavailable or invalid'


def projection_inputs():
    from app.agent_registry import load_agent_registry
    registry = load_agent_registry()
    task_id, job_id = str(uuid4()), str(uuid4())
    private = 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL'
    metadata = {'task_id': task_id, 'created_at': '2026-10-07T04:00:00Z',
        'completed_at': '2026-10-07T04:00:01Z',
        'agent_execution': [{'selected_agent_id': 'a20', 'registry_binding': 'VERIFIED'}],
        'runtime': {'source_revision': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64,
                    'private_context': private}, 'prompt': private, 'context': private}
    return dict(runtime={'source_revision': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64,
                         'token': private},
        certification_rows=[{'agent_id': row['id'], 'level': 'L0', 'trust_state': 'UNPROVEN',
                             'missing': {}, 'private_evidence': private}
                            for row in registry['agents']],
        jobs=[{'id': job_id, 'agent': 'a20', 'status': 'completed',
               'prompt': private, 'result': private, 'secret_ref': private}],
        objectives=[{'id': task_id, 'revision': 0, 'state': 'COMPLETED',
                     'result': {'text': private, 'verification_status': 'VERIFIED',
                                'l7_status': 'L7-CURRENT'}, 'execution_metadata': metadata}],
        lens={task_id: {'task_id': task_id, 'record_id': 'objective:' + task_id + ':r0',
                       'integrity': 'VALID', 'currentness': 'CURRENT',
                       'verification': 'VERIFIED', 'observed': {'result_digest': {'algorithm': 'sha256', 'value': 'c' * 64}},
                       'raw_context': private, 'private_key': private}},
        now=datetime(2026, 10, 7, 4, 1, tzinfo=timezone.utc))


def test_projection_retains_actual_noncontiguous_population_and_no_private_data():
    from app import gods_eye_api as api
    from app.agent_registry import load_agent_registry
    inputs = projection_inputs()
    result = api.project_snapshot(**inputs)
    actual = {row['id'] for row in load_agent_registry()['agents']}
    assert len(actual) == 21 and 'a26' in actual and 'a29' in actual and 'a03' not in actual
    assert {row['agent_id'] for row in result['agents']} == actual
    assert set(result['registry']['authoritative_ids']) == actual
    encoded = json.dumps(result)
    for private in ('DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL', 'secret_ref', 'private_key',
                    'private_evidence', 'raw_context'):
        assert private not in encoded
    assert result['access_scope'] == 'LOOPBACK_OPERATOR_NOT_PWA_IDENTITY_PROOF'


def test_projection_completion_and_lens_valid_current_do_not_award_l7():
    from app import gods_eye_api as api
    result = api.project_snapshot(**projection_inputs())
    assert result['certification']['l7_count'] == 0
    assert all(row['l7_status'] == 'NOT_L7' for row in result['agents'])
    assert len(result['results']) == 1
    observed = result['results'][0]
    assert observed['integrity'] == 'VALID' and observed['currentness'] == 'CURRENT'
    assert observed['verification'] == observed['environment_verification'] == 'UNVERIFIED'
    assert result['runtime']['identity_verification'] == 'UNVERIFIED'
    assert all(gate['status'] != 'VERIFIED' for gate in result['gates'])


def test_projection_stale_or_wrong_task_lens_is_not_current_evidence():
    from app import gods_eye_api as api
    inputs = projection_inputs()
    task_id = inputs['objectives'][0]['id']
    inputs['lens'][task_id]['currentness'] = 'STALE'
    result = api.project_snapshot(**inputs)
    assert result['results'][0]['currentness'] == 'STALE'
    inputs['lens'][task_id]['task_id'] = str(uuid4())
    result = api.project_snapshot(**inputs)
    assert result['results'][0]['integrity'] == 'UNKNOWN'
    assert result['results'][0]['currentness'] == 'UNKNOWN'
    assert result['results'][0]['evidence_ref'] is None


@pytest.mark.parametrize('digest,expected', [
    ({'algorithm': 'sha256', 'value': 'd' * 64}, 'd' * 64),
    ({'algorithm': 'sha1', 'value': 'd' * 64}, None),
    ({'algorithm': 'sha256', 'value': 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL'}, None),
])
def test_projection_uses_actual_lens_digest_contract_without_awarding_truth(digest, expected):
    from app import gods_eye_api as api
    inputs = projection_inputs()
    task_id = inputs['objectives'][0]['id']
    inputs['lens'][task_id]['observed']['result_digest'] = digest
    result = api.project_snapshot(**inputs)
    assert result['results'][0]['result_sha256'] == expected
    assert result['results'][0]['verification'] == 'UNVERIFIED'
    assert result['certification']['l7_count'] == 0
    assert 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL' not in json.dumps(result)


def test_projection_unknown_agent_is_not_relabelled_as_permanent():
    from app import gods_eye_api as api
    inputs = projection_inputs()
    inputs['jobs'][0]['agent'] = 'a03'
    inputs['objectives'][0]['execution_metadata']['agent_execution'][0]['selected_agent_id'] = 'a03'
    result = api.project_snapshot(**inputs)
    assert not result['results']
    assert all(row['runtime_activation'] == 'UNVERIFIED' for row in result['agents'])


@pytest.mark.parametrize('dimension', ['agent_execution_none', 'runtime_string', 'lens_observed_string'])
def test_projection_malformed_private_domain_shape_does_not_crash_or_disclose(dimension):
    from app import gods_eye_api as api
    inputs = projection_inputs()
    metadata = inputs['objectives'][0]['execution_metadata']
    if dimension == 'agent_execution_none':
        metadata['agent_execution'] = None
    elif dimension == 'runtime_string':
        metadata['runtime'] = 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL'
    else:
        task_id = inputs['objectives'][0]['id']
        inputs['lens'][task_id]['observed'] = 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL'
    result = api.project_snapshot(**inputs)
    assert len(result['agents']) == 21
    assert 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL' not in json.dumps(result)
    assert result['certification']['l7_count'] == 0


@pytest.mark.parametrize('dimension', ['job_agent', 'execution_agent', 'certification_agent'])
def test_non_scalar_identity_cannot_crash_metadata_projection(dimension):
    from app import gods_eye_api as api
    inputs = projection_inputs()
    if dimension == 'job_agent':
        inputs['jobs'][0]['agent'] = {'private': 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL'}
    elif dimension == 'execution_agent':
        inputs['objectives'][0]['execution_metadata']['agent_execution'][0]['selected_agent_id'] = []
    else:
        inputs['certification_rows'][0]['agent_id'] = []
    result = api.project_snapshot(**inputs)
    assert len(result['agents']) == 21
    assert 'DO_NOT_EXPORT_PRIVATE_CONTEXT_SENTINEL' not in json.dumps(result)
    assert result['certification']['l7_count'] in (0, None)

