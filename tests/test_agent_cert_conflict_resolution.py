"""Original temporary four-Objective public conflict; no production case credit."""
import json
import copy
from datetime import datetime,timezone,timedelta
import pytest
from app import agent_cert_conflict_events as events
from scripts.agent_cert_operator_io import ConflictPhaseOperatorIO
from scripts.collect_agent_cert_event import collect_conflict_case
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE,NONCE
from tests.test_agent_cert_operator_io import FakeTimer,TOKEN


def collect(runtime,variant='standard'):
    def factory(**kwargs):
        return ConflictPhaseOperatorIO(owner_token=TOKEN,expected_source_revision=SOURCE,
            expected_runtime_image=IMAGE,connection_factory=runtime.transport,timer_factory=FakeTimer,
            monotonic=lambda:0.0,**kwargs)
    return collect_conflict_case(operator_factory=factory,variant=variant,expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE,expected_registry_sha256=runtime.registry_sha,
        monotonic=lambda:0.0,nonce_factory=lambda:NONCE)


@pytest.mark.parametrize('variant',['standard','swapped'])
def test_actual_four_original_objectives_select_source_data_not_identity(runtime,variant):
    result=collect(runtime,variant)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    originals=execution['peer_executions'];resolved=json.loads(execution['artifact_content_utf8'])
    assert len({value['dispatch']['task_id'] for value in originals+[execution,peer]})==4
    assert [path for method,path in runtime.requests if method=='POST']==['/api/agents/objectives']*4
    assert [len(value['original_action_records']) for value in originals+[execution]]==[6,6,12]
    assert len(peer['action_records'])==2
    assert resolved['result']['continuous_health']=='UNKNOWN' and resolved['result']['failure_basis_points']==500
    assert resolved['result']['selected_source_id']=='CF-CURRENT'
    assert all(value['objective_read'][1]['execution_metadata']['jobs']==[] for value in originals+[execution,peer])
    assert events.validate_reviewed_conflict(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))['certification']=='UNVERIFIED'
    selected=resolved['result']['selected_peer_task_id']
    assert selected==originals[1 if variant=='standard' else 0]['dispatch']['task_id']
    assert any(item['original_result']['continuous_health']=='HEALTHY'
        for item in resolved['result']['preserved_recommendations'])
    assert len(events.canonical(execution))<80000 and len(events.canonical(peer))<65536


def recompute(result,**changes):
    from scripts.agent_cert_reviewed_signing import _review
    now=datetime.now(timezone.utc)
    row=dict(agent_id='a19',capability_id='responsibility.a19',dimension='conflict_resolution',test_case='complete',
        certification_test='original-four-source-tasks',test_version=events.VERSION,test_result='PASS',verifier='a26',
        executor_identity='a19',source_revision=SOURCE,review_source_revision=SOURCE,reviewer_code_revision='f'*40,
        authority_scope='advisory',review_test_version=events.ORACLE,review_run_id='temporary-source-conflict',
        certified_at=now.isoformat(),last_revalidated=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    row.update(changes.pop('row',{}))
    return _review(row,result.execution_bytes,result.peer_execution_bytes,source_revision=SOURCE,
        runtime_image_id=IMAGE,reviewer_code_revision='f'*40,now=now,**changes)


def test_actual_original_chain_pure_admission_no_signing(runtime):
    assert recompute(collect(runtime)) is True


@pytest.mark.parametrize('field,value',[
    ('verifier','a19'),('authority_scope','executor'),('source_revision','b'*40),
    ('reviewer_code_revision','b'*40),('test_version','borrowed'),('review_test_version','borrowed'),
    ('certified_at','2000-01-01T00:00:00+00:00'),('expires_at','2000-01-01T00:00:00+00:00')])
def test_original_admission_rejects_authority_source_or_time_drift(runtime,field,value):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    result=collect(runtime)
    with pytest.raises(CertificationReviewError):recompute(result,row={field:value})


def test_cloud_binding_cannot_replace_original_four_tasks(runtime):
    from scripts.agent_cert_reviewed_signing import CertificationReviewError
    with pytest.raises(CertificationReviewError,match='CONFLICT_CLOUD_TRANSPORT_FORBIDDEN'):
        recompute(collect(runtime),cloud_binding={'claimed':'PASS'})


@pytest.mark.parametrize('fault',['actor_vote','copied_hash','quality_label','health','execution','omit_peer','wrong_math'])
def test_actual_wrong_reconciliation_rejected_by_independent_source_oracle(runtime,monkeypatch,fault):
    original=events.producer_result
    def wrong(which,**kwargs):
        raw=original(which,**kwargs)
        if which!='reconciliation':return raw
        value=json.loads(raw);out=value['result'];inputs=json.loads(kwargs['input_raw'])['peer_sources']
        if fault=='actor_vote':out['selected_peer_task_id']=inputs[0]['task_id']
        elif fault=='copied_hash':out['selected_source_id']='CF-LEGACY'
        elif fault=='quality_label':out['selection_basis']='HIGH_QUALITY_PEER_STATUS'
        elif fault=='health':out['continuous_health']='HEALTHY'
        elif fault=='execution':value['execution']='PERFORMED'
        elif fault=='omit_peer':out['preserved_recommendations'].pop()
        else:out['failure_basis_points']=0
        return events.canonical(value)
    monkeypatch.setattr(events,'producer_result',wrong)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE'
    assert len([path for method,path in runtime.requests if method=='POST'])==3
    assert runtime.ledger.status()['persisted']==24


@pytest.mark.parametrize('fault',['producer_classifier','report_builder'])
def test_final_original_consumer_does_not_trust_producer_helpers(runtime,monkeypatch,fault):
    if fault=='producer_classifier':
        original=events._source_assessment
        def wrong(source):
            value=original(source)
            if value['supported']:value['failure_basis_points']=0
            return value
        monkeypatch.setattr(events,'_source_assessment',wrong)
    else:
        original=events._review_report
        def wrong(*args):return dict(original(*args),certification='L7')
        monkeypatch.setattr(events,'_review_report',wrong)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE'
    assert len([path for method,path in runtime.requests if method=='POST'])==(2 if fault=='producer_classifier' else 4)


@pytest.mark.parametrize('mutation',['peer_task','peer_origin','source_bytes','original_actions','request_hash',
    'runtime','future','peer_report','peer_owner','peer_objective','contribution_only'])
def test_original_four_task_join_rejects_mutation(runtime,mutation):
    result=collect(runtime)
    execution=json.loads(result.execution_bytes);peer=json.loads(result.peer_execution_bytes)
    first=execution['peer_executions'][0]
    if mutation=='peer_task':first['dispatch']['task_id']=execution['dispatch']['task_id']
    elif mutation=='peer_origin':execution['peer_executions'].reverse()
    elif mutation=='source_bytes':first['input_content_utf8']=execution['peer_executions'][1]['input_content_utf8']
    elif mutation=='original_actions':first['original_action_records'][0]=first['original_action_records'][1]
    elif mutation=='request_hash':execution['submitted_request_sha256']='a'*64
    elif mutation=='runtime':execution['runtime']['source_revision']='b'*40
    elif mutation=='future':execution['observation']['completed_at']='2099-01-01T00:00:00+00:00'
    elif mutation=='peer_report':peer['artifact_content_utf8']=peer['artifact_content_utf8'].replace('UNVERIFIED','L7')
    elif mutation=='peer_owner':peer['dispatch']['agent_id']='a19'
    elif mutation=='peer_objective':peer['objective_read'][1]['execution_metadata']['jobs']=[{'borrowed':True}]
    else:execution=first
    with pytest.raises(ValueError):events.validate_reviewed_conflict(execution,peer,source_revision=SOURCE,
        runtime_image_id=IMAGE,registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


@pytest.mark.parametrize('which',['first_peer','second_peer','subject'])
def test_original_reviewer_rereads_each_domain_twice(runtime,monkeypatch,which):
    original=events.reread_original;counts={}
    def changed(root,execution,**kwargs):
        key=execution['dispatch']['task_id'];counts[key]=counts.get(key,0)+1
        target={'first_peer':'code_proposal','second_peer':'fixture_finding','subject':'reconciliation'}[which]
        phase=execution['dispatch']['conflict_event']['phase']
        # Peers were already reread twice during reconciliation; review reads
        # them twice again. The subject is reread twice only by A26.
        if phase==target and counts[key]==(4 if which!='subject' else 2):
            raise events.ConflictEventError('CONFLICT_ORIGINAL_ARTIFACT_CHANGED')
        return original(root,execution,**kwargs)
    monkeypatch.setattr(events,'reread_original',changed)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE'
    assert len([path for method,path in runtime.requests if method=='POST'])==4
    assert runtime.ledger.status()['persisted']==24


@pytest.mark.parametrize('domain',['input','result','objective','ledger'])
def test_actual_original_domain_change_between_review_reads_is_rejected(runtime,monkeypatch,domain):
    import sqlite3
    original=events.reread_original;mutated=[]
    def change_after_first_subject_read(root,execution,**kwargs):
        checked=original(root,execution,**kwargs)
        if execution['dispatch']['conflict_event']['phase']=='reconciliation' and not mutated:
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
    monkeypatch.setattr(events,'reread_original',change_after_first_subject_read)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and mutated==[domain]
    assert len([path for method,path in runtime.requests if method=='POST'])==4
    rows=[json.loads(line) for line in (runtime.root/'action-records.jsonl').read_text().splitlines()]
    assert len(rows)==(25 if domain=='ledger' else 24)
    assert all(row['agent_id']!='a26' for row in rows)


@pytest.mark.parametrize('mutation',['copied_origin','wrong_math','peer_task','source','future'])
def test_actual_authenticated_a26_rejects_changed_originals_without_peer_writes(runtime,mutation):
    import uuid
    result=collect(runtime);execution=json.loads(result.execution_bytes)
    if mutation=='copied_origin':execution['peer_executions'].reverse()
    elif mutation=='wrong_math':
        value=json.loads(execution['artifact_content_utf8']);value['result']['failure_basis_points']=0
        execution['artifact_content_utf8']=events.canonical(value).decode()
    elif mutation=='peer_task':execution['peer_executions'][0]['dispatch']['task_id']=execution['dispatch']['task_id']
    elif mutation=='source':execution['runtime']['source_revision']='b'*40
    else:execution['observation']['completed_at']='2099-01-01T00:00:00+00:00'
    request=events.phase_request('review',execution=execution,nonce=str(uuid.uuid4()))
    before=(runtime.root/'action-records.jsonl').read_bytes()
    artifacts={path.name for path in (runtime.root/'artifacts').iterdir()}
    reply=runtime.client.post('/api/agents/objectives',json=request,headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code==202 and reply.json()['steps'][0]['state']=='blocked',reply.json()
    actual=runtime.client.get('/api/agents/objectives/'+reply.json()['id'],headers={'Authorization':'Bearer '+TOKEN}).json()
    assert actual['state']=='COMPLETED_WITH_FAILURES' and actual['execution_metadata']['jobs']==[]
    assert (runtime.root/'action-records.jsonl').read_bytes()==before
    assert {path.name for path in (runtime.root/'artifacts').iterdir()}==artifacts


def test_actual_delayed_durable_writer_uses_shared_original_five_seconds(runtime,monkeypatch):
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


def test_actual_failed_writer_never_passes_case(runtime,monkeypatch):
    from types import SimpleNamespace
    from app import action_records
    def failed(fd):raise OSError('controlled disposable writer failure')
    monkeypatch.setattr(action_records,'os',SimpleNamespace(fsync=failed))
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and len([p for m,p in runtime.requests if m=='POST'])==1
    assert runtime.ledger.status()['dropped']==6
    assert runtime.ledger.close() is False
    monkeypatch.setattr(runtime.ledger,'close',lambda:True)


def test_exhausted_original_shared_budget_no_flush_or_peer(runtime,monkeypatch):
    from types import SimpleNamespace
    samples=iter([0.0,6.0]);flushes=[]
    monkeypatch.setattr(events,'time',SimpleNamespace(monotonic=lambda:next(samples,6.0)))
    original=runtime.ledger.flush
    def flush(*args,**kwargs):flushes.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(runtime.ledger,'flush',flush)
    result=collect(runtime)
    assert result.summary['state']=='INCOMPLETE' and flushes==[]
    assert len([p for m,p in runtime.requests if m=='POST'])==1


def test_original_78354_byte_execution_uses_compact_review_with_unchanged_cap():
    from pathlib import Path
    import hashlib
    raw=(Path(__file__).parent/'fixtures/conflict-source-execution-78354.json').read_bytes()
    assert len(raw)==78354 and hashlib.sha256(raw).hexdigest()=='1c4f2b99e613773ec94cdc8b13efc94ed31b044a82cd1ee5c0b5b3f9c3629e09'
    execution=json.loads(raw)
    request=events.phase_request('review',execution=execution,nonce=NONCE)
    context=json.loads(request['context'])
    assert context['execution']==execution
    assert context['expected_execution_sha256']==hashlib.sha256(raw).hexdigest()
    assert context['fixed_challenge_sha256']==events.sha(events.challenge_bytes())
    assert len(request['context'].encode())<=80000
    operator=ConflictPhaseOperatorIO(owner_token=TOKEN,which='review',execution=execution,
        nonce=NONCE,expected_source_revision=SOURCE,expected_runtime_image=IMAGE)
    assert operator._submitted_request==request  # Constructor only: no authentication/network.
    execution['oversized_transport']='x'*80000
    with pytest.raises(events.ConflictEventError,match='CONFLICT_CONTEXT_BOUND'):
        events.phase_request('review',execution=execution,nonce=NONCE)


@pytest.mark.parametrize('family',['conflict','cross_agent_conflict'])
def test_actual_four_objectives_with_full_source_domain_identity(runtime,monkeypatch,family):
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID','SOURCE_DOMAIN_8c7130c9-340d-4aa0-865c-06149f3491f7')
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_VERSION','SOURCE_QUALIFICATION')
    if family=='conflict':result=collect(runtime)
    else:
        from tests.test_agent_cert_cross_agent_conflict import collect as collect_cross
        result=collect_cross(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    assert result.summary['submission_attempts']==4
    assert len([path for method,path in runtime.requests if method=='POST'])==4


@pytest.mark.parametrize('fault',['foreign_hash','missing_hash'])
def test_compact_challenge_drift_rejected_before_original_review_writes(runtime,fault):
    result=collect(runtime)
    assert result.summary['state']=='UNSIGNED_EVENT_EVIDENCE',result.summary
    request=events.phase_request('review',execution=json.loads(result.execution_bytes),nonce=NONCE)
    context=json.loads(request['context'])
    if fault=='foreign_hash':context['fixed_challenge_sha256']='0'*64
    else:context.pop('fixed_challenge_sha256')
    request['context']=events.canonical(context).decode()
    before=runtime.ledger.status()['persisted']
    artifacts=set((runtime.root/'artifacts').rglob('*'))
    reply=runtime.client.post('/api/agents/objectives',json=request,
        headers={'Authorization':'Bearer '+TOKEN})
    assert reply.status_code==202 and reply.json()['steps'][0]['state']=='blocked'
    assert runtime.ledger.status()['persisted']==before
    assert set((runtime.root/'artifacts').rglob('*'))==artifacts
    assert not any(json.loads(line).get('task_id')==reply.json()['id']
        for line in (runtime.root/'action-records.jsonl').read_text().splitlines())
