"""Disposable actual admission/review domains, never live or signed evidence."""
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3

import pytest
from app import agent_cert_authority_events as events
from app.spine import SpineStore
from tests.test_agent_cert_authority_events import domain, execute_and_collect
from tests.test_agent_cert_authority_chain import runtime, collect, TOKEN
from tests.test_agent_cert_review_dispatch import configured


def test_existing_store_open_is_read_only_and_never_initializes(tmp_path, monkeypatch):
    path = tmp_path / 'prime-spine.db'
    with pytest.raises(sqlite3.OperationalError):
        SpineStore(str(path), initialize=False)
    assert not path.exists()
    SpineStore(str(path))
    original = path.read_bytes()
    monkeypatch.setattr(SpineStore, '_init', lambda *_: pytest.fail('Schema initialized'))
    store = SpineStore(str(path), initialize=False)
    assert store.path == str(path) and path.read_bytes() == original


@pytest.mark.parametrize('defect', ['missing','wrong_store','wrong_schema','unset'])
def test_denial_missing_or_wrong_owning_store_fails_before_any_write(domain, monkeypatch, defect):
    root, ledger, prepare, _, _ = domain
    spec, task, args, _ = prepare(events.DENIAL_CASE)
    path = root / 'prime-spine.db'
    if defect == 'missing': path.unlink()
    elif defect == 'wrong_store': monkeypatch.setenv('PRIME_SPINE_DB', str(root / 'other.db'))
    elif defect == 'unset': monkeypatch.delenv('PRIME_SPINE_DB')
    else:
        path.unlink()
        with sqlite3.connect(path) as db: db.execute('CREATE TABLE unrelated(value)')
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(events.AuthorityEventError):
        events.execute_authority_case(spec, task, **args)
    assert ledger.status()['persisted'] == 0 and not (root / 'artifacts').exists()
    assert (path.read_bytes() if path.exists() else None) == before
    assert not (root / 'other.db').exists()


def test_actual_blocked_admission_preserves_existing_policy_and_adds_only_original_rows(domain, monkeypatch):
    root, *_ = domain
    store = events._owning_spine(root)
    with store.connect() as db:
        db.execute("INSERT INTO trust_registry(action_type,policy_state,updated_at) VALUES('trust.change','AUTO','test')")
        db.execute("INSERT INTO trust_registry(action_type,policy_state,updated_at) VALUES('calendar.create','GATED','test')")
    monkeypatch.setattr(SpineStore, '_init', lambda *_: pytest.fail('No admission schema initialization'))
    before = events._spine_snapshot(store)
    execution, pins = execute_and_collect(domain, events.DENIAL_CASE, through_dispatch=True)
    event = execution['dispatch']['authority_event']
    joined = events.validate_authority_execution(execution, **pins)
    assert joined['consequential_guard_denial_proven'] is True
    events.read_original_denial(root, event['task_id'], event['admission'])
    after = events._spine_snapshot(store)
    assert all(before[key] == after[key] for key in ('trust_registry','trust_evidence','approvals'))
    assert after['audit_trail']['rows'] == before['audit_trail']['rows'] + 1
    assert after['event_bus']['rows'] == before['event_bus']['rows'] + 1
    assert json.loads(event['admission']['audit_row']['envelope_json'])['actor_id'] == 'a19'
    assert json.loads(event['admission']['audit_row']['decision_record_json'])['case_spec_sha256'] == events.sha(events.canonical(execution['case_spec']))
    with pytest.raises(events.AuthorityEventError):
        _, _, prepare, *_ = domain
        # Reusing the same original Objective must never write a second denial.
        spec = execution['case_spec']
        events.execute_authority_case(spec, event['task_id'], submitted_request=spec['request'],
            data_root=root, ledger=domain[1], runtime=execution['runtime'], read_runtime=lambda: execution['runtime'],
            source_revision=pins['source_revision'], runtime_image_id=pins['runtime_image_id'], registry_sha256=pins['registry_sha256'])
    assert events._spine_snapshot(store) == after


@pytest.mark.parametrize('defect', ['missing_audit','missing_event','foreign_actor','foreign_task','unknown_action',
    'gated','authorized','owner_claim','proposal_target','source_context','proposal_hash','verified','duplicate_field','event_type','event_decision',
    'future_audit','stale','policy_changed','prior_changed','missing_admission'])
def test_original_denial_validator_rejects_auth_join_policy_and_time_tamper(domain, defect):
    execution, pins = execute_and_collect(domain, events.DENIAL_CASE)
    changed = deepcopy(execution)
    event = changed['dispatch']['authority_event']
    admission = event['admission']
    audit, emitted = admission['audit_row'], admission['event_row']
    envelope = json.loads(audit['envelope_json'])
    if defect == 'missing_audit': admission['audit_row'] = {}
    elif defect == 'missing_event': admission['event_row'] = {}
    elif defect == 'foreign_actor': envelope['actor_id'] = 'a26'
    elif defect == 'foreign_task': audit['correlation_id'] = 'foreign'
    elif defect == 'unknown_action': envelope['action'] = 'production.restart'
    elif defect == 'gated': audit['policy_state'] = 'GATED'
    elif defect == 'authorized': audit['execution_status'] = 'AUTHORIZED'
    elif defect == 'owner_claim': envelope['context']['owner_approval'] = True
    elif defect == 'proposal_target': envelope['parameters']['target_action_type'] = 'email.send'
    elif defect == 'source_context': envelope['context']['source_revision'] = 'c'*40
    elif defect == 'proposal_hash': envelope['context']['proposal_sha256'] = 'c'*64
    elif defect == 'verified': audit['verification_json'] = '{"command":"VERIFIED","execution":"VERIFIED","outcome":"VERIFIED"}'
    elif defect == 'duplicate_field': audit['envelope_json'] = '{"action":"trust.change","action":"trust.change"}'
    elif defect == 'event_type': emitted['event_type'] = 'approval.required'
    elif defect == 'event_decision': emitted['payload_json'] = '{"decision":{"state":"PROHIBITED","reason":"fake","action":"trust.change"}}'
    elif defect == 'future_audit': audit['created_at'] = (pins['now'] + timedelta(seconds=1)).isoformat()
    elif defect == 'stale': pins['now'] += timedelta(seconds=301)
    elif defect == 'policy_changed': admission['protected_after']['trust_registry']['sha256'] = 'c'*64
    elif defect == 'prior_changed': admission['prior_rows_after']['audit_trail']['sha256'] = 'c'*64
    elif defect == 'missing_admission': event.pop('admission')
    if defect in {'foreign_actor','unknown_action','owner_claim','proposal_target','source_context','proposal_hash'}:
        audit['envelope_json'] = events.canonical(envelope).decode()
    with pytest.raises(events.AuthorityEventError): events.validate_authority_execution(changed, **pins)


@pytest.mark.parametrize('defect', ['audit_deleted','event_deleted','audit_modified','duplicate_event','foreign_event','foreign_audit','aggregate_collision','policy_modified'])
def test_fixed_a26_reviewer_rejects_changed_original_admission_before_review_write(runtime, defect):
    result = collect(runtime, events.DENIAL_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    with sqlite3.connect(runtime.root / 'prime-spine.db') as db:
        if defect == 'audit_deleted': db.execute('DELETE FROM audit_trail')
        elif defect == 'event_deleted': db.execute('DELETE FROM event_bus')
        elif defect == 'audit_modified': db.execute("UPDATE audit_trail SET execution_status='AUTHORIZED'")
        elif defect == 'duplicate_event':
            db.execute("INSERT INTO event_bus SELECT 'duplicate',correlation_id,event_type,aggregate_id,payload_json,created_at FROM event_bus")
        elif defect == 'foreign_event':
            db.execute("INSERT INTO event_bus SELECT 'foreign', 'foreign-task', event_type, 'foreign-key', payload_json,created_at FROM event_bus")
        elif defect == 'foreign_audit':
            db.execute("INSERT INTO audit_trail(correlation_id,idempotency_key,action_type,policy_state,execution_status,verification_json,envelope_json,decision_record_json,created_at) SELECT 'foreign-task','foreign-key',action_type,policy_state,execution_status,verification_json,envelope_json,decision_record_json,created_at FROM audit_trail")
        elif defect == 'aggregate_collision':
            db.execute("INSERT INTO event_bus SELECT 'foreign','foreign-task',event_type,aggregate_id,payload_json,created_at FROM event_bus")
        else: db.execute("INSERT INTO trust_registry(action_type,policy_state,updated_at) VALUES('calendar.create','AUTO','test')")
    before = runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 422
    assert (runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())) == before


def test_fixed_a26_final_original_reread_detects_mid_review_tamper(runtime, monkeypatch):
    result = collect(runtime, events.DENIAL_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    original = events.read_original_denial
    calls = []
    def changed(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            with sqlite3.connect(runtime.root / 'prime-spine.db') as db: db.execute('DELETE FROM event_bus')
        return original(*args, **kwargs)
    monkeypatch.setattr(events, 'read_original_denial', changed)
    before = runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 422 and len(calls) == 2
    assert (runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())) == before


def test_original_admission_preseed_prevents_replay_before_action_write(domain):
    from app.spine import StableSpine
    from datetime import datetime, timezone
    root, ledger, prepare, *_ = domain
    spec, task, args, _ = prepare(events.DENIAL_CASE)
    store = events._owning_spine(root)
    outcome = StableSpine(store).evaluate(events._denial_envelope(task, datetime.now(timezone.utc).isoformat(), binding={
        'source_revision': args['source_revision'], 'registry_sha256': args['registry_sha256'],
        'runtime_identity_sha256': events.sha(events.canonical(args['runtime']))}),
        events._denial_record(spec))
    assert outcome['idempotent_replay'] is False
    before = events._spine_snapshot(store)
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_ADMISSION_ALREADY_ATTEMPTED'):
        events.execute_authority_case(spec, task, **args)
    assert ledger.status()['persisted'] == 0 and not (root/'artifacts').exists()
    assert events._spine_snapshot(store) == before


def test_actual_policy_mutation_during_denial_fails_and_retains_original_failed_attempt(domain, monkeypatch):
    from app.spine import StableSpine
    root, ledger, prepare, *_ = domain
    spec, task, args, _ = prepare(events.DENIAL_CASE)
    original = StableSpine.evaluate
    def changed(self, *a, **k):
        result = original(self, *a, **k)
        with self.store.connect() as db:
            db.execute("INSERT INTO trust_registry(action_type,policy_state,updated_at) VALUES('calendar.create','AUTO','test')")
        return result
    monkeypatch.setattr(StableSpine, 'evaluate', changed)
    with pytest.raises(events.AuthorityEventError): events.execute_authority_case(spec, task, **args)
    assert ledger.flush(timeout=1)
    assert not list((root/'artifacts').glob('*/artifact.json'))
    store = events._owning_spine(root)
    audit, emitted = events._original_denial_rows(store, task)
    assert audit['execution_status'] == 'BLOCKED' and emitted['event_type'] == 'action.prohibited'
    # Original failure remains; certification code does not roll back/rewrite it.
    assert ledger.status()['persisted'] == 2


def test_existing_only_store_cannot_recreate_removed_domain(tmp_path):
    path = tmp_path/'prime-spine.db'
    SpineStore(str(path))
    store = SpineStore(str(path), initialize=False)
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        with store.connect(): pass
    assert not path.exists()


def test_independent_original_reader_rejects_consistently_forged_prior_digest(domain):
    root, *_ = domain
    execution, pins = execute_and_collect(domain, events.DENIAL_CASE)
    event = execution['dispatch']['authority_event']
    forged = deepcopy(event['admission'])
    forged['prior_rows_before']['audit_trail']['sha256'] = 'c'*64
    forged['prior_rows_after']['audit_trail']['sha256'] = 'c'*64
    # Equal submitted before/after claims alone are insufficient.
    events._validate_denial(forged, event['task_id'], execution['case_spec'],
        events._utc(event['started_at']), events._utc(event['completed_at']), binding={
            key: event[key] for key in ('source_revision','registry_sha256','runtime_identity_sha256')})
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_CURRENT_PRIOR_ROWS_CHANGED'):
        events.read_original_denial(root, event['task_id'], forged)


@pytest.mark.parametrize('table', ['approvals','trust_evidence'])
def test_related_prior_approval_or_trust_evidence_is_rejected_before_write(domain, table):
    root, ledger, prepare, *_ = domain
    spec, task, args, _ = prepare(events.DENIAL_CASE)
    store = events._owning_spine(root)
    with store.connect() as db:
        if table == 'approvals':
            db.execute("INSERT INTO approvals(idempotency_key,correlation_id,action_type,status,envelope_json,decision_json,created_at) VALUES(?,?,'trust.change','PENDING','{}','{}','test')", (task,task))
        else:
            db.execute("INSERT INTO trust_evidence(action_type,idempotency_key,execution_status,verification_json,evidence_json,created_at) VALUES('trust.change',?,'BLOCKED','{}','{}','test')", (task,))
    before = events._spine_snapshot(store)
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_ADMISSION_ALREADY_ATTEMPTED'):
        events.execute_authority_case(spec, task, **args)
    assert ledger.status()['persisted'] == 0 and not (root/'artifacts').exists()
    assert events._spine_snapshot(store) == before


@pytest.mark.parametrize('suffix', ['-wal','-journal'])
def test_large_sidecar_is_rejected_before_any_admission_write(domain, suffix):
    root, ledger, prepare, *_ = domain
    spec, task, args, _ = prepare(events.DENIAL_CASE)
    path = root/('prime-spine.db'+suffix)
    with path.open('wb') as stream: stream.truncate(events.MAX_DOMAIN_BYTES)
    before = (root/'prime-spine.db').read_bytes()
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_SPINE_BYTE_BOUND_EXCEEDED'):
        events.execute_authority_case(spec, task, **args)
    assert ledger.status()['persisted'] == 0 and not (root/'artifacts').exists()
    assert (root/'prime-spine.db').read_bytes() == before


def test_real_live_wal_rows_are_read_instead_of_ignored(domain):
    from contextlib import closing
    root, *_ = domain
    with closing(sqlite3.connect(root/'prime-spine.db')) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO trust_registry(action_type,policy_state,updated_at) VALUES('calendar.create','GATED','test')")
        writer.commit()
        assert (root/'prime-spine.db-wal').stat().st_size > 0
        store = events._owning_spine(root)
        assert events._spine_rows(store, 'trust_registry')['rows'] == 1


def test_sqlite_rejects_giant_value_before_materializing_snapshot(domain):
    root, *_ = domain
    with sqlite3.connect(root/'prime-spine.db') as db:
        db.execute("INSERT INTO trust_registry(action_type,policy_state,metadata_json,updated_at) VALUES('calendar.create','GATED',?,'test')", ('x'*(1024*1024+1),))
    store = events._owning_spine(root)
    with pytest.raises(sqlite3.DataError, match='too big'):
        events._spine_rows(store, 'trust_registry')


def test_incremental_snapshot_byte_cap_rejects_many_bounded_rows(domain):
    root, *_ = domain
    with sqlite3.connect(root/'prime-spine.db') as db:
        db.executemany("INSERT INTO trust_registry(action_type,policy_state,metadata_json,updated_at) VALUES(?,'GATED',?,'test')",
            [(str(i),'x'*100000) for i in range(11)])
    with pytest.raises(events.AuthorityEventError, match='AUTHORITY_SPINE_READ_BOUND_EXCEEDED'):
        events._spine_rows(events._owning_spine(root), 'trust_registry')


def test_expired_deadline_fails_before_schema_or_row_queries(domain):
    import time
    root, *_ = domain
    before = (root/'prime-spine.db').read_bytes()
    with pytest.raises(TimeoutError): events._owning_spine(root, deadline=time.monotonic()-1)
    assert (root/'prime-spine.db').read_bytes() == before


def test_sqlite_progress_handler_interrupts_actual_scan_at_shared_deadline(domain, monkeypatch):
    root, *_ = domain
    store = events._owning_spine(root)
    with store.connect() as db:
        db.executemany("INSERT INTO event_bus VALUES(?,?,'action.prohibited',?,'{}','test')",
            [(str(i),'other','other') for i in range(10000)])
    # A real SQLite table scan, with deadline expiring after the native query
    # starts; no sleeps, fake query results or disabled production limits.
    elapsed = {'value': 0.0}
    def clock():
        elapsed['value'] += 0.1
        return elapsed['value']
    monkeypatch.setattr('app.spine.time.monotonic', clock)
    store._deadline = 0.25
    with pytest.raises(sqlite3.OperationalError, match='interrupted'):
        with store.connect(read_only=True) as db:
            db.execute("SELECT 1 FROM event_bus WHERE correlation_id='absent' LIMIT 1").fetchone()
