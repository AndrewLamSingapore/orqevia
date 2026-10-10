"""Disposable original supported peer refusal; no runtime/agent-health claim."""
import json
import pytest
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE,NONCE
from tests.test_agent_cert_operator_io import FakeTimer,TOKEN
from scripts.agent_cert_operator_io import HandoffFailureOperatorIO,HandoffContinuationOperatorIO
from scripts.collect_agent_cert_event import collect_handoff_case
from app.agent_cert_handoff_gap import CASE,FAILURE_CASE,FAILURE_REASON


def collect(runtime,case=CASE):
    def factory(which,**kwargs):
        cls=HandoffFailureOperatorIO if which=='failure' else HandoffContinuationOperatorIO
        return cls(owner_token=TOKEN,expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
            connection_factory=runtime.transport,timer_factory=FakeTimer,monotonic=lambda:0.0,**kwargs)
    return collect_handoff_case(case=case,operator_factory=factory,expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE,expected_registry_sha256=runtime.registry_sha,
        reviewer_code_revision='f'*40,review_run_id='temporary-original-handoff',
        monotonic=lambda:0.0,nonce_factory=lambda:NONCE)


@pytest.mark.parametrize('case', (CASE,FAILURE_CASE))
def test_original_supported_refusal_retained_before_actual_continuation_and_fresh_review(runtime,case):
    result=collect(runtime,case)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',{k:result.summary.get(k) for k in ('state','stage','reason')}
    failed=json.loads(result.original_failure_bytes)
    assert failed['state']=='COMPLETED_WITH_FAILURES'
    assert failed['steps'][0]['reason']=='STEP_DISPATCH_FAILED'
    assert failed['execution_metadata']['lifecycle']['started_at_reason']=='NO_EXECUTION_STARTED_DISPATCH_BLOCKED'
    continuation=json.loads(result.continuation.execution_bytes)
    answer=json.loads(continuation['artifact_content_utf8'])
    assert answer['failure_basis_points']==500
    assert answer['peer_dependent_gap']=='ORIGINAL_PEER_EVIDENCE_UNAVAILABLE'
    assert answer['failed_peer']['failure_scope']=='MISSING_REQUIRED_ORIGINAL_PEER_EVIDENCE_NOT_AGENT_CRASH'
    assert len({failed['id'],continuation['dispatch']['task_id'],result.summary['review_task_id']})==3
    assert len([p for m,p in runtime.requests if m=='POST'])==3
    db=__import__('sqlite3').connect(runtime.root/'objectives.db')
    try:stored=json.loads(db.execute('SELECT steps_json FROM objectives WHERE id=?',(failed['id'],)).fetchone()[0])
    finally:db.close()
    assert stored[0]['reason']==FAILURE_REASON
    assert stored[0]['source_handoff_trace']==failed['steps'][0]['source_handoff_trace']
    assert len(continuation['original_action_records'])==6
    from app import agent_cert_tool_events as events
    action=events.tool_action_type(case,phase='full')
    response=runtime.client.get('/api/agent-cert-events/actions/'+continuation['dispatch']['task_id'],
        params={'action_type':action},headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==200,response.json()
    assert response.json()['original_lines']==continuation['original_action_records']
    assert not any(json.loads(x)['task_id']==failed['id'] for x in (runtime.root/'action-records.jsonl').read_text().splitlines())

import copy
import pytest
from datetime import datetime,timezone
from app import agent_cert_handoff_gap as gap


@pytest.mark.parametrize('field,value',[
 ('peer_conclusion','CONFIRMED'),('peer_retry_count',1),('recovery','PROVEN'),
 ('current_health','HEALTHY'),('authority_transfer',True),('failure_basis_points',0),
 ('peer_dependent_gap','NO_GAP')])
def test_independent_oracle_rejects_wrong_claim_without_using_producer(runtime,monkeypatch,field,value):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.continuation.execution_bytes)
    answer=json.loads(execution['artifact_content_utf8']);answer[field]=value
    def forbidden(*args,**kwargs):pytest.fail('Independent oracle borrowed producer')
    monkeypatch.setattr(gap,'produce_assessment',forbidden)
    with pytest.raises(ValueError,match='HANDOFF_INDEPENDENT_ASSESSMENT_REJECTED'):
        gap.validate_assessment(gap.canonical(answer),execution['input_content_utf8'].encode(),
            execution['dispatch']['tool_event']['original_failed_peer'],runtime=execution['runtime'],
            registry_sha256=runtime.registry_sha,task_id=execution['dispatch']['task_id'],
            now=datetime.now(timezone.utc))


@pytest.mark.parametrize('defect',['task','request_hash','runtime','reason','trace'])
def test_rehashed_original_failure_cannot_replace_actual_private_store(runtime,defect):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.continuation.execution_bytes)
    failed=json.loads(result.original_failure_bytes)
    if defect=='task':failed['id']=execution['dispatch']['task_id']
    elif defect=='request_hash':failed['steps'][0]['source_handoff_trace']['dispatcher_request_sha256']='e'*64
    elif defect=='runtime':failed['steps'][0]['source_handoff_trace']['runtime']['source_revision']='e'*40
    elif defect=='reason':failed['steps'][0]['reason']='AGENT_CRASHED'
    else:failed['steps'][0]['source_handoff_trace']['outcome']='AGENT_FAILED'
    with pytest.raises(ValueError):gap.read_failed_store(runtime.root,failed,runtime=execution['runtime'],
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc),
        subject_task=execution['dispatch']['task_id'],deadline=__import__('time').monotonic()+1)


def test_arbitrary_refusal_keeps_existing_public_detail_without_source_trace(runtime):
    body=gap.failure_request();body['context']='{}'
    reply=runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code==202
    task=reply.json()['id']
    actual=runtime.client.get('/api/agents/objectives/'+task,headers={'Authorization':'Bearer '+TOKEN}).json()
    assert actual['steps'][0]['reason']=='STEP_DISPATCH_FAILED'
    assert 'source_handoff_trace' not in actual['steps'][0]


def test_fixed_denial_never_accepts_client_trace_or_objective_drift(runtime):
    for key,value in (('objective','Claim peer failure'),('context',gap.canonical(dict(
            source_case=CASE,missing_original_peer_evidence=True,
            scope='PUBLIC_SOURCE_MISSING_EVIDENCE_HANDOFF_ONLY',source_handoff_trace={'claimed':'server'})).decode())):
        body=gap.failure_request();body[key]=value
        reply=runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
        assert reply.status_code==202
        actual=runtime.client.get('/api/agents/objectives/'+reply.json()['id'],headers={'Authorization':'Bearer '+TOKEN}).json()
        assert 'source_handoff_trace' not in actual['steps'][0]


def test_pure_original_admission_checks_prior_and_distinct_peer_without_signing(runtime):
    from scripts.agent_cert_reviewed_signing import _review
    from app.agent_cert_tool_events import case_version,oracle_id
    from datetime import timedelta
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    now=datetime.now(timezone.utc)
    row=dict(agent_id='a19',capability_id='responsibility.a19',dimension='handoff_recovery',test_case='bounded_response',
        certification_test='temporary-original-failed-handoff',test_version=case_version(CASE),test_result='PASS',
        verifier='a26',executor_identity='a19',source_revision=SOURCE,review_source_revision=SOURCE,
        reviewer_code_revision='f'*40,authority_scope='advisory',review_test_version=oracle_id(CASE),
        review_run_id='temporary-original-handoff',certified_at=now.isoformat(),last_revalidated=now.isoformat(),
        expires_at=(now+timedelta(hours=1)).isoformat())
    assert _review(row,result.continuation.execution_bytes,result.continuation.review_bytes,
        source_revision=SOURCE,runtime_image_id=IMAGE,reviewer_code_revision='f'*40,now=now) is True

@pytest.mark.parametrize('defect',['stored_reason','stored_trace','stored_request','stored_runtime','stored_time'])
def test_actual_final_failed_store_drift_prevents_peer_review_writes(runtime,monkeypatch,defect):
    import sqlite3
    from app import objective_api
    original=objective_api.get_read_only;failed_task=[None];reads=[0];tampered=[]
    def reread(task,authorization):
        value=original(task,authorization)
        if value['state']=='COMPLETED_WITH_FAILURES' and value['steps'][0].get('source_handoff_trace'):
            failed_task[0]=task;reads[0]+=1
            # Two owning producer calls, then the two A26 joining calls.
            # HTTP API GETs use their own endpoint and are not this callback.
            if reads[0]==4:
                db=sqlite3.connect(runtime.root/'objectives.db')
                try:
                    if defect in ('stored_reason','stored_trace'):
                        stored=json.loads(db.execute('SELECT steps_json FROM objectives WHERE id=?',(task,)).fetchone()[0])
                        if defect=='stored_reason':stored[0]['reason']='Borrowed denial'
                        else:stored[0]['source_handoff_trace']['dispatcher_request_sha256']='e'*64
                        db.execute('UPDATE objectives SET steps_json=? WHERE id=?',(json.dumps(stored),task))
                    elif defect=='stored_request':db.execute('UPDATE objectives SET objective_hash=? WHERE id=?',('e'*64,task))
                    elif defect=='stored_runtime':db.execute('UPDATE objective_runtime SET source_revision=? WHERE task=?',('e'*40,task))
                    else:db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?',('2000-01-01T00:00:00+00:00',task))
                    db.commit();tampered.append(task)
                finally:db.close()
        return value
    monkeypatch.setattr(objective_api,'get_read_only',reread)
    result=collect(runtime)
    assert tampered and reads[0]>=4
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert runtime.ledger.status()['persisted']==6
    assert len(list((runtime.root/'artifacts').iterdir()))==2


def test_actual_slow_continuation_fsync_uses_original_five_second_budget(runtime,monkeypatch):
    import os,time,threading
    from app import agent_cert_tool_events as events
    execute,fsync=events.execute_tool_case,os.fsync;active=[False];delayed=[]
    def continuation(spec,*args,**kwargs):
        active[0]=True
        try:return execute(spec,*args,**kwargs)
        finally:active[0]=False
    def slow(fd):
        if active[0] and not delayed and threading.current_thread().name=='action-observability':
            delayed.append(fd);time.sleep(1.2)
        return fsync(fd)
    monkeypatch.setattr(events,'execute_tool_case',continuation);monkeypatch.setattr(os,'fsync',slow)
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    assert len(delayed)==1


def test_separate_agent_failure_case_actually_continues_assessment_after_retained_refusal(runtime):
    result=collect(runtime,gap.FAILURE_CASE)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.continuation.execution_bytes)
    answer=json.loads(execution['artifact_content_utf8'])
    assert answer['case']==gap.FAILURE_CASE
    assert answer['known_observation']['source_id']=='HG2'
    assert answer['continuation_status']=='ASSESSMENT_COMPLETED_AFTER_ORIGINAL_HANDOFF_REFUSAL'
    assert 'gap_status' not in answer and answer['failure_basis_points']==500
    failed=json.loads(result.original_failure_bytes)
    assert failed['steps'][0]['source_handoff_trace']['source_case']==gap.FAILURE_CASE
    assert failed['execution_metadata']['lifecycle']['started_at_reason']=='NO_EXECUTION_STARTED_DISPATCH_BLOCKED'
    assert len(execution['original_action_records'])==6
    assert len({failed['id'],execution['dispatch']['task_id'],result.summary['review_task_id']})==3


def test_actual_slow_final_peer_fsync_uses_same_original_five_second_budget(runtime,monkeypatch):
    import os,time,threading
    from app import agent_dispatch_api as dispatch
    joined,fsync=dispatch._joined_contract_event_review,os.fsync;active=[False];delayed=[]
    def review(*args,**kwargs):
        value=joined(*args,**kwargs)
        if value['dimension']=='handoff_recovery':active[0]=True
        return value
    def slow(fd):
        if active[0] and not delayed and threading.current_thread().name=='action-observability':
            delayed.append(fd);time.sleep(1.2)
        return fsync(fd)
    monkeypatch.setattr(dispatch,'_joined_contract_event_review',review);monkeypatch.setattr(os,'fsync',slow)
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    assert len(delayed)==1


def test_actual_final_peer_artifact_delay_cannot_reset_original_five_seconds(runtime,monkeypatch):
    import time
    from app.artifact_factory import ArtifactFactory
    create=ArtifactFactory.create;delayed=[]
    def late(self,*args,**kwargs):
        metadata=create(self,*args,**kwargs)
        content=json.loads(kwargs['content'])
        if content.get('dimension')=='handoff_recovery':
            delayed.append(metadata['artifact_id']);time.sleep(5.1)
        return metadata
    monkeypatch.setattr(ArtifactFactory,'create',late)
    result=collect(runtime)
    assert len(delayed)==1
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert (runtime.root/'artifacts'/delayed[0]/'artifact.json').is_file()
