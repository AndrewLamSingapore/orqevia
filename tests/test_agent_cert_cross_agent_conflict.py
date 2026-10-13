"""Separate actual unresolved four-Objective case; no borrowed case credit."""
import json
from datetime import datetime,timezone,timedelta
import pytest
from app import agent_cert_cross_conflict_events as events
from scripts.agent_cert_operator_io import CrossConflictPhaseOperatorIO
from scripts.collect_agent_cert_event import collect_cross_conflict_case
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE,NONCE
from tests.test_agent_cert_operator_io import FakeTimer,TOKEN


def collect(runtime,variant='standard'):
    def factory(**kwargs):
        return CrossConflictPhaseOperatorIO(owner_token=TOKEN,expected_source_revision=SOURCE,
            expected_runtime_image=IMAGE,connection_factory=runtime.transport,timer_factory=FakeTimer,
            monotonic=lambda:0.0,**kwargs)
    return collect_cross_conflict_case(operator_factory=factory,variant=variant,expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE,expected_registry_sha256=runtime.registry_sha,
        monotonic=lambda:0.0,nonce_factory=lambda:NONCE)


@pytest.mark.parametrize('variant',['standard','swapped'])
def test_actual_four_original_objectives_keep_both_conclusions_unresolved(runtime,variant):
    result=collect(runtime,variant)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    originals=execution['peer_executions'];resolved=json.loads(execution['artifact_content_utf8'])['result']
    assert len({value['dispatch']['task_id'] for value in originals+[execution,peer]})==4
    assert [path for method,path in runtime.requests if method=='POST']==['/api/agents/objectives']*4
    assert [len(value['original_action_records']) for value in originals+[execution]]==[6,6,12]
    assert len(peer['action_records'])==2
    assert resolved['resolution']=='UNRESOLVED_PENDING_INDEPENDENT_DISCRIMINATING_CHECK'
    assert resolved['selected_peer_task_id'] is None and resolved['production_health']=='UNKNOWN'
    assert resolved['discriminating_check_execution']=='NOT_PERFORMED'
    assert {item['original_result']['original_conclusion'] for item in resolved['preserved_conclusions']}=={'HEALTHY','DEGRADED'}
    assert all(value['objective_read'][1]['execution_metadata']['jobs']==[] for value in originals+[execution,peer])
    assert events.validate_reviewed_conflict(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))['certification']=='UNVERIFIED'
    request=resolved['required_independent_check']
    assert request['service_id']=='PUBLIC-CONFLICT-SERVICE' and request['check_spec']=='PUBLIC_STATUS_CHECK'
    assert request['comparison_targets']==[value['dispatch']['task_id'] for value in originals]
    assert request['execution']=='NOT_PERFORMED'
    assert len(events.canonical(execution))<80000 and len(events.canonical(peer))<65536


def recompute(result,**changes):
    from scripts.agent_cert_reviewed_signing import _review
    now=datetime.now(timezone.utc)
    row=dict(agent_id='a19',capability_id='responsibility.a19',dimension='cross_agent_conflict',test_case='complete',
        certification_test='original-four-unresolved-tasks',test_version=events.VERSION,test_result='PASS',verifier='a26',
        executor_identity='a19',source_revision=SOURCE,review_source_revision=SOURCE,reviewer_code_revision='f'*40,
        authority_scope='advisory',review_test_version=events.ORACLE,review_run_id='temporary-unresolved-conflict',
        certified_at=now.isoformat(),last_revalidated=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    row.update(changes.pop('row',{}))
    return _review(row,result.execution_bytes,result.peer_execution_bytes,source_revision=SOURCE,
        runtime_image_id=IMAGE,reviewer_code_revision='f'*40,now=now,**changes)


def test_original_unresolved_chain_pure_admission_no_signing(runtime):
    assert recompute(collect(runtime)) is True


@pytest.mark.parametrize('field,value',[
    ('verifier','a19'),('authority_scope','executor'),('source_revision','b'*40),
    ('test_version','borrowed'),('review_test_version','borrowed'),
    ('certified_at','2000-01-01T00:00:00+00:00'),('expires_at','2000-01-01T00:00:00+00:00')])
def test_record_cannot_expand_authority_change_source_or_renew_time(runtime,field,value):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    with pytest.raises(CertificationReviewError):recompute(collect(runtime),row={field:value})


def test_cloud_transport_cannot_replace_original_unresolved_tasks(runtime):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    with pytest.raises(CertificationReviewError,match='CROSS_CONFLICT_CLOUD_TRANSPORT_FORBIDDEN'):
        recompute(collect(runtime),cloud_binding={'claimed':'PASS'})


@pytest.mark.parametrize('fault',['select_first','select_second','collapse','agreement','check_executed',
    'health_confirmed','wrong_target','omit_original','missing_gap'])
def test_actual_wrong_separation_rejected_by_independent_oracle(runtime,monkeypatch,fault):
    original=events.producer_result
    def wrong(which,**kwargs):
        raw=original(which,**kwargs)
        if which!='separation':return raw
        value=json.loads(raw);out=value['result']
        if fault.startswith('select_'):
            index=0 if fault=='select_first' else 1
            out['selected_peer_task_id']=out['preserved_conclusions'][index]['task_id']
        elif fault=='collapse':out['preserved_conclusions'][1]=out['preserved_conclusions'][0]
        elif fault=='agreement':out['resolution']='PEERS_AGREE_HEALTHY'
        elif fault=='check_executed':out['discriminating_check_execution']='PERFORMED'
        elif fault=='health_confirmed':out['production_health']='CONFIRMED_HEALTHY'
        elif fault=='wrong_target':out['required_independent_check']['service_id']='another-service'
        elif fault=='omit_original':out['preserved_conclusions'].pop()
        else:out['required_independent_check']['needed_evidence']=[]
        return events.canonical(value)
    monkeypatch.setattr(events,'producer_result',wrong)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE'
    assert len([path for method,path in runtime.requests if method=='POST'])==3
    assert runtime.ledger.status()['persisted']==24


@pytest.mark.parametrize('fault',['producer_assessment','report_builder'])
def test_original_consumer_is_independent_of_producer_and_review_builders(runtime,monkeypatch,fault):
    if fault=='producer_assessment':
        original=events._source_assessment
        def wrong(source):return dict(original(source),conclusion_confirmed=True)
        monkeypatch.setattr(events,'_source_assessment',wrong)
    else:
        original=events._review_report
        def wrong(*args):return dict(original(*args),certification='L7')
        monkeypatch.setattr(events,'_review_report',wrong)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE'
    assert len([path for method,path in runtime.requests if method=='POST'])==(1 if fault=='producer_assessment' else 4)


@pytest.mark.parametrize('mutation',['origin','source','task','report','future','request','contribution_only'])
def test_original_unresolved_join_rejects_changed_provenance(runtime,mutation):
    result=collect(runtime);execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    if mutation=='origin':execution['peer_executions'].reverse()
    elif mutation=='source':execution['peer_executions'][0]['input_content_utf8']=execution['peer_executions'][1]['input_content_utf8']
    elif mutation=='task':execution['peer_executions'][0]['dispatch']['task_id']=execution['dispatch']['task_id']
    elif mutation=='report':peer['artifact_content_utf8']=peer['artifact_content_utf8'].replace('UNVERIFIED','L7')
    elif mutation=='future':execution['observation']['completed_at']='2099-01-01T00:00:00+00:00'
    elif mutation=='request':execution['submitted_request_sha256']='a'*64
    else:execution=execution['peer_executions'][0]
    with pytest.raises(ValueError):events.validate_reviewed_conflict(execution,peer,source_revision=SOURCE,
        runtime_image_id=IMAGE,registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


def test_actual_source_quality_case_cannot_supply_sibling_case_credit(runtime):
    from tests.test_agent_cert_conflict_resolution import collect as collect_reconciliation
    old=collect_reconciliation(runtime)
    assert old.summary['state']=='UNSIGNED_EVENT_EVIDENCE',old.summary
    with pytest.raises(ValueError):events.validate_reviewed_conflict(json.loads(old.execution_bytes),
        json.loads(old.peer_execution_bytes),source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


@pytest.mark.parametrize('domain',['input','result','objective','ledger'])
def test_actual_original_domain_change_between_a26_reads_rejected(runtime,monkeypatch,domain):
    import sqlite3
    original=events.reread_original;mutated=[]
    def change(root,execution,**kwargs):
        checked=original(root,execution,**kwargs)
        if execution['dispatch']['conflict_event']['phase']=='separation' and not mutated:
            task=execution['dispatch']['task_id']
            if domain=='objective':
                with sqlite3.connect(root/'objectives.db') as db:
                    db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?',
                        ('2000-01-01T00:00:00+00:00',task))
            elif domain=='ledger':
                path=root/'action-records.jsonl'
                path.write_bytes(path.read_bytes()+execution['original_action_records'][0].encode())
            else:
                metadata=execution['artifact_metadata'] if domain=='result' else execution['dispatch']['conflict_event']['input_artifact_metadata']
                (root/'artifacts'/metadata['artifact_id']/'artifact.json').write_bytes(b'{}')
            mutated.append(domain)
        return checked
    monkeypatch.setattr(events,'reread_original',change)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and mutated==[domain]
    assert len([path for method,path in runtime.requests if method=='POST'])==4
    rows=[json.loads(line) for line in (runtime.root/'action-records.jsonl').read_text().splitlines()]
    assert len(rows)==(25 if domain=='ledger' else 24) and all(row['agent_id']!='a26' for row in rows)


@pytest.mark.parametrize('mutation',['invented_check','collapsed','task','source'])
def test_actual_authenticated_a26_denies_changed_original_without_peer_writes(runtime,mutation):
    import uuid
    result=collect(runtime);execution=json.loads(result.execution_bytes)
    if mutation in ('invented_check','collapsed'):
        value=json.loads(execution['artifact_content_utf8'])
        if mutation=='invented_check':value['result']['discriminating_check_execution']='PERFORMED'
        else:value['result']['preserved_conclusions'].pop()
        execution['artifact_content_utf8']=events.canonical(value).decode()
    elif mutation=='task':execution['peer_executions'][0]['dispatch']['task_id']=execution['dispatch']['task_id']
    else:execution['runtime']['source_revision']='b'*40
    request=events.phase_request('review',execution=execution,nonce=str(uuid.uuid4()))
    before=(runtime.root/'action-records.jsonl').read_bytes()
    artifacts={path.name for path in (runtime.root/'artifacts').iterdir()}
    reply=runtime.client.post('/api/agents/objectives',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code==202 and reply.json()['steps'][0]['state']=='blocked',reply.json()
    actual=runtime.client.get('/api/agents/objectives/'+reply.json()['id'],headers={'Authorization':'Bearer '+TOKEN}).json()
    assert actual['state']=='COMPLETED_WITH_FAILURES' and actual['execution_metadata']['jobs']==[]
    assert (runtime.root/'action-records.jsonl').read_bytes()==before
    assert {path.name for path in (runtime.root/'artifacts').iterdir()}==artifacts


def test_actual_delayed_durable_writer_uses_shared_five_seconds(runtime,monkeypatch):
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
    assert calls and runtime.ledger.status()['persisted']==26


def test_actual_failed_durable_writer_never_passes(runtime,monkeypatch):
    from types import SimpleNamespace
    from app import action_records
    def failed(fd):raise OSError('controlled disposable writer failure')
    monkeypatch.setattr(action_records,'os',SimpleNamespace(fsync=failed))
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and len([p for m,p in runtime.requests if m=='POST'])==1
    assert runtime.ledger.status()['dropped']==6 and runtime.ledger.close() is False
    monkeypatch.setattr(runtime.ledger,'close',lambda:True)


def test_exhausted_shared_budget_no_flush_or_peer(runtime,monkeypatch):
    from types import SimpleNamespace
    samples=iter([0.0,6.0]);flushes=[]
    monkeypatch.setattr(events,'time',SimpleNamespace(monotonic=lambda:next(samples,6.0)))
    original=runtime.ledger.flush
    def flush(*args,**kwargs):flushes.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(runtime.ledger,'flush',flush)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and flushes==[]
    assert len([path for method,path in runtime.requests if method=='POST'])==1
