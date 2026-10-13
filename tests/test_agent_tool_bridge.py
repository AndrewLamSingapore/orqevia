"""Disposable queue/store checks, not live agent or provider acceptance."""
import json
import threading
import base64
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.action_records import ActionLedger
from app.agent_tool_bridge import AgentToolBridge, Scope, BridgeConflict, SCHEMA, digest
from app.job_queue import JobQueue, QueuePolicy, Provider

LOCAL = Provider('ollama-fast', 'local', 'fixture-local', 1024, 0, 1)


def envelope(*requests):
    return json.dumps({'schema': SCHEMA, 'requests': list(requests)})


def read_step(**changes):
    return {'id': 'source', 'kind': 'service', 'service': 'private.task.metadata.read',
            'parameters': {}, **changes}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from app import backend_admission
    monkeypatch.setattr(backend_admission, 'reserve_model', lambda *a, **k: None)
    queue = JobQueue(tmp_path / 'queue.db', QueuePolicy(local_ram_mb=2048))
    ledger = ActionLedger(tmp_path / 'audit.jsonl')
    def finish(job_id, output, error=''):
        selected = queue.claim('fixture-worker', [LOCAL])
        assert selected['id'] == job_id
        return queue.finish(job_id, result=output, error=error, retryable=False,
                            inference_receipt={'scope': 'SYNTHETIC_EXECUTOR_TEST_ONLY'})
    def completed(output, agent='a01', classification='LOCAL_ONLY'):
        row = queue.submit(agent=agent, prompt='Original authorized test input',
            model=LOCAL.model, preferred_provider=LOCAL.name, max_retries=0,
            data_classification=classification)
        return finish(row['id'], output)
    def build(**kwargs):
        return AgentToolBridge(tmp_path / 'bridge.db', queue, ledger=ledger,
            runtime={'source_revision': 'UNKNOWN', 'image_digest': 'UNKNOWN'},
            local_model=LOCAL.model, **kwargs)
    yield queue, ledger, completed, finish, build
    ledger.close()


def test_recorded_output_private_tool_real_audit_and_restart_idempotency(rig):
    queue, ledger, completed, _, build = rig
    job = completed(envelope(read_step()))
    bridge = build()
    scope = Scope('Check this task metadata', services=('private.task.metadata.read',))
    registered = bridge.register(job['id'], scope)
    assert registered['original_output_sha256'] == digest(job['result'])
    assert registered['observed_bridge_runtime']['source_revision'] == 'UNKNOWN'
    result = bridge.execute(job['id'])
    receipt = result['steps'][0]['receipt']
    assert receipt['audit_persisted'] and receipt['result']['audit_persisted']
    assert receipt['result']['result']['job_id'] == job['id']
    assert not result['full_role_acceptance_awarded']
    before = ledger.path.read_bytes()
    assert build().execute(job['id']) == result
    assert before == ledger.path.read_bytes()
    assert len(queue.list()) == 1


def test_completed_model_evidence_and_exact_actor_binding_required(rig):
    queue, _, completed, _, build = rig
    job = completed(envelope(read_step()))
    scope = Scope('Original task', services=('private.task.metadata.read',))
    bridge = build()
    bridge.register(job['id'], scope)
    with queue.connect() as db:
        db.execute('UPDATE compute_jobs SET agent=? WHERE id=?', ('a02', job['id']))
    with pytest.raises(BridgeConflict):
        bridge.execute(job['id'])
    queued = queue.submit(agent='a01', prompt='Never executed')
    with pytest.raises(BridgeConflict):
        bridge.register(queued['id'], scope)


@pytest.mark.parametrize('field,value', [('result', 'Changed output'),
    ('prompt', 'Changed original input'), ('provider', 'other-provider'), ('attempts', 2)])
def test_changed_original_execution_cannot_reach_effect(rig, field, value):
    queue, _, completed, _, build = rig
    job = completed(envelope(read_step()))
    calls = []
    bridge = build(service=lambda *a, **k: calls.append(1))
    bridge.register(job['id'], Scope('Original', services=('private.task.metadata.read',)))
    with queue.connect() as db:
        db.execute(f'UPDATE compute_jobs SET {field}=? WHERE id=?', (value, job['id']))
    with pytest.raises(BridgeConflict):
        bridge.execute(job['id'])
    assert calls == []


@pytest.mark.parametrize('raw', [
    '{"schema":"x","schema":"y","requests":[]}',
    '{"schema":"orqevia.agent-tool-requests.v1","requests":NaN}',
    envelope(read_step(actor='a29')), envelope(read_step(parameters={'agent': 'a29'})),
    envelope(read_step(), read_step()), envelope(*[read_step(id=f's{i}') for i in range(5)]),
    envelope(read_step(parameters={'value': [[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]})),
    envelope(read_step(kind=['service'])),
    'x' * 65537,
])
def test_model_identity_extra_duplicate_nonfinite_and_bounds_rejected_before_effect(rig, raw):
    _, _, completed, _, build = rig
    job = completed(raw)
    calls = []
    bridge = build(service=lambda *a, **k: calls.append(1))
    with pytest.raises((ValueError, PermissionError)):
        bridge.register(job['id'], Scope('Check', services=('private.task.metadata.read',)))
    assert not calls


def test_scope_cannot_grant_management_secrets_or_unregistered_delegation(rig):
    _, _, completed, _, build = rig
    job = completed(envelope(read_step()))
    for scope in (Scope('Change infrastructure', services=('infrastructure.apply',)),
        Scope('Secrets', services=('secrets.request',)),
        Scope('Cross-domain delegate', delegation_targets=('a19',))):
        with pytest.raises(PermissionError):
            build().register(job['id'], scope)


def test_existing_broker_denies_local_only_public_egress_and_retains_failure(rig):
    queue, ledger, completed, _, build = rig
    job = completed(envelope(read_step(service='internet.public.read',
        parameters={'url': 'https://example.com'})))
    bridge = build()
    bridge.register(job['id'], Scope('Public read', services=('internet.public.read',)))
    result = bridge.execute(job['id'])
    assert result['steps'][0]['state'] == 'FAILED'
    assert result['steps'][0]['receipt']['error_type'] == 'PermissionError'
    before = ledger.path.read_bytes()
    assert bridge.execute(job['id']) == result
    assert before == ledger.path.read_bytes()


def test_actual_workspace_write_readback_and_cross_actor_denial(rig, tmp_path):
    _, _, completed, _, build = rig
    from app.collective_api import execute_workspace
    from app.collective_workspace import CollectiveWorkspace
    store = CollectiveWorkspace(tmp_path / 'workspace.db')
    def workspace(body, **kwargs):
        return execute_workspace(body, store=store, **kwargs)
    job = completed(envelope({'id': 'note', 'kind': 'workspace', 'operation': 'sketch.write',
        'parameters': {'owner': 'a01', 'entry': 'findings', 'note': {'summary': 'Task data'}, 'checkpoint': True}},
        {'id': 'cross', 'kind': 'workspace', 'operation': 'sketch.read',
        'parameters': {'owner': 'a02', 'entry': 'findings'}}))
    bridge = build(workspace=workspace)
    bridge.register(job['id'], Scope('Keep task findings', workspace_operations=('sketch.write', 'sketch.read')))
    result = bridge.execute(job['id'])
    assert store.read_sketch('a01', owner='a01', entry='findings')['checkpoint'] == 1
    assert {s['step_id']: s['state'] for s in result['steps']} == {'cross': 'FAILED', 'note': 'SUCCEEDED'}


def test_delegation_actual_queue_result_and_feedback_binding(rig):
    queue, _, completed, finish, build = rig
    job = completed(envelope({'id': 'analysis', 'kind': 'delegate', 'target': 'a02',
                            'objective': 'Develop a feasible plan'}))
    bridge = build()
    bridge.register(job['id'], Scope('Plan an approved objective', delegation_targets=('a02',)))
    result = bridge.execute(job['id'])
    child_id = result['steps'][0]['receipt']['result']['child_job_id']
    child = queue.get(child_id)
    assert child['agent'] == 'a02' and child['allow_cloud'] == 0 and child['max_cost_usd'] == 0
    assert child['max_retries'] == 0 and child['data_classification'] == 'LOCAL_ONLY'
    assert bridge.execute(job['id']) == result
    assert len(queue.list()) == 2
    with pytest.raises(BridgeConflict):
        bridge.feedback(job['id'])
    finish(child_id, 'Actual synthetic child result')
    observed = bridge.observe(job['id'])
    assert observed['steps'][0]['receipt']['result']['child_evidence']['output_sha256'] == digest('Actual synthetic child result')
    feedback = bridge.feedback(job['id'])
    feed_step = next(s for s in feedback['steps'] if s['step_id'] == '_feedback')
    feedback_job = queue.get(feed_step['receipt']['result']['child_job_id'])
    assert 'Actual synthetic child result' in feedback_job['prompt']
    assert feed_step['receipt']['result']['feedback_input_sha256'] == digest(feedback_job['prompt'])
    finish(feedback_job['id'], 'Actual synthetic synthesis')
    observed = build().observe(job['id'])
    feed_step = next(s for s in observed['steps'] if s['step_id'] == '_feedback')
    assert feed_step['receipt']['result']['model_response_recorded'] is True
    assert feed_step['receipt']['result']['model_consumption_established'] is False
    assert feed_step['receipt']['result']['output'] == 'Actual synthetic synthesis'
    assert not observed['full_role_acceptance_awarded']
    bridge.feedback(job['id'])
    assert len(queue.list()) == 3


def test_child_prompt_or_egress_tamper_stops_observation(rig):
    queue, _, completed, _, build = rig
    job = completed(envelope({'id': 'plan', 'kind': 'delegate', 'target': 'a02', 'objective': 'Plan'}))
    bridge = build()
    bridge.register(job['id'], Scope('Objective', delegation_targets=('a02',)))
    result = bridge.execute(job['id'])
    child_id = result['steps'][0]['receipt']['result']['child_job_id']
    with queue.connect() as db:
        db.execute('UPDATE compute_jobs SET allow_cloud=1 WHERE id=?', (child_id,))
    with pytest.raises(BridgeConflict):
        bridge.observe(job['id'])


def test_failed_child_retained_feedback_does_not_claim_success(rig):
    queue, _, completed, finish, build = rig
    job = completed(envelope({'id': 'plan', 'kind': 'delegate', 'target': 'a02', 'objective': 'Plan'}))
    bridge = build()
    bridge.register(job['id'], Scope('Objective', delegation_targets=('a02',)))
    result = bridge.execute(job['id'])
    child_id = result['steps'][0]['receipt']['result']['child_job_id']
    finish(child_id, '', error='Original execution failure')
    result = bridge.observe(job['id'])
    step = result['steps'][0]
    assert step['state'] == 'FAILED' and step['receipt']['result']['execution_completed'] is False
    assert step['receipt']['result']['child_evidence']['error'] == 'Original execution failure'
    assert len(queue.list()) == 2


def test_crash_and_overlapping_runner_never_reexecute_reserved_effect(rig):
    _, _, completed, _, build = rig
    job = completed(envelope(read_step()))
    started, release = threading.Event(), threading.Event()
    calls = []
    def service(*a, **k):
        calls.append(1)
        started.set()
        release.wait(5)
        return {'actual': 'fixture result'}
    bridge = build(service=service)
    bridge.register(job['id'], Scope('Read', services=('private.task.metadata.read',)))
    errors = []
    def run():
        try:
            bridge.execute(job['id'])
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert started.wait(2)
        with pytest.raises(BridgeConflict):
            build(service=service).execute(job['id'])
    finally:
        release.set()
        worker.join(5)
    assert not errors and calls == [1]
    # Independently retained crash reservation must also stop after restart.
    with bridge.connect() as db:
        db.execute('UPDATE bridge_steps SET state=?,receipt_json=NULL WHERE job_id=?', ('IN_PROGRESS', job['id']))
    with pytest.raises(BridgeConflict):
        build(service=service).execute(job['id'])
    assert calls == [1]


def test_owner_stop_preserved_across_restart_and_cancels_known_pending_child(rig):
    queue, _, completed, _, build = rig
    job = completed(envelope({'id': 'plan', 'kind': 'delegate', 'target': 'a02', 'objective': 'Plan'}))
    bridge = build()
    bridge.register(job['id'], Scope('Objective', delegation_targets=('a02',)))
    result = bridge.execute(job['id'])
    child_id = result['steps'][0]['receipt']['result']['child_job_id']
    assert bridge.stop(job['id'])['state'] == 'STOPPED'
    assert queue.get(child_id)['status'] == 'cancelled'
    with pytest.raises(BridgeConflict):
        build().execute(job['id'])
    with pytest.raises(BridgeConflict):
        build().feedback(job['id'])


def test_stop_during_pending_enqueue_audit_cancels_provisional_child(rig, monkeypatch):
    queue, ledger, completed, _, build = rig
    job = completed(envelope({'id': 'plan', 'kind': 'delegate', 'target': 'a02', 'objective': 'Plan'}))
    bridge = build()
    bridge.register(job['id'], Scope('Objective', delegation_targets=('a02',)))
    audit_pending, release = threading.Event(), threading.Event()
    flush = ledger.flush
    def delayed_flush(*a, **kw):
        result = flush(*a, **kw)
        audit_pending.set()
        release.wait(5)
        return result
    monkeypatch.setattr(ledger, 'flush', delayed_flush)
    errors = []
    def run():
        try:
            bridge.execute(job['id'])
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert audit_pending.wait(2)
        interim = build().status(job['id'])
        assert interim['steps'][0]['state'] == 'IN_PROGRESS'
        child_id = interim['steps'][0]['receipt']['result']['child_job_id']
        assert build().stop(job['id'])['state'] == 'STOPPED'
        assert queue.get(child_id)['status'] == 'cancelled'
    finally:
        release.set()
        worker.join(5)
    assert not errors and build().status(job['id'])['state'] == 'STOPPED'


def test_full_64kb_public_receipts_retained_with_bounded_labelled_model_projection(rig):
    queue, _, completed, _, build = rig
    from app.capability_broker import execute_request
    # Control bytes are valid UTF8 and also exercise worst-case JSON escaping.
    raw = b'\x00' * 65536
    data = {'source_sha256': digest(raw.decode()), 'content': raw.decode(),
            'content_base64': base64.b64encode(raw).decode(), 'bytes': len(raw), 'status': 200}
    def service(body, **kwargs):
        return execute_request(body, reader=lambda url: data, **kwargs)
    job = completed(envelope(*[read_step(id=f'source{i}', service='internet.public.read',
        parameters={'url': 'https://example.com'}) for i in range(4)]), classification='CLOUD_PERMITTED')
    bridge = build(service=service)
    bridge.register(job['id'], Scope('Read public source', services=('internet.public.read',)))
    result = bridge.execute(job['id'])
    assert all(step['state'] == 'SUCCEEDED' for step in result['steps'])
    retained = bridge.receipt(job['id'], 'source0')
    assert retained['receipt']['result']['result']['content_base64'] == data['content_base64']
    feedback = bridge.feedback(job['id'])
    step = next(s for s in feedback['steps'] if s['step_id'] == '_feedback')
    child = queue.get(step['receipt']['result']['child_job_id'])
    assert len(child['prompt'].encode()) <= 65536
    assert 'PARTIAL_RECEIPT_EXCERPT; FULL_ORIGINAL_RETAINED_AT_REFERENCE' in child['prompt']
    assert retained['sha256'] in child['prompt']


def test_feedback_preflight_failure_does_not_reserve_never_submitted_step(rig, monkeypatch):
    _, _, completed, _, build = rig
    from app import agent_tool_bridge as module
    job = completed(envelope(read_step()))
    bridge = build(service=lambda *a, **k: {'result': 'x' * 2000})
    bridge.register(job['id'], Scope('Read', services=('private.task.metadata.read',)))
    bridge.execute(job['id'])
    monkeypatch.setattr(module, 'MAX_BYTES', 1000)
    with pytest.raises(ValueError):
        bridge.feedback(job['id'])
    assert '_feedback' not in {s['step_id'] for s in bridge.status(job['id'])['steps']}


@pytest.mark.parametrize('limit', [None, True, 0, 5])
def test_workspace_list_effect_requires_explicit_bounded_limit(rig, limit):
    _, _, completed, _, build = rig
    parameters = {'board': 'EVIDENCE'}
    if limit is not None:
        parameters['limit'] = limit
    job = completed(envelope({'id': 'list', 'kind': 'workspace', 'operation': 'board.read', 'parameters': parameters}))
    with pytest.raises(ValueError):
        build().register(job['id'], Scope('Read', workspace_operations=('board.read',)))


def test_router_owner_auth_and_forbidden_actor_model_inputs(rig, monkeypatch):
    _, _, completed, _, build = rig
    from app import agent_tool_bridge_api as api
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'fixture-owner-only')
    monkeypatch.setattr(api, 'bridge', build)
    app = FastAPI()
    app.include_router(api.router)
    job = completed(envelope(read_step()))
    body = {'job_id': job['id'], 'objective': 'Read this task', 'services': ['private.task.metadata.read']}
    with TestClient(app) as client:
        assert client.post('/api/agent-tool-bridge/sessions', json=body).status_code == 401
        assert client.post('/api/agent-tool-bridge/sessions', json=body,
                           headers={'Authorization': 'Bearer fixture-member'}).status_code == 401
        headers = {'Authorization': 'Bearer fixture-owner-only'}
        assert client.post('/api/agent-tool-bridge/sessions', json={**body, 'actor': 'a29'}, headers=headers).status_code == 422
        assert client.post('/api/agent-tool-bridge/sessions', json={**body, 'model': 'caller-local-bypass'}, headers=headers).status_code == 422
        assert client.post('/api/agent-tool-bridge/sessions', json=body, headers=headers).status_code == 200
        response = client.post(f'/api/agent-tool-bridge/sessions/{job["id"]}/execute', json={}, headers=headers)
        assert response.status_code == 200 and not response.json()['full_role_acceptance_awarded']
