"""Actual temporary owning domains, never live authority/certification evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid

import pytest

from app import agent_cert_authority_events as events
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span

SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
RUNTIME = {'host_id': 'authority-test-domain', 'version': 'test-only-v1',
    'source_revision': SOURCE, 'image_digest': IMAGE}


@pytest.fixture
def domain(tmp_path, monkeypatch):
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', str(tmp_path / 'compute-queue.db'))
    monkeypatch.setenv('ORQEVIA_RUNTIME_REVISION', SOURCE)
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST', IMAGE)
    monkeypatch.setenv('ORQEVIA_INTERFACE_HOST_ID', RUNTIME['host_id'])
    monkeypatch.setenv('ORQEVIA_INTERFACE_RUNTIME_VERSION', RUNTIME['version'])
    monkeypatch.setenv('ORQEVIA_REGISTRY_V1_ENABLED', '1')
    from app import agent_registry, objective_api, agent_dispatch_api
    # Authentication integration is separately tested below; no real credential.
    monkeypatch.setattr(objective_api, 'authenticate_owner', lambda _: None)
    monkeypatch.setattr(agent_dispatch_api, 'authenticate_owner', lambda _: None)
    ledger = ActionLedger(tmp_path / 'action-records.jsonl')
    monkeypatch.setattr(agent_dispatch_api, 'action_ledger', lambda: ledger)
    registry_pin = events.sha(agent_registry.REGISTRY_PATH.read_bytes())
    # Existing owning stores are retained as bytes; producer must never decode them.
    for name in ('interface.db', 'pwa-sessions.db'):
        (tmp_path / name).write_bytes(b'PRIVATE_TEST_OWNER_STORE_NOT_A_PUBLIC_OBSERVATION')
    def prepare(case_id):
        spec = events.canonical_authority_case(case_id)
        task = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()
        db = objective_api.connect()
        try:
            db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
                (task, events.sha(spec['request']['objective'].encode()), 'dispatching', json.dumps([events.CAPABILITY_ID])))
            db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)', (task, 0, created, created))
            objective_api.store_runtime(db, task, 0)
            db.commit()
        finally:
            db.close()
        args = dict(submitted_request=deepcopy(spec['request']), data_root=tmp_path, ledger=ledger,
            runtime=deepcopy(RUNTIME), read_runtime=objective_api.runtime_snapshot,
            source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=registry_pin)
        return spec, task, args, created
    yield tmp_path, ledger, prepare, objective_api, agent_dispatch_api
    assert ledger.close()


def execute_and_collect(domain, case_id, *, through_dispatch=False):
    root, ledger, prepare, objective_api, dispatcher = domain
    spec, task, args, created = prepare(case_id)
    before = objective_api.runtime_snapshot()
    if through_dispatch:
        dispatch = dispatcher.dispatch_request(dispatcher.AgentRequest(**spec['request']), None, parent_task_id=task)
    else:
        dispatch = events.execute_authority_case(spec, task, **args)
    after = objective_api.runtime_snapshot()
    steps = [{'capability': events.CAPABILITY_ID, 'dispatch': dispatch}]
    db = objective_api.connect()
    try:
        db.execute('UPDATE objectives SET state=?,steps_json=? WHERE id=?', ('submitted', json.dumps(steps), task))
        db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=0',
            (datetime.now(timezone.utc).isoformat(), task))
        db.commit()
    finally:
        db.close()
    read = objective_api._get(task, None, read_only=True)
    metadata, raw = ArtifactFactory(root / 'artifacts').retrieve(dispatch['artifact']['artifact_id'])
    receipt = dispatch['authority_event']
    lines = events.read_authority_action_span(root, task, case_id)
    chain = action_span(lines, task_id=task, agent_id=events.AGENT_ID,
        action_type=events.authority_action_type(case_id), schema=events.RESULT_SCHEMA, metadata=metadata,
        began=events._utc(receipt['started_at']), ended=events._utc(receipt['completed_at']),
        action_id=receipt['subject_action_id'])
    now = datetime.now(timezone.utc)
    execution = {'case_spec': spec, 'runtime': before, 'runtime_after': after,
        'runtime_current': objective_api.runtime_snapshot(), 'submission': [202, {'id': task, 'steps': steps}],
        'dispatch': dispatch, 'artifact_metadata': metadata, 'artifact_content_utf8': raw.decode(),
        'objective_read': [200, read], 'action_records': lines, 'action_chain_join': chain,
        'observation': {'started_at': created, 'completed_at': now.isoformat()}}
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=args['registry_sha256'], now=now)
    return execution, pins


def test_import_is_io_free(monkeypatch):
    code = compile(Path(events.__file__).read_text(encoding='utf-8'), '<source-only>', 'exec')
    def forbidden(*a, **k):
        pytest.fail('import performed file I/O')
    monkeypatch.setattr('builtins.open', forbidden)
    for name in ('open', 'read_bytes', 'read_text', 'mkdir'):
        monkeypatch.setattr(Path, name, forbidden)
    namespace = {'__name__': 'authority_source_only', '__package__': 'app'}
    exec(code, namespace)
    assert namespace['UNREADY_CASES'] == events.UNREADY_CASES


def test_two_distinct_fixed_inputs_and_two_consequential_cases_remain_unready():
    specs = [events.canonical_authority_case(case_id) for case_id in events.SUPPORTED_CASES]
    assert len({spec['case_input_sha256'] for spec in specs}) == 2
    assert len({events.authority_action_type(spec['case']) for spec in specs}) == 2
    assert all(spec['consequential_guard_denial_proven'] is False for spec in specs)
    for case_id in events.UNREADY_CASES:
        with pytest.raises(events.AuthorityEventError, match='AUTHORITY_OWNING_CASE_REQUIRED'):
            events.canonical_authority_case(case_id)


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
@pytest.mark.parametrize('through_dispatch', (False, True))
def test_original_owning_policy_artifact_action_and_objective_join(domain, case_id, through_dispatch):
    root, ledger, _, _, _ = domain
    owner_before = {name: (root / name).read_bytes() for name in ('interface.db', 'pwa-sessions.db')}
    execution, pins = execute_and_collect(domain, case_id, through_dispatch=through_dispatch)
    result = events.validate_authority_execution(execution, **pins)
    report = json.loads(execution['artifact_content_utf8'])
    assert result['certification'] == 'UNVERIFIED'
    assert result['consequential_guard_denial_proven'] is False
    assert report['registered_authority']['execution_authority'] == 'none inherited from Registry'
    assert report['registered_authority']['consequential_requires_owner_approval'] is True
    assert report['registered_authority']['provided_context_read_eligible'] is True
    assert all((root / name).read_bytes() == raw for name, raw in owner_before.items())
    assert execution['dispatch']['authority_event']['read_domains_before'] == execution['dispatch']['authority_event']['read_domains_after']
    assert 'PRIVATE_TEST_OWNER_STORE' not in execution['artifact_content_utf8']
    assert ledger.status()['persisted'] == 2
    assert not (root / 'compute-ledger.db').exists()
    # First owning Objective API import may initialize its existing temporary
    # queue schema. Empty store is not an enqueue or an inference execution.
    queue_path = root / 'compute-queue.db'
    if queue_path.exists():
        with sqlite3.connect(queue_path.as_uri() + '?mode=ro', uri=True) as db:
            assert db.execute('SELECT COUNT(*) FROM compute_jobs').fetchone()[0] == 0
    assert all('inference.' not in line for line in execution['action_records'])
    if case_id == events.SUPPORTED_CASES[0]:
        assert report['assessment']['actual_consequential_guard_denial'] == 'NOT_PROVEN'
    else:
        assert report['assessment']['failure_basis_points'] == 500


@pytest.mark.parametrize('defect', ('actor', 'capability', 'objective', 'context', 'classification',
    'extra_request', 'spec', 'runtime', 'current_runtime', 'registry_pin', 'task_owner', 'task_hash', 'task_state'))
def test_invalid_owning_identity_request_or_objective_has_no_action_or_artifact_effect(domain, defect):
    root, ledger, prepare, objective_api, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[0])
    before = events.read_domain_snapshot(root)
    if defect == 'actor':
        spec['agent_id'] = 'a26'
    elif defect in {'capability', 'objective', 'context', 'classification'}:
        args['submitted_request'][defect] = 'unowned drift'
    elif defect == 'extra_request':
        args['submitted_request']['owner_approval_id'] = 'not-a-grant'
    elif defect == 'spec':
        spec['oracle_id'] = 'caller-oracle'
    elif defect == 'runtime':
        args['runtime']['host_id'] = 'other-host'
    elif defect == 'current_runtime':
        args['read_runtime'] = lambda: {**RUNTIME, 'source_revision': 'c' * 40}
    elif defect == 'registry_pin':
        args['registry_sha256'] = 'c' * 64
    else:
        db = objective_api.connect()
        try:
            column, value = {'task_owner': ('steps_json', json.dumps(['responsibility.a26'])),
                'task_hash': ('objective_hash', '0' * 64), 'task_state': ('state', 'submitted')}[defect]
            db.execute(f'UPDATE objectives SET {column}=? WHERE id=?', (value, task))
            db.commit()
        finally:
            db.close()
        before = events.read_domain_snapshot(root)
    with pytest.raises(events.AuthorityEventError):
        events.execute_authority_case(spec, task, **args)
    assert events.read_domain_snapshot(root) == before
    assert ledger.status()['persisted'] == 0 and ledger.pending.unfinished_tasks == 0
    assert not (root / 'artifacts').exists()


@pytest.mark.parametrize('defect', ('policy', 'result', 'runtime_after', 'runtime_current', 'subject_action',
    'action_lines', 'action_join', 'objective_owner', 'objective_runtime', 'objective_agent_work',
    'submission', 'scope', 'read_domain_change', 'read_domain_bool_laundering', 'stale', 'claimed_denial'))
def test_join_rejects_tampering_without_rewriting_original_records(domain, defect):
    execution, pins = execute_and_collect(domain, events.SUPPORTED_CASES[0])
    if defect in {'policy', 'result'}:
        report = json.loads(execution['artifact_content_utf8'])
        if defect == 'policy':
            report['registered_authority']['execution_authority'] = 'caller-granted'
        else:
            report['assessment']['execution_permission'] = 'OWNER'
        execution['artifact_content_utf8'] = events.canonical(report).decode()
    elif defect in {'runtime_after', 'runtime_current'}:
        execution[defect]['host_id'] = 'other-host'
    elif defect == 'subject_action':
        execution['dispatch']['authority_event']['subject_action_id'] = str(uuid.uuid4())
    elif defect == 'action_lines':
        execution['action_records'][0] = execution['action_records'][0].rstrip('\n')
    elif defect == 'action_join':
        execution['action_chain_join']['last_sha256'] = '0' * 64
    elif defect == 'objective_owner':
        execution['objective_read'][1]['steps'][0]['capability'] = 'responsibility.a26'
    elif defect == 'objective_runtime':
        execution['objective_read'][1]['execution_metadata']['runtime']['source_revision'] = 'c' * 40
    elif defect == 'objective_agent_work':
        execution['objective_read'][1]['execution_metadata']['agent_execution'] = [{'agent_id': 'a19'}]
    elif defect == 'submission':
        execution['submission'][0] = True
    elif defect == 'scope':
        execution['dispatch']['authority_event']['fixed_store_no_change_scope'] = 'GLOBAL_NO_EFFECTS'
    elif defect == 'read_domain_change':
        execution['dispatch']['authority_event']['read_domains_after']['interface.db']['sha256'] = '0' * 64
    elif defect == 'read_domain_bool_laundering':
        execution['dispatch']['authority_event']['read_domains_before']['interface.db']['bytes'] = True
    elif defect == 'stale':
        pins['now'] += timedelta(seconds=301)
    else:
        execution['dispatch']['authority_event']['consequential_guard_denial_proven'] = True
    with pytest.raises(events.AuthorityEventError):
        events.validate_authority_execution(execution, **pins)


def test_read_domain_drift_after_actual_operation_fails_closed_and_cannot_replay(domain, monkeypatch):
    root, ledger, prepare, _, _ = domain
    spec, task, args, _ = prepare(events.SUPPORTED_CASES[0])
    original = ArtifactFactory.retrieve
    def drift(factory, artifact_id):
        value = original(factory, artifact_id)
        (root / 'interface.db').write_bytes(b'changed independent test store')
        return value
    monkeypatch.setattr(ArtifactFactory, 'retrieve', drift)
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_OWNING_READ_DOMAINS_CHANGED'):
        events.execute_authority_case(spec, task, **args)
    assert ledger.status()['persisted'] == 2
    assert len(list((root / 'artifacts').iterdir())) == 1
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_TASK_ALREADY_ATTEMPTED'):
        events.execute_authority_case(spec, task, **args)
    assert len(list((root / 'artifacts').iterdir())) == 1


def test_dispatch_authentication_precedes_authority_producer(domain, monkeypatch):
    root, ledger, _, _, dispatcher = domain
    from fastapi import HTTPException
    def denied(_):
        raise HTTPException(401, 'test client denied')
    monkeypatch.setattr(dispatcher, 'authenticate_owner', denied)
    monkeypatch.setattr(events, 'execute_authority_case', lambda *a, **k: pytest.fail('producer ran before auth'))
    body = dispatcher.AgentRequest(**events.canonical_authority_case(events.SUPPORTED_CASES[0])['request'])
    with pytest.raises(HTTPException) as exc:
        dispatcher.dispatch_request(body, None)
    assert exc.value.status_code == 401
    assert ledger.status()['persisted'] == 0 and not (root / 'artifacts').exists()


@pytest.mark.parametrize('case_id', events.UNREADY_CASES)
def test_dispatch_does_not_turn_missing_consequential_seam_into_denial_evidence(domain, case_id):
    root, ledger, _, _, dispatcher = domain
    from fastapi import HTTPException
    request = events.canonical_authority_case(events.SUPPORTED_CASES[0])['request']
    request['context'] = events.canonical({'case': case_id}).decode()
    with pytest.raises(HTTPException) as exc:
        dispatcher.dispatch_request(dispatcher.AgentRequest(**request), None)
    assert exc.value.status_code == 422
    assert ledger.status()['persisted'] == 0 and not (root / 'artifacts').exists()


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_existing_objective_submit_dispatch_and_read_create_the_original_join(domain, case_id):
    root, ledger, _, objective_api, _ = domain
    from app import agent_registry
    spec = events.canonical_authority_case(case_id)
    began = datetime.now(timezone.utc)
    runtime = objective_api.runtime_snapshot()
    submitted = objective_api.submit(objective_api.ObjectiveRequest(**spec['request']), None)
    task = submitted['id']
    dispatch = submitted['steps'][0]['dispatch']
    runtime_after = objective_api.runtime_snapshot()
    read = objective_api.get_read_only(task, None)
    metadata, raw = ArtifactFactory(root / 'artifacts').retrieve(dispatch['artifact']['artifact_id'])
    receipt = dispatch['authority_event']
    lines = events.read_authority_action_span(root, task, case_id)
    chain = action_span(lines, task_id=task, agent_id=events.AGENT_ID,
        action_type=events.authority_action_type(case_id), schema=events.RESULT_SCHEMA, metadata=metadata,
        began=events._utc(receipt['started_at']), ended=events._utc(receipt['completed_at']),
        action_id=receipt['subject_action_id'])
    ended = datetime.now(timezone.utc)
    execution = {'case_spec': spec, 'runtime': runtime, 'runtime_after': runtime_after,
        'runtime_current': objective_api.runtime_snapshot(), 'submission': [202, submitted], 'dispatch': dispatch,
        'artifact_metadata': metadata, 'artifact_content_utf8': raw.decode(), 'objective_read': [200, read],
        'action_records': lines, 'action_chain_join': chain,
        'observation': {'started_at': began.isoformat(), 'completed_at': ended.isoformat()}}
    result = events.validate_authority_execution(execution, source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=events.sha(agent_registry.REGISTRY_PATH.read_bytes()), now=ended)
    assert result['case'] == case_id and result['task_id'] == submitted['id']
    assert result['certification'] == 'UNVERIFIED' and result['consequential_guard_denial_proven'] is False
    assert ledger.status()['persisted'] == 2
