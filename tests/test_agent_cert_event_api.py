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
from app import agent_cert_tool_events as tool_events
from app.action_records import ActionLedger, ActionRecord, DirectExecutor
from app.artifact_factory import ArtifactFactory
from app.deterministic_ops import DeterministicOps

SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
RUNTIME = {'source_revision': SOURCE, 'image_digest': IMAGE,
           'host_id': 'fixture-host', 'version': 'fixture-version'}
AUTH = {'Authorization': 'Bearer public-test-fixture-owner'}
TOOL_FULL_ACTIONS = {tool_events.tool_action_type(case, phase='full')
                     for case in tool_events.SUPPORTED_CASES}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import objective_api
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'public-test-fixture-owner')
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
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


def tool_full(env, case):
    """Actual temporary setup/read/result operations, not a virtual full pair."""
    task = str(uuid.uuid4())
    ledger = ActionLedger(env.root / 'action-records.jsonl')
    executor = DirectExecutor(ledger)
    factory = ArtifactFactory(env.root / 'artifacts')
    def create(raw):
        metadata = factory.create(kind='json', content=raw.decode(), task_id=task, creator='a19',
            provenance=tool_events.PROVENANCE, runtime_revision=SOURCE)
        assert factory.retrieve(metadata['artifact_id']) == (metadata, raw)
        return metadata
    def record(phase):
        return ActionRecord(task, 'a19', tool_events.tool_action_type(case, phase=phase), 'artifact-factory',
            parameters_summary={'schema_version': tool_events.INPUT_SCHEMA if phase == 'setup' else tool_events.RESULT_SCHEMA,
                                'read_only_observations': True})
    try:
        setup = executor.execute(record('setup'), lambda: create(tool_events.input_bytes(case)))
        folder = env.root / 'artifacts' / setup['artifact_id']
        assert {path.name for path in folder.iterdir()} == {'artifact.json', 'metadata.json'}
        read = None
        if case not in tool_events.PROPOSAL_CASES:
            read = ActionRecord(task, 'a19', tool_events.tool_action_type(case, phase='read'), 'provided_context.read',
                target=tool_events.MISSING_SLOT, parameters_summary={'schema_version': tool_events.INPUT_SCHEMA,
                    'setup_artifact_id': setup['artifact_id'], 'relative_path': tool_events.MISSING_SLOT,
                    'read_only_observations': True})
        reader = DeterministicOps(source_version=SOURCE)
        available_raw = None
        if case in tool_events.AVAILABLE_CASES:
            available = ActionRecord(task,'a19',tool_events.tool_action_type(case,phase='available'),
                'provided_context.read',target='artifact.json',parameters_summary={
                    'schema_version':tool_events.INPUT_SCHEMA,'setup_artifact_id':setup['artifact_id'],
                    'relative_path':'artifact.json','expected_sha256':setup['sha256'],'read_only_observations':True})
            def consume():
                raw,digest = reader.retrieve_file(folder,'artifact.json',expected_sha256=setup['sha256'])
                return {'source_sha256':digest,'result':raw.decode()}
            available_raw = executor.execute(available,consume)['result'].encode()
            assert available_raw == tool_events.input_bytes(case)
        if read is not None:
            with pytest.raises(FileNotFoundError) as missing:
                executor.execute(read, lambda: reader.retrieve_file(folder, tool_events.MISSING_SLOT))
            assert missing.value.errno == 2 and Path(missing.value.filename) == folder / tool_events.MISSING_SLOT
        assert factory.retrieve(setup['artifact_id']) == (setup, tool_events.input_bytes(case))
        health_rows = None
        if case == tool_events.HEALTH_CASE:
            assert ledger.flush(timeout=1) is True
            health_rows = (env.root / 'action-records.jsonl').read_text().splitlines(keepends=True)[-6:]
        result = executor.execute(record('result'), lambda: create(tool_events.expected_artifact_bytes(case,available_bytes=available_raw,
            **({'source_revision':SOURCE} if case == tool_events.REVALIDATION_CASE else
                {'source_revision':SOURCE, 'original_health_rows':health_rows, 'task_id':task}
                if case == tool_events.HEALTH_CASE else {}))))
        assert result['artifact_id'] != setup['artifact_id']
        assert ledger.flush(timeout=1) is True
    finally:
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


@pytest.mark.parametrize('action', sorted(api._ACTIONS - TOOL_FULL_ACTIONS))
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


@pytest.mark.parametrize('case', tool_events.SUPPORTED_CASES)
def test_ordinary_pair_cannot_masquerade_as_virtual_tool_full_span(env, monkeypatch, case):
    action = tool_events.tool_action_type(case, phase='full')
    task, before = pair(env, action)
    assert len(before.splitlines()) == 2
    monkeypatch.setattr(ActionLedger, 'flush', lambda *a, **k: pytest.fail('Original read cannot flush a ledger'))
    response = env.client.get(url(task, action), headers=AUTH)
    assert response.status_code == 503 and 'original_lines' not in response.json()
    assert str(env.root) not in response.text
    assert (env.root / 'action-records.jsonl').read_bytes() == before


@pytest.mark.parametrize('case', tool_events.SUPPORTED_CASES)
def test_tool_full_returns_exact_actual_original_records_without_mutation_or_flush(env, monkeypatch, case):
    task, before = tool_full(env, case)
    lines = before.decode().splitlines(keepends=True)
    original = [json.loads(line) for line in lines]
    phases = ('setup','available','result') if case in tool_events.PROPOSAL_CASES else (
        ('setup','available','read','result') if case in (tool_events.DEGRADATION_CASE, tool_events.HEALTH_CASE) else ('setup','read','result'))
    if case in (tool_events.DEGRADATION_CASE, tool_events.HEALTH_CASE):
        assert len(original) == 8 and len({event['action_id'] for event in original}) == 4
    else:
        assert len(original) == 6 and len({event['action_id'] for event in original}) == 3
    assert len(original) == 2 * len(phases) and len({event['action_id'] for event in original}) == len(phases)
    assert [event['phase'] for event in original] == ['started', 'completed'] * len(phases)
    assert [event['action_type'] for event in original] == [tool_events.tool_action_type(case, phase=phase)
        for phase in phases for _ in range(2)]
    for phase,completion in zip(phases,original[1::2]):
        assert completion['success'] is (phase != 'read')
        if phase == 'read':assert completion['error'] == 'FileNotFoundError'
        elif phase == 'available':assert completion['result_summary']['output_sha256'] == tool_events.sha(tool_events.input_bytes(case))
    assert tool_events.validate_full_span(lines, task, case) == original
    for previous, current in zip(original, original[1:]):
        assert current['sequence'] == previous['sequence'] + 1 and current['previous_sha256'] == previous['sha256']
    files_before = {str(path.relative_to(env.root)): path.read_bytes() for path in env.root.rglob('*') if path.is_file()}
    monkeypatch.setattr(ActionLedger, 'flush', lambda *a, **k: pytest.fail('Original read cannot flush a ledger'))
    monkeypatch.setattr(ActionLedger, 'emit', lambda *a, **k: pytest.fail('Original read cannot mutate a ledger'))
    action = tool_events.tool_action_type(case, phase='full')
    response = env.client.get(url(task, action), headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {'schema': 'prime.original-action-span.v1', 'task_id': task,
        'action_type': action, 'source_revision': SOURCE, 'original_lines': lines}
    assert ''.join(response.json()['original_lines']).encode() == before
    assert {str(path.relative_to(env.root)): path.read_bytes() for path in env.root.rglob('*') if path.is_file()} == files_before
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'


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
