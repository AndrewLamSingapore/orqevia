"""Real temporary ledgers and HTTP authorization, not live certification."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import agent_cert_event_api as api
from app.action_records import ActionLedger, ActionRecord, DirectExecutor

SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
RUNTIME = {'source_revision': SOURCE, 'image_digest': IMAGE,
           'host_id': 'fixture-host', 'version': 'fixture-version'}
AUTH = {'Authorization': 'Bearer public-test-fixture-owner'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import objective_api
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'public-test-fixture-owner')
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(objective_api, 'runtime_snapshot', lambda: copy.deepcopy(RUNTIME))
    app = FastAPI()
    app.include_router(api.router)
    return SimpleNamespace(client=TestClient(app), root=tmp_path)


def pair(env, action_type='agent.certification.initialization.artifact'):
    task = str(uuid.uuid4())
    ledger = ActionLedger(env.root / 'action-records.jsonl')
    record = ActionRecord(task, 'a19', action_type, 'artifact-factory')
    DirectExecutor(ledger).execute(record, lambda: {'artifact_id': 'c' * 32})
    assert ledger.flush(timeout=1) is True
    assert ledger.close() is True
    return task, (env.root / 'action-records.jsonl').read_bytes()


def url(task, action='agent.certification.initialization.artifact'):
    return f'/api/agent-cert-events/actions/{task}?action_type={action}'


@pytest.mark.parametrize('path', ['/runtime', '/actions/not-a-uuid?action_type=unsupported'])
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer wrong'}])
def test_authentication_precedes_identifier_validation_and_no_ledger_read(env, monkeypatch, path, headers):
    monkeypatch.setattr(api, 'read_action_span', lambda *a: pytest.fail('Unauthorized ledger read'))
    response = env.client.get('/api/agent-cert-events' + path, headers=headers)
    assert response.status_code == 401
    assert not list(env.root.iterdir())


def test_runtime_uses_existing_domain_identity_not_public_readiness(env):
    result = env.client.get('/api/agent-cert-events/runtime', headers=AUTH)
    assert result.status_code == 200 and result.json() == RUNTIME
    assert result.headers['cache-control'] == 'private, no-store'
    assert result.headers['x-content-type-options'] == 'nosniff'
    assert not list(env.root.iterdir())


@pytest.mark.parametrize('action', sorted(api._ACTIONS))
def test_read_returns_exact_original_bytes_without_mutation_or_flush(env, monkeypatch, action):
    task, before = pair(env, action)
    response = env.client.get(url(task, action), headers=AUTH)
    assert response.status_code == 200
    result = response.json()
    assert result == {'schema': 'prime.original-action-span.v1', 'task_id': task,
                      'action_type': action, 'source_revision': SOURCE,
                      'original_lines': before.decode().splitlines(keepends=True)}
    assert ''.join(result['original_lines']).encode() == before
    assert (env.root / 'action-records.jsonl').read_bytes() == before
    assert not any(key in result for key in ('test_result', 'certification', 'attestation', 'health'))
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('task,action', [('../escape', 'runtime.status.artifact'),
    ('not-a-uuid', 'runtime.status.artifact'), (str(uuid.uuid4()), 'inference.run'),
    (str(uuid.uuid4()), '../action-records.jsonl')])
def test_identifier_and_action_allowlist_fail_closed(env, monkeypatch, task, action):
    monkeypatch.setattr(api, 'read_action_span', lambda *a: pytest.fail('Invalid ledger read'))
    response = env.client.get(url(task, action), headers=AUTH)
    assert response.status_code in {404, 422}
    assert not list(env.root.iterdir())


def test_missing_ledger_is_redacted_and_not_created(env):
    response = env.client.get(url(str(uuid.uuid4())), headers=AUTH)
    assert response.status_code == 503
    assert str(env.root) not in response.text
    assert not list(env.root.iterdir())


def test_wrong_task_is_not_exported(env):
    _, before = pair(env)
    response = env.client.get(url(str(uuid.uuid4())), headers=AUTH)
    assert response.status_code == 503
    assert 'original_lines' not in response.json()
    assert (env.root / 'action-records.jsonl').read_bytes() == before


def test_tampered_persisted_hash_rejected_and_preserved(env):
    task, before = pair(env)
    damaged = before.replace(b'"agent_id": "a19"', b'"agent_id": "a18"', 1)
    assert damaged != before
    (env.root / 'action-records.jsonl').write_bytes(damaged)
    response = env.client.get(url(task), headers=AUTH)
    assert response.status_code == 503
    assert (env.root / 'action-records.jsonl').read_bytes() == damaged


def test_runtime_drift_denies_original_span(env, monkeypatch):
    from app import objective_api
    task, before = pair(env)
    snapshots = iter((RUNTIME, {**RUNTIME, 'source_revision': 'd' * 40}))
    monkeypatch.setattr(objective_api, 'runtime_snapshot', lambda: next(snapshots))
    response = env.client.get(url(task), headers=AUTH)
    assert response.status_code == 503
    assert (env.root / 'action-records.jsonl').read_bytes() == before


def test_busy_read_denied_without_ledger_access(env, monkeypatch):
    monkeypatch.setattr(api, 'read_action_span', lambda *a: pytest.fail('Busy ledger read'))
    assert api._read_slot.acquire(blocking=False)
    try:
        response = env.client.get(url(str(uuid.uuid4())), headers=AUTH)
        assert response.status_code == 429
    finally:
        api._read_slot.release()


@pytest.mark.parametrize('lines', [[1, 2], ['{}', '{}'], ['{}\n'], ['x' * 65537 + '\n'] * 2])
def test_malformed_original_span_fails_closed(lines):
    with pytest.raises(ValueError):
        api._original_chain(lines, str(uuid.uuid4()), 'runtime.status.artifact')


def test_missing_completed_event_is_uncertainty_not_completion(env):
    task, before = pair(env)
    partial = before.splitlines(keepends=True)[0]
    (env.root / 'action-records.jsonl').write_bytes(partial)
    response = env.client.get(url(task), headers=AUTH)
    assert response.status_code == 503
    assert (env.root / 'action-records.jsonl').read_bytes() == partial


def test_production_mount_preserves_explicit_bearer_for_new_routes(env):
    from app.production_entry import app
    client = TestClient(app, client=('127.0.0.1', 1234), base_url='http://127.0.0.1:8000')
    assert client.get('/health').status_code == 200  # Public readiness is not Owner auth.
    assert client.get('/api/agent-cert-events/runtime').status_code == 401
    response = client.get('/api/agent-cert-events/runtime', headers=AUTH)
    assert response.status_code == 200 and response.json() == RUNTIME
