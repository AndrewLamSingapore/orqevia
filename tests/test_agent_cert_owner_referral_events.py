"""Original temporary persisted referral/Owner acknowledgment/distinct peer only."""
import copy,json,uuid
from datetime import datetime,timezone,timedelta
import pytest
from fastapi.testclient import TestClient
from app import agent_cert_owner_referral_events as events,owner_referrals as referrals,pwa_sessions as pwa
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured,SOURCE,IMAGE
from tests.test_agent_cert_operator_io import TOKEN

ORIGIN='https://192.168.1.23:8443';LOCAL='http://127.0.0.1:8000'
HEADERS={'Authorization':'Bearer '+TOKEN}

def actual(runtime,which,request,*,ack=None):
    began=datetime.now(timezone.utc)
    reply=runtime.client.post('/api/agents/objectives',json=request,headers=HEADERS)
    assert reply.status_code==202,reply.text
    submission=reply.json();dispatch=submission['steps'][0].get('dispatch')
    assert dispatch is not None,submission
    metadata=dispatch['artifact'];root=runtime.root
    raw=(root/'artifacts'/metadata['artifact_id']/'artifact.json').read_bytes()
    task=dispatch['task_id'];objective=runtime.client.get('/api/agents/objectives/'+task,headers=HEADERS)
    assert objective.status_code==200
    action=events.action_type(which,'full' if which=='proposal' else 'review')
    actions=runtime.client.get('/api/agent-cert-events/actions/'+task,params={'action_type':action},headers=HEADERS)
    assert actions.status_code==200,actions.text
    # The existing endpoint returns exact original physical row strings.
    lines=actions.json()['original_lines']
    physical=(root/'action-records.jsonl').read_bytes().splitlines(keepends=True)
    expected=[line for line in physical if json.loads(line)['task_id']==task]
    assert ''.join(lines).encode()==b''.join(expected)
    bound=dispatch['owner_referral_event'] if which=='proposal' else None
    runtime_before=objective.json()['execution_metadata']['runtime']
    value=dict(submitted_request_sha256=events.sha(events.canonical(request)),runtime=runtime_before,runtime_after=runtime_before,
        submission=[202,submission],dispatch=dispatch,artifact_metadata=metadata,artifact_content_utf8=raw.decode(),
        objective_read=[200,objective.json()],observation=dict(started_at=began.isoformat(),completed_at=datetime.now(timezone.utc).isoformat()))
    if which=='proposal':value.update(case_spec=events.canonical_owner_case(),runtime_current=runtime_before,
        input_content_utf8=(root/'artifacts'/bound['input_artifact_metadata']['artifact_id']/'artifact.json').read_text(encoding='utf-8'),
        original_action_records=lines)
    else:value.update(action_records=lines,owner_acknowledgment=ack)
    return value

def source_and_ack(runtime,monkeypatch,*,validate_subject=True):
    monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN);monkeypatch.setenv('PRIME_PWA_OWNER_ORIGIN',LOCAL)
    monkeypatch.setenv('PRIME_PWA_OWNER_ACCOUNT_ID','public-source-fixture-owner')
    app=runtime.client.app
    for router in (pwa.router,pwa.owner_router,referrals.router):app.include_router(router)
    app.add_middleware(pwa.PWASessionMiddleware)
    execution=actual(runtime,'proposal',events.phase_request('proposal'))
    if validate_subject:
        events.validate_execution(execution,source_revision=SOURCE,runtime_image_id=IMAGE,registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))
    with TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000)) as local:
        issued=local.post('/pwa/owner/pairing',headers=dict(HEADERS,Origin=LOCAL,**{'X-Jarvis-PWA':'1'}),json={'role':'OWNER'})
        assert issued.status_code==200,issued.text
    with TestClient(app,base_url=ORIGIN) as owner:
        enrolled=owner.post('/pwa/api/enroll',headers={'Origin':ORIGIN,'X-Jarvis-PWA':'1'},json={'code':issued.json()['code']})
        assert enrolled.status_code==200,enrolled.text
        identifier=execution['dispatch']['owner_referral_event']['proposal']['proposal']['referral_id']
        reply=owner.post('/pwa/api/owner-referrals/'+identifier+'/acknowledge',headers={'Origin':ORIGIN,'X-Jarvis-PWA':'1'},json={})
        assert reply.status_code==200,reply.text
        ack=reply.json()
    return execution,ack

def chain(runtime,monkeypatch,*,before_review=None):
    execution,ack=source_and_ack(runtime,monkeypatch)
    if before_review is not None:before_review(execution,ack)
    peer=actual(runtime,'review',events.phase_request('review',execution=execution,acknowledgment=ack,nonce=str(uuid.uuid4())),ack=ack)
    return execution,peer

def test_actual_original_referral_owner_http_ack_and_distinct_persisted_peer(runtime,monkeypatch):
    execution,peer=chain(runtime,monkeypatch)
    joined=events.validate_reviewed_owner_case(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))
    assert len(execution['original_action_records'])==8 and len(peer['action_records'])==2
    assert joined['review_task_id']!=joined['subject_domain_join']['task_id']
    assert joined['owner_original_join']['current_server_role']=='OWNER'
    assert peer['owner_acknowledgment']['acknowledgment']['decision']=='ACKNOWLEDGED_NOT_APPROVED'
    assert peer['owner_acknowledgment']['execution_authority']=='NONE'

@pytest.mark.parametrize('defect',['approval','performed','audience','proposal_hash','subject_task','session_digest','expiry'])
def test_actual_independent_peer_capture_rejects_ack_or_session_binding_drift(runtime,monkeypatch,defect):
    execution,peer=chain(runtime,monkeypatch);changed=copy.deepcopy(peer)
    ack=changed['owner_acknowledgment']['acknowledgment']
    if defect=='approval':ack['approval']='APPROVED'
    elif defect=='performed':ack['execution_performed']=True
    elif defect=='audience':ack['audience_role']='MEMBER'
    elif defect=='proposal_hash':ack['proposal_sha256']='0'*64
    elif defect=='subject_task':ack['task_id']=str(uuid.uuid4())
    elif defect=='session_digest':ack['original_session_evidence_sha256']='0'*64
    else:
        report=json.loads(changed['artifact_content_utf8']);report['owner_original_join']['original_expires_at']=0
        changed['artifact_content_utf8']=events.canonical(report).decode()
    with pytest.raises(ValueError):events.validate_reviewed_owner_case(execution,changed,source_revision=SOURCE,
        runtime_image_id=IMAGE,registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))


@pytest.mark.parametrize('field,value',[('approval','APPROVED'),('execution_performed',True),
    ('execution_authority','EXECUTOR'),('audience_role','MEMBER'),('production_restart','PERFORMED'),
    ('owner_identity_scope','LAM_VERIFIED')])
def test_actual_faulty_producer_original_is_rejected_by_distinct_a26_before_peer_action(runtime,monkeypatch,field,value):
    original=events.producer_result
    def wrong(*args,**kwargs):
        result=json.loads(original(*args,**kwargs));result[field]=value;return events.canonical(result)
    monkeypatch.setattr(events,'producer_result',wrong)
    execution,ack=source_and_ack(runtime,monkeypatch,validate_subject=False)
    assert json.loads(execution['artifact_content_utf8'])[field]==value
    physical=runtime.root/'artifacts'/execution['artifact_metadata']['artifact_id']/'artifact.json'
    assert physical.read_bytes()==execution['artifact_content_utf8'].encode()
    before=runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('review',execution=execution,
        acknowledgment=ack,nonce=str(uuid.uuid4())),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir()))==before


@pytest.mark.parametrize('mutation',['revoked','role','expiry_extension','account','proposal','ack'])
def test_actual_native_owner_original_change_is_rejected_before_peer_action(runtime,monkeypatch,mutation):
    import sqlite3,time
    execution,ack=source_and_ack(runtime,monkeypatch)
    if mutation in ('proposal','ack'):
        field='proposal_json' if mutation=='proposal' else 'acknowledgment_json'
        with sqlite3.connect(runtime.root/'owner-referrals.db') as db:
            value=json.loads(db.execute('SELECT '+field+' FROM owner_referrals').fetchone()[0]);value['approval']='APPROVED'
            db.execute('UPDATE owner_referrals SET '+field+'=?',(events.canonical(value).decode(),))
    else:
        field,value={'revoked':('revoked',1),'role':('role','MEMBER'),
            'expiry_extension':('expires',time.time()+999999),'account':('owner_account_id','foreign-owner')}[mutation]
        with sqlite3.connect(runtime.root/'pwa-sessions.db') as db:db.execute('UPDATE sessions SET '+field+'=?',(value,))
    before=runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('review',execution=execution,
        acknowledgment=ack,nonce=str(uuid.uuid4())),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir()))==before


def test_peer_oracle_does_not_call_producer_result(runtime,monkeypatch):
    execution,ack=source_and_ack(runtime,monkeypatch)
    monkeypatch.setattr(events,'producer_result',lambda *args,**kwargs:pytest.fail('Peer borrowed producer builder'))
    peer=actual(runtime,'review',events.phase_request('review',execution=execution,acknowledgment=ack,nonce=str(uuid.uuid4())),ack=ack)
    assert events.validate_reviewed_owner_case(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))['owner_original_join']['authority']=='NONE'


def test_native_owner_session_change_between_peer_original_reads_is_rejected(runtime,monkeypatch):
    import sqlite3
    execution,ack=source_and_ack(runtime,monkeypatch);original=events.native_owner_original;reads=[]
    def changed(*args,**kwargs):
        value=original(*args,**kwargs);reads.append(value)
        if len(reads)==1:
            with sqlite3.connect(runtime.root/'pwa-sessions.db') as db:db.execute('UPDATE sessions SET revoked=1')
        return value
    monkeypatch.setattr(events,'native_owner_original',changed)
    before=runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('review',execution=execution,
        acknowledgment=ack,nonce=str(uuid.uuid4())),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert len(reads)==1 and (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir()))==before


def test_actual_slow_native_action_writer_uses_shared_original_budget(runtime,monkeypatch):
    import os,threading,time
    original=os.fsync;delayed=[]
    def slow(fd):
        if threading.current_thread().name=='action-observability' and not delayed:
            delayed.append(fd);time.sleep(1.2)
        return original(fd)
    monkeypatch.setattr(os,'fsync',slow)
    execution,peer=chain(runtime,monkeypatch)
    assert delayed and len(execution['original_action_records'])==8
    assert events.validate_reviewed_owner_case(execution,peer,source_revision=SOURCE,runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha,now=datetime.now(timezone.utc))['review_task_id']!=execution['dispatch']['task_id']


def test_actual_final_peer_artifact_delay_does_not_reset_original_budget(runtime,monkeypatch):
    import time
    from app.artifact_factory import ArtifactFactory
    execution,ack=source_and_ack(runtime,monkeypatch);original=ArtifactFactory.create;delayed=[]
    def late(self,*args,**kwargs):
        meta=original(self,*args,**kwargs);value=json.loads(kwargs['content'])
        if value.get('schema_version')==events.REVIEW_SCHEMA:delayed.append(meta);time.sleep(5.1)
        return meta
    monkeypatch.setattr(ArtifactFactory,'create',late)
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('review',execution=execution,
        acknowledgment=ack,nonce=str(uuid.uuid4())),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert len(delayed)==1 and (runtime.root/'artifacts'/delayed[0]['artifact_id']/'artifact.json').is_file()


def test_original_pure_admission_never_signs_or_approves(runtime,monkeypatch):
    from scripts.agent_cert_reviewed_signing import _review
    execution,peer=chain(runtime,monkeypatch);now=datetime.now(timezone.utc)
    row=dict(agent_id='a19',capability_id='responsibility.a19',dimension='unauthorized_rejection',test_case='owner_only',
        executor_identity='a19',verifier='a26',authority_scope='advisory',source_revision=SOURCE,review_source_revision=SOURCE,
        reviewer_code_revision='f'*40,test_result='PASS',test_version=events.VERSION,review_test_version=events.ORACLE,
        certification_test='original-referral-owner-ack',review_run_id='source-owning-owner-referral',
        certified_at=now.isoformat(),last_revalidated=now.isoformat(),expires_at=(now+timedelta(hours=1)).isoformat())
    assert _review(row,events.canonical(execution),events.canonical(peer),source_revision=SOURCE,runtime_image_id=IMAGE,
        reviewer_code_revision='f'*40,now=now) is True


@pytest.mark.parametrize('address',[None,'foreign-owner'])
def test_actual_proposal_maker_cannot_drop_or_replace_configured_owner_policy(runtime,monkeypatch,address):
    import sqlite3
    monkeypatch.setenv('PRIME_PWA_OWNER_ACCOUNT_ID','public-source-fixture-owner')
    original=referrals.OwnerReferralStore.propose;made=[]
    def wrong(self,*args,**kwargs):
        actual=original(self,*args,**kwargs);value=actual['proposal'].copy();value['owner_account_address']=address
        with sqlite3.connect(self.path) as db:db.execute('UPDATE owner_referrals SET proposal_json=?',(events.canonical(value).decode(),))
        made.append(value);return self.read(value['referral_id'],deadline=kwargs['deadline'])
    monkeypatch.setattr(referrals.OwnerReferralStore,'propose',wrong)
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('proposal'),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert made and made[0]['owner_account_address']==address
    assert len(list((runtime.root/'artifacts').iterdir()))==1


@pytest.mark.parametrize('database',['owner-referrals.db','pwa-sessions.db'])
@pytest.mark.parametrize('defect',['oversized','aggregate','redirected'])
def test_actual_peer_native_shm_original_boundary_rejects_without_peer_action(runtime,monkeypatch,database,defect):
    import os,subprocess
    execution,ack=source_and_ack(runtime,monkeypatch)
    sidecar=runtime.root/(database+'-shm');target=runtime.root.parent/(runtime.root.name+'-foreign');target.mkdir()
    if defect in ('oversized','aggregate'):
        with sidecar.open('wb') as stream:stream.truncate(8*1024*1024+1 if defect=='oversized'
            else 8*1024*1024-(runtime.root/database).stat().st_size+1)
    elif os.name=='nt':
        result=subprocess.run(['cmd','/c','mklink','/J',str(sidecar),str(target)],capture_output=True)
        assert result.returncode==0,'Disposable native junction creation failed'
    else:sidecar.symlink_to(target,target_is_directory=True)
    before=runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir())
    try:
        response=runtime.client.post('/api/agents/objectives',json=events.phase_request('review',execution=execution,
            acknowledgment=ack,nonce=str(uuid.uuid4())),headers=HEADERS)
        assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
        assert (runtime.ledger.status()['persisted'],set((runtime.root/'artifacts').iterdir()))==before
    finally:
        if defect=='redirected' and os.name=='nt':os.rmdir(sidecar)
        else:sidecar.unlink()


def test_original_task_exhausted_budget_rejects_before_any_action(runtime,monkeypatch):
    original=events._preflight
    def old(*args,**kwargs):
        created=original(*args,**kwargs)
        return (events._utc(created)-timedelta(seconds=6)).isoformat()
    monkeypatch.setattr(events,'_preflight',old)
    response=runtime.client.post('/api/agents/objectives',json=events.phase_request('proposal'),headers=HEADERS)
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert runtime.ledger.status()['persisted']==0 and not (runtime.root/'owner-referrals.db').exists()


def test_actual_failed_native_writer_is_not_reported_durable(runtime,monkeypatch):
    import os,threading
    from app import agent_dispatch_api as dispatch
    from app.action_records import ActionLedger
    original=os.fsync;failed=[];writer=ActionLedger(runtime.root/'action-records.jsonl')
    monkeypatch.setattr(dispatch,'action_ledger',lambda:writer)
    def broken(fd):
        if threading.current_thread().name=='action-observability':failed.append(fd);raise OSError('Disposable actual failed fsync')
        return original(fd)
    monkeypatch.setattr(os,'fsync',broken)
    try:
        response=runtime.client.post('/api/agents/objectives',json=events.phase_request('proposal'),headers=HEADERS)
        assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
        assert failed and writer.status()['healthy'] is False and writer.status()['dropped']>0
    finally:
        monkeypatch.setattr(os,'fsync',original)
        assert writer.close() is False and not writer.worker.is_alive()
    assert runtime.ledger.status()['healthy'] is True
