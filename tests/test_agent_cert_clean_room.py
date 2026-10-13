"""Genuine temporary original input-only tasks; no live PRIME/model/signing."""
import json
from copy import deepcopy
import uuid
import pytest

from app import agent_cert_tool_events as events
from app import agent_cert_clean_room as audit
from tests.test_agent_cert_tool_events import collect,validate,no_external_operations
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_review_dispatch import SOURCE
from tests.test_agent_cert_operator_io import TOKEN


def original(runtime):
    result = collect(runtime,audit.CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE',json.dumps(result.summary)
    return json.loads(result.execution_bytes)


def test_final_oracle_never_borrows_either_producer(runtime,monkeypatch):
    execution = original(runtime)
    def forbidden(*args,**kwargs):pytest.fail('Borrowed producer computation')
    monkeypatch.setattr(events,'expected_artifact_bytes',forbidden)
    monkeypatch.setattr(audit,'reproduce_input',forbidden)
    validate(execution,runtime)


@pytest.mark.parametrize('defect',['ratio','health','recovery'])
def test_actual_wrong_producer_is_rejected_after_real_input_only_audit_and_by_final_peer(runtime,monkeypatch,defect):
    real = events.expected_artifact_bytes
    def faulty(case,**kwargs):
        raw = real(case,**kwargs)
        if case != audit.CASE:return raw
        answer = json.loads(raw)
        key,value = {'ratio':('api_failure_basis_points',0),'health':('current_health','HEALTHY'),
            'recovery':('recovery','PROVEN')}[defect]
        answer['assessment'][key] = value
        return events.canonical(answer)
    monkeypatch.setattr(events,'expected_artifact_bytes',faulty)
    result = collect(runtime,audit.CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(result.execution_bytes)
    blind = execution['blind_audit']
    assert json.loads(blind['artifact_content_utf8'])['conclusion']['api_failure_basis_points'] == 500
    assert len(execution['original_action_records']) == 6
    artifact = runtime.root/'artifacts'/execution['artifact_metadata']['artifact_id']/'artifact.json'
    assert artifact.read_bytes() == execution['artifact_content_utf8'].encode()
    before = set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']
    reply = runtime.client.post('/api/agents/objectives',json=events.cross_peer_request(execution,str(uuid.uuid4()),SOURCE),
        headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code == 202 and reply.json()['steps'][0]['state'] == 'blocked'
    assert (set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']) == before


@pytest.mark.parametrize('defect',['ratio','health','recovery'])
def test_actual_faulty_blind_auditor_artifact_is_rejected_independently(runtime,monkeypatch,defect):
    real = audit.reproduce_input
    def faulty(raw):
        answer = real(raw)
        key,value = {'ratio':('api_failure_basis_points',0),'health':('current_health','HEALTHY'),
            'recovery':('recovery','PROVEN')}[defect]
        answer[key] = value
        return answer
    monkeypatch.setattr(audit,'reproduce_input',faulty)
    result = collect(runtime,audit.CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert len([1 for method,path,body in runtime.transport.calls if method == 'POST' and path == '/api/agents/objectives']) == 2
    # The wrong answer was actually committed by the separate auditor, never accepted.
    originals = [json.loads((folder/'artifact.json').read_text()) for folder in (runtime.root/'artifacts').iterdir()]
    assert any(item.get('schema_version') == audit.SCHEMA for item in originals)


@pytest.mark.parametrize('extra',['execution','answer_artifact_id','prior_answer','expected_answer_sha256'])
def test_input_only_request_rejects_any_prior_answer_access(runtime,extra):
    execution = original(runtime);proof = execution['blind_audit'];body = deepcopy(proof['request'])
    context = json.loads(body['context']);context[extra] = 'forbidden';body['context'] = events.canonical(context).decode()
    with pytest.raises(ValueError):audit.admit_request(body,runtime=execution['runtime'],registry=runtime.registry_sha)


@pytest.mark.parametrize('defect',['actor','task','source','model','nonce','output','order'])
def test_original_blind_custody_tampering_is_rejected(runtime,defect):
    execution = original(runtime);proof = execution['blind_audit']
    if defect == 'actor':proof['dispatch']['agent_id'] = 'a19'
    elif defect == 'task':proof['dispatch']['task_id'] = execution['dispatch']['task_id']
    elif defect == 'source':proof['dispatch']['runtime_source_revision'] = '0'*40
    elif defect == 'model':proof['dispatch']['model_calls'] = 1
    elif defect == 'nonce':
        body = json.loads(proof['request']['context']);body['review_nonce'] = str(uuid.uuid4())
        proof['request']['context'] = events.canonical(body).decode()
    elif defect == 'output':proof['artifact_content_utf8'] += ' '
    else:proof['input_action_records'].reverse()
    with pytest.raises(ValueError):validate(execution,runtime)


def test_exact_blind_submission_has_no_automatic_replay(runtime):
    execution = original(runtime)
    count = len(runtime.transport.calls)
    with pytest.raises(ValueError):runtime.operator.dispatch_reviewer(execution['blind_audit']['request'])
    assert len(runtime.transport.calls) == count


def test_unauthenticated_blind_request_is_denied_before_artifact_or_action(runtime):
    execution = original(runtime);before = set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']
    body = deepcopy(execution['blind_audit']['request'])
    context = json.loads(body['context']);context['review_nonce'] = str(uuid.uuid4());body['context'] = events.canonical(context).decode()
    response = runtime.client.post('/api/agents/objectives',json=body)
    assert response.status_code in (401,403)
    assert (set((runtime.root/'artifacts').iterdir()),runtime.ledger.status()['persisted']) == before


def test_actual_input_variation_drives_both_independent_calculations(runtime,monkeypatch):
    real = events.input_bytes
    def changed(case):
        raw = real(case)
        if case != audit.CASE:return raw
        value = json.loads(raw);sample = value['known_observation']
        sample.update(api_checks=7,api_failures=2,service_id='synthetic-alternative',window_id='CA-ALTERNATIVE')
        return events.canonical(value)
    monkeypatch.setattr(events,'input_bytes',changed)
    execution = original(runtime);answer = json.loads(execution['blind_audit']['artifact_content_utf8'])['conclusion']
    assert answer['api_failure_basis_points'] == 2857 and answer['ratio_remainder'] == 1
    assert answer['service_id'] == 'synthetic-alternative' and answer['window_id'] == 'CA-ALTERNATIVE'
    validate(execution,runtime)


def test_actual_blind_action_writer_fsync_failure_prevents_sealed_audit(runtime,monkeypatch):
    import os
    import threading
    from app import agent_dispatch_api
    from app.action_records import ActionLedger
    execute,fsync = audit.execute_blind,os.fsync
    active = [];failures = [];failed_ledgers = []
    def blind(*args,**kwargs):
        assert runtime.ledger.flush()
        failed_ledger = ActionLedger(runtime.ledger.path)
        failed_ledgers.append(failed_ledger)
        active.append(True)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(agent_dispatch_api,'action_ledger',lambda:failed_ledger)
                return execute(*args,**kwargs)
        finally:
            active.pop()
            assert failed_ledger.close() is False
            assert not failed_ledger.worker.is_alive()
    def failed(fd):
        if active and threading.current_thread().name == 'action-observability':
            failures.append(fd);raise OSError('Disposable blind writer fault')
        return fsync(fd)
    monkeypatch.setattr(audit,'execute_blind',blind)
    monkeypatch.setattr(os,'fsync',failed)
    result = collect(runtime,audit.CASE)
    assert failures and result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert result.summary['review_dispatch_attempts'] == 0
    assert failed_ledgers[0].status()['dropped'] > 0
    assert runtime.ledger.status()['healthy'] is True
    for folder in (runtime.root/'artifacts').iterdir():
        assert json.loads((folder/'artifact.json').read_text()).get('schema_version') != audit.SCHEMA


def test_actual_blind_read_cannot_extend_its_shared_deadline(runtime,monkeypatch):
    import time
    from app.deterministic_ops import DeterministicOps
    execute,read = audit.execute_blind,DeterministicOps.retrieve_file
    active = [];calls = []
    def blind(*args,**kwargs):
        active.append(True)
        try:return execute(*args,**kwargs)
        finally:active.pop()
    def delayed(*args,**kwargs):
        value = read(*args,**kwargs)
        if active:
            calls.append(value[1]);time.sleep(5.1)
        return value
    monkeypatch.setattr(audit,'execute_blind',blind)
    monkeypatch.setattr(DeterministicOps,'retrieve_file',delayed)
    result = collect(runtime,audit.CASE)
    assert len(calls) == 1 and result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert result.summary['review_dispatch_attempts'] == 0


def test_actual_slow_fsync_at_both_blind_barriers_uses_one_existing_five_second_budget(runtime,monkeypatch):
    import os,time,threading
    from app.action_records import ActionLedger
    execute,fsync,flush = audit.execute_blind,os.fsync,ActionLedger.flush
    phase = [None];delayed = [];budgets = []
    def blind(*args,**kwargs):
        phase[0] = 'input'
        try:return execute(*args,**kwargs)
        finally:phase[0] = 'output'
    def slow(fd):
        current = phase[0]
        if current and current not in delayed and threading.current_thread().name == 'action-observability':
            delayed.append(current);time.sleep(1.2)
        return fsync(fd)
    def observed(self,timeout=5):
        if phase[0]:budgets.append((phase[0],timeout))
        return flush(self,timeout=timeout)
    monkeypatch.setattr(audit,'execute_blind',blind)
    monkeypatch.setattr(os,'fsync',slow)
    monkeypatch.setattr(ActionLedger,'flush',observed)
    execution = original(runtime)
    assert delayed == ['input','output']
    assert 1 < budgets[1][1] < budgets[0][1] <= 5
    assert execution['blind_audit']['dispatch']['review_action_durable'] is True


def test_case_budget_cannot_be_widened_by_utc_clock_rollback(monkeypatch):
    from datetime import datetime,timedelta,timezone
    started = datetime.now(timezone.utc)
    class Backwards(datetime):
        @classmethod
        def now(cls,tz=None):return started-timedelta(hours=1)
    monkeypatch.setattr(audit,'datetime',Backwards)
    monkeypatch.setattr(audit.time,'monotonic',lambda:14.0)
    assert audit.case_remaining(dict(deadline=15.0,started_at=started)) == 1
    assert audit.case_remaining(dict(deadline=13.0,started_at=started)) == 0


def test_actual_final_blind_artifact_fsync_failure_is_never_durable_evidence(runtime,monkeypatch):
    import os,threading
    from app import agent_dispatch_api
    from app.action_records import ActionLedger
    execute,fsync = audit.execute_blind,os.fsync
    writers = [];failures = []
    def blind(*args,**kwargs):
        data = execute(*args,**kwargs)
        writer = ActionLedger(runtime.ledger.path);writers.append(writer)
        monkeypatch.setattr(agent_dispatch_api,'action_ledger',lambda:writer)
        return data
    def failed(fd):
        if writers and threading.current_thread().name == 'action-observability':
            failures.append(fd);raise OSError('Disposable final audit writer fault')
        return fsync(fd)
    monkeypatch.setattr(audit,'execute_blind',blind)
    monkeypatch.setattr(os,'fsync',failed)
    try:result = collect(runtime,audit.CASE)
    finally:
        assert len(writers) == 1 and writers[0].close() is False
        assert not writers[0].worker.is_alive()
    assert failures and writers[0].status()['dropped'] > 0
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE' and result.summary['review_dispatch_attempts'] == 0
    assert runtime.ledger.status()['healthy'] is True


def test_actual_final_artifact_write_cannot_reset_exhausted_blind_case_budget(runtime,monkeypatch):
    import time
    from app.artifact_factory import ArtifactFactory
    create = ArtifactFactory.create;writes = []
    def delayed(self,*args,**kwargs):
        metadata = create(self,*args,**kwargs)
        if json.loads(kwargs['content']).get('schema_version') == audit.SCHEMA:
            writes.append(metadata['artifact_id']);time.sleep(5.1)
        return metadata
    monkeypatch.setattr(ArtifactFactory,'create',delayed)
    result = collect(runtime,audit.CASE)
    assert len(writes) == 1 and (runtime.root/'artifacts'/writes[0]/'artifact.json').is_file()
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE' and result.summary['review_dispatch_attempts'] == 0


@pytest.mark.parametrize('defect',['missing','wal','giant_row','task_state','artifact_bytes'])
def test_final_peer_original_reread_fails_closed_without_store_initialization(runtime,defect):
    import sqlite3
    from datetime import datetime,timezone
    execution = original(runtime);proof = execution['blind_audit'];task = proof['dispatch']['task_id']
    if defect == 'missing':(runtime.root/'objectives.db').unlink()
    elif defect == 'wal':(runtime.root/'objectives.db-wal').write_bytes(b'x'*(8*1024*1024+1))
    elif defect in ('giant_row','task_state'):
        with sqlite3.connect(runtime.root/'objectives.db') as db:
            if defect == 'giant_row':db.execute('UPDATE objectives SET objective_hash=? WHERE id=?',('x'*2_000_000,task))
            else:db.execute('UPDATE objectives SET state=? WHERE id=?',('dispatching',task))
    else:(runtime.root/'artifacts'/proof['artifact_metadata']['artifact_id']/'artifact.json').write_bytes(b'wrong')
    before = {p.name:p.read_bytes() for p in runtime.root.glob('objectives.db*') if p.is_file()}
    with pytest.raises(ValueError):audit.read_original_audit(runtime.root,proof,
        input_metadata=execution['dispatch']['tool_event']['input_artifact_metadata'],
        input_raw=execution['input_content_utf8'].encode(),runtime=execution['runtime'],registry=runtime.registry_sha,
        authorization='Bearer '+TOKEN,now=datetime.now(timezone.utc))
    assert {p.name:p.read_bytes() for p in runtime.root.glob('objectives.db*') if p.is_file()} == before


def test_actual_input_only_auditor_seals_original_conclusion_before_comparison(runtime,monkeypatch):
    from app.artifact_factory import ArtifactFactory
    from app.deterministic_ops import DeterministicOps
    active = [];reads = []
    execute, retrieve, read_file = audit.execute_blind,ArtifactFactory.retrieve,DeterministicOps.retrieve_file
    def blind(body,*args,**kwargs):
        value = body.model_dump() if hasattr(body,'model_dump') else body
        active.append(json.loads(value['context'])['input_artifact_metadata']['artifact_id'])
        try:return execute(body,*args,**kwargs)
        finally:active.pop()
    def retrieve_only(self,artifact_id):
        if active:
            assert artifact_id == active[-1],'Auditor accessed undisclosed producer answer'
            reads.append(('artifact',artifact_id))
        return retrieve(self,artifact_id)
    def read_only(self,folder,relative,**kwargs):
        if active:
            from pathlib import Path
            assert Path(folder).name == active[-1] and relative == 'artifact.json'
            reads.append(('tool',active[-1]))
        return read_file(self,folder,relative,**kwargs)
    monkeypatch.setattr(audit,'execute_blind',blind)
    monkeypatch.setattr(ArtifactFactory,'retrieve',retrieve_only)
    monkeypatch.setattr(DeterministicOps,'retrieve_file',read_only)
    errors = [];real = audit.validate_audit
    def observed(*args,**kwargs):
        try:return real(*args,**kwargs)
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc));raise
    monkeypatch.setattr(audit,'validate_audit',observed)
    result = collect(runtime,audit.CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE',json.dumps(result.summary)+'; audit_errors='+str(errors)
    execution = json.loads(result.execution_bytes);blind = execution['blind_audit']
    data = json.loads(blind['artifact_content_utf8']);context = json.loads(blind['request']['context'])
    assert set(context) == {'case','input_artifact_metadata','expected_source_revision','expected_registry_sha256','review_nonce'}
    assert 'execution' not in context and execution['artifact_metadata']['artifact_id'] not in json.dumps(context)
    assert execution['artifact_content_utf8'] not in json.dumps(context)
    assert data['conclusion'] == json.loads(execution['artifact_content_utf8'])['assessment']
    assert data['answer_access'] == 'NOT_SUPPLIED_OR_READ' and data['comparison'] == 'NOT_PERFORMED'
    proof = json.loads(result.review_bytes)['observations']['reviewer_execution']
    peer = json.loads(proof['artifact_content_utf8'])
    assert len({execution['dispatch']['task_id'],blind['dispatch']['task_id'],proof['dispatch']['task_id']}) == 3
    assert peer['audit_scope'] == 'SEALED_INPUT_ONLY_AUDIT_THEN_ORIGINAL_ANSWER_COMPARISON'
    assert blind['artifact_metadata']['timestamp'] <= peer['peer_request_receipt']['created_at']
    assert len(blind['input_action_records']) == len(blind['action_records']) == 2
    assert len([1 for method,path,body in runtime.transport.calls if method == 'POST' and path == '/api/agents/objectives']) == 3
    assert result.summary['signature'] == 'NOT_PERFORMED' and result.summary['model_calls'] == 0
    validate(execution,runtime)
    assert any(kind == 'tool' for kind,_ in reads)
    assert all(identifier == execution['dispatch']['tool_event']['input_artifact_metadata']['artifact_id'] for _,identifier in reads)
