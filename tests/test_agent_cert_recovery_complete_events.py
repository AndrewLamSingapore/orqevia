"""Disposable authenticated original two-task challenge; no live case/L7 proof."""
import json
import copy
from datetime import datetime,timezone,timedelta
import pytest

from app import agent_cert_recovery_events as events
from scripts.agent_cert_operator_io import RecoveryPhaseOperatorIO
from scripts.collect_agent_cert_event import collect_recovery_case
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE,NONCE
from tests.test_agent_cert_operator_io import FakeTimer,TOKEN


def collect(runtime):
    def factory(**kwargs):
        return RecoveryPhaseOperatorIO(owner_token=TOKEN,expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
            connection_factory=runtime.transport,timer_factory=FakeTimer,monotonic=lambda:0.0,**kwargs)
    return collect_recovery_case(operator_factory=factory,expected_source_revision=SOURCE,expected_runtime_image=IMAGE,
        expected_registry_sha256=runtime.registry_sha,monotonic=lambda:0.0,nonce_factory=lambda:NONCE)


def test_actual_three_persisted_objectives_retained_failure_and_newer_correction(runtime):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    prior=execution['prior_execution']
    prior_result=json.loads(prior['artifact_content_utf8']);corrected=json.loads(execution['artifact_content_utf8'])
    assert prior_result['failure_classification']=='CONTROLLED_FAILURE' and prior_result['continuous_health']=='HEALTHY'
    assert corrected['continuous_health']=='UNKNOWN' and corrected['failure_basis_points']==500
    assert corrected['retained_wrong_result_sha256']==events.sha(prior['artifact_content_utf8'].encode())
    tasks={prior['dispatch']['task_id'],execution['dispatch']['task_id'],peer['dispatch']['task_id']}
    assert len(tasks)==3
    assert [path for method,path in runtime.requests if method=='POST']==['/api/agents/objectives']*3
    assert all(value['objective_read'][1]['execution_metadata']['jobs']==[] for value in (prior,execution,peer))
    assert len(prior['original_action_records'])==len(execution['original_action_records'])==6
    assert len(peer['action_records'])==2
    assert result.summary['controlled_failure_retained'] is True
    joined=events.validate_reviewed_recovery(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))
    assert joined['certification']=='UNVERIFIED'


def recompute(result, **changes):
    from scripts.agent_cert_reviewed_signing import _review
    now=datetime.now(timezone.utc)
    row=dict(agent_id='a19',capability_id='responsibility.a19',dimension='recovery',test_case='complete',
        certification_test='original-two-task-recovery',test_version=events.VERSION,test_result='PASS',
        verifier='a26',executor_identity='a19',source_revision=SOURCE,review_source_revision=SOURCE,
        reviewer_code_revision='f'*40,authority_scope='advisory',review_test_version=events.ORACLE,
        review_run_id='temporary-original-recovery',certified_at=now.isoformat(),last_revalidated=now.isoformat(),
        expires_at=(now+timedelta(hours=1)).isoformat())
    row.update(changes.pop('row',{}))
    options=dict(source_revision=SOURCE,runtime_image_id=IMAGE,reviewer_code_revision='f'*40,now=now)
    options.update(changes)
    return _review(row,result.execution_bytes,result.peer_execution_bytes,**options)


def test_pure_admission_accepts_original_chain_without_signing(runtime):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    assert recompute(result) is True


@pytest.mark.parametrize('change',[
    {'verifier':'a19'}, {'test_version':'borrowed'}, {'review_test_version':'borrowed'},
    {'source_revision':'b'*40}, {'authority_scope':'executor'},
    {'certified_at':'2000-01-01T00:00:00+00:00'}, {'expires_at':'2000-01-01T00:00:00+00:00'},
])
def test_admission_rejects_record_authority_source_and_time_drift(runtime,change):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    with pytest.raises(CertificationReviewError):recompute(result,row=change)


def test_cloud_receipt_cannot_substitute_original_custody(runtime):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    result=collect(runtime)
    with pytest.raises(CertificationReviewError,match='RECOVERY_CLOUD_TRANSPORT_FORBIDDEN'):
        recompute(result,cloud_binding={'claimed':'PASS'})


@pytest.mark.parametrize('field,value',[
    ('continuous_health','HEALTHY'),('failure_basis_points',0),('production_recovery','CONFIRMED'),
    ('owner_authority','GRANTED'),('model_calls',1),('certification','L7'),
])
def test_actual_wrong_producer_output_rejected_before_peer_objective(runtime,monkeypatch,field,value):
    original=events.producer_result
    def corrupt(which,**kwargs):
        raw=original(which,**kwargs)
        if which==events.CORRECTION_PHASE:
            result=json.loads(raw);result[field]=value;return events.canonical(result)
        return raw
    monkeypatch.setattr(events,'producer_result',corrupt)
    result=collect(runtime)
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert len([path for method,path in runtime.requests if method=='POST'])==2
    assert runtime.ledger.status()['persisted']>=6


@pytest.mark.parametrize('mutation',['prior_task','prior_result','newer_input','peer_task','source','action'])
def test_original_join_rejects_tampered_chain(runtime,mutation):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    if mutation=='prior_task':execution['prior_execution']['dispatch']['task_id']=execution['dispatch']['task_id']
    elif mutation=='prior_result':execution['prior_execution']['artifact_content_utf8']='{}'
    elif mutation=='newer_input':execution['input_content_utf8']='{}'
    elif mutation=='peer_task':peer['dispatch']['task_id']=execution['dispatch']['task_id']
    elif mutation=='source':execution['runtime']['source_revision']='b'*40
    else:execution['original_action_records'][0]='{}'
    with pytest.raises((ValueError,KeyError,TypeError)):
        events.validate_reviewed_recovery(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
            registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


def test_original_controlled_failure_alone_cannot_pass_recovery(runtime):
    result=collect(runtime);execution=json.loads(result.execution_bytes)
    with pytest.raises(events.RecoveryEventError):
        events.validate_recovery_execution(execution['prior_execution'],source_revision=SOURCE,
            runtime_image_id=IMAGE,registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


@pytest.mark.parametrize('which,domain',[
    (events.PRIOR_PHASE,'result'),(events.PRIOR_PHASE,'input'),
    (events.CORRECTION_PHASE,'result'),(events.CORRECTION_PHASE,'input'),
    (events.PRIOR_PHASE,'objective'),(events.CORRECTION_PHASE,'objective'),
    (events.PRIOR_PHASE,'ledger'),(events.CORRECTION_PHASE,'ledger'),
])
def test_peer_second_physical_read_rejects_changed_original(runtime,monkeypatch,which,domain):
    original=events.reread_phase_original
    calls=[];mutated=[]
    def read(root,execution,**kwargs):
        checked=original(root,execution,**kwargs)
        actual=execution['dispatch']['recovery_event']['phase'];calls.append(actual)
        # Prior has one producer read; the next prior/correction read is the
        # peer's first pass. Mutate only after that actual successful read.
        threshold=2 if which==events.PRIOR_PHASE else 1
        if actual==which and calls.count(which)==threshold:
            if domain=='objective':
                import sqlite3
                with sqlite3.connect(root/'objectives.db') as db:
                    db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?',
                        ('2000-01-01T00:00:00+00:00',execution['dispatch']['task_id']))
            elif domain=='ledger':
                path=root/'action-records.jsonl'
                path.write_bytes(path.read_bytes()+execution['original_action_records'][0].encode())
            else:
                meta=execution['artifact_metadata'] if domain=='result' else execution['dispatch']['recovery_event']['input_artifact_metadata']
                (root/'artifacts'/meta['artifact_id']/'artifact.json').write_bytes(b'{}')
            mutated.append(domain)
        return checked
    monkeypatch.setattr(events,'reread_phase_original',read)
    result=collect(runtime)
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert mutated and len([p for m,p in runtime.requests if m=='POST'])==3
    rows=[json.loads(line) for line in (runtime.root/'action-records.jsonl').read_text().splitlines()]
    assert len(rows)==(13 if domain=='ledger' else 12) and all(row['agent_id']=='a19' for row in rows)


def test_real_delayed_durable_writer_uses_remaining_five_second_budget(runtime,monkeypatch):
    import os,time
    from types import SimpleNamespace
    from app import action_records
    original=os.fsync;calls=[]
    def delayed(fd):
        calls.append(fd)
        if len(calls)==1:time.sleep(1.2)
        return original(fd)
    monkeypatch.setattr(action_records,'os',SimpleNamespace(fsync=delayed))
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    assert calls and runtime.ledger.status()['persisted']==14


def test_failed_durable_writer_never_yields_completed_case(runtime,monkeypatch):
    from types import SimpleNamespace
    from app import action_records
    def failed(fd):raise OSError('controlled disposable writer failure')
    monkeypatch.setattr(action_records,'os',SimpleNamespace(fsync=failed))
    result=collect(runtime)
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert len([p for m,p in runtime.requests if m=='POST'])==1
    assert runtime.ledger.status()['dropped']==6
    # Stop the actual failed disposable writer and retain its failure result;
    # the shared fixture's later teardown only acknowledges this prior close.
    assert runtime.ledger.close() is False
    monkeypatch.setattr(runtime.ledger,'close',lambda:True)


def test_exhausted_shared_budget_performs_no_flush_or_peer(runtime,monkeypatch):
    from types import SimpleNamespace
    samples=iter([0.0,6.0]);flushes=[]
    monkeypatch.setattr(events,'time',SimpleNamespace(monotonic=lambda:next(samples,6.0)))
    original=runtime.ledger.flush
    def flush(*args,**kwargs):flushes.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(runtime.ledger,'flush',flush)
    result=collect(runtime)
    assert result.summary['state']!='UNSIGNED_EVENT_EVIDENCE'
    assert flushes==[] and len([p for m,p in runtime.requests if m=='POST'])==1


@pytest.mark.parametrize('mutation',['result','prior','source','task','ordering'])
def test_actual_authenticated_a26_rejects_corrupted_original_without_peer_writes(runtime,mutation):
    import uuid
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes)
    if mutation=='result':execution['artifact_content_utf8']='{}'
    elif mutation=='prior':execution['prior_execution']['artifact_content_utf8']='{}'
    elif mutation=='source':execution['runtime']['source_revision']='b'*40
    elif mutation=='task':execution['prior_execution']['dispatch']['task_id']=execution['dispatch']['task_id']
    else:execution['observation']['completed_at']='2099-01-01T00:00:00+00:00'
    request=events.canonical_review_request(execution,nonce=str(uuid.uuid4()))
    before=(runtime.root/'action-records.jsonl').read_bytes()
    artifacts={path.name for path in (runtime.root/'artifacts').iterdir()}
    reply=runtime.client.post('/api/agents/objectives',json=request,
        headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code==202
    assert reply.json()['steps'][0]['state']=='blocked',reply.json()['steps']
    original=runtime.client.get('/api/agents/objectives/'+reply.json()['id'],
        headers={'Authorization':'Bearer '+TOKEN}).json()
    assert original['state']=='COMPLETED_WITH_FAILURES'
    assert original['execution_metadata']['jobs']==[]
    assert (runtime.root/'action-records.jsonl').read_bytes()==before
    assert {path.name for path in (runtime.root/'artifacts').iterdir()}==artifacts
