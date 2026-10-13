"""Actual disposable PWA role boundary; no production Owner or L7 evidence."""
from datetime import datetime,timezone
import hashlib,json,sqlite3,time,uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import owner_referrals as referrals,pwa_sessions as pwa

ORIGIN='https://192.168.1.23:8443'
LOCAL='http://127.0.0.1:8000'
TOKEN='owner-referral-disposable-fixture-bearer'
HEADERS={'Origin':ORIGIN,'X-Jarvis-PWA':'1'}

@pytest.fixture
def domain(tmp_path,monkeypatch):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path));monkeypatch.setenv('PRIME_SPINE_TOKEN',TOKEN)
    monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN);monkeypatch.setenv('PRIME_PWA_OWNER_ORIGIN',LOCAL)
    monkeypatch.setenv('PRIME_PWA_OWNER_ACCOUNT_ID','public-source-fixture-owner')
    app=FastAPI();app.include_router(pwa.router);app.include_router(pwa.owner_router);app.include_router(referrals.router)
    app.add_middleware(pwa.PWASessionMiddleware)
    local=TestClient(app,base_url=LOCAL,client=('127.0.0.1',50000))
    def enroll(role):
        result=local.post('/pwa/owner/pairing',headers={'Authorization':'Bearer '+TOKEN,'Origin':LOCAL,'X-Jarvis-PWA':'1'},json={'role':role})
        assert result.status_code==200,result.text
        client=TestClient(app,base_url=ORIGIN)
        response=client.post('/pwa/api/enroll',headers=HEADERS,json={'code':result.json()['code']})
        assert response.status_code==200,response.text
        return client
    store=referrals.OwnerReferralStore(tmp_path)
    proposal=store.propose(task_id=str(uuid.uuid4()),source_revision='a'*40,registry_sha256='b'*64,
        runtime={'host_id':'source-owner-domain','source_revision':'a'*40,'version':'source-test','image_digest':'sha256:'+'c'*64},
        created_at=datetime.now(timezone.utc).isoformat(),deadline=time.monotonic()+5)
    yield tmp_path,store,proposal,enroll,app
    local.close()

def url(value):return '/pwa/api/owner-referrals/'+value['proposal']['referral_id']


@pytest.mark.parametrize('database',['owner-referrals.db','pwa-sessions.db'])
@pytest.mark.parametrize('defect',['oversized','redirected','aggregate'])
def test_native_original_shm_sidecar_rejected_before_sqlite_read(domain,database,defect):
    import os,subprocess
    root,store,proposal,enroll,app=domain
    owner=enroll('OWNER')
    assert owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={}).status_code==200
    sidecar=root/(database+'-shm');target=root/('outside-'+database);target.mkdir()
    assert not sidecar.exists()
    if defect in ('oversized','aggregate'):
        with sidecar.open('wb') as stream:stream.truncate(referrals.MAX_DB_BYTES+1 if defect=='oversized'
            else referrals.MAX_DB_BYTES-(root/database).stat().st_size+1)
    elif os.name=='nt':
        result=subprocess.run(['cmd','/c','mklink','/J',str(sidecar),str(target)],capture_output=True)
        assert result.returncode==0,'Disposable native junction creation failed'
    else:sidecar.symlink_to(target,target_is_directory=True)
    before=(root/'owner-referrals.db').read_bytes()
    try:
        with pytest.raises(ValueError):
            store.verified_original(proposal['proposal']['referral_id'],deadline=time.monotonic()+5)
        assert (root/'owner-referrals.db').read_bytes()==before
    finally:
        if defect=='redirected' and os.name=='nt':os.rmdir(sidecar)
        else:sidecar.unlink()

def test_real_server_issued_owner_referral_ack_never_grants_approval(domain):
    root,store,proposal,enroll,app=domain;owner=enroll('OWNER')
    read=owner.get(url(proposal),headers=HEADERS);assert read.status_code==200 and read.json()==proposal
    ack=owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={})
    assert ack.status_code==200,ack.text
    value=store.verified_original(proposal['proposal']['referral_id'],deadline=time.monotonic()+5)
    assert value==ack.json() and value['state']=='ACKNOWLEDGED_NOT_APPROVED'
    assert value['acknowledgment']['approval']=='NOT_GRANTED' and value['execution_authority']=='NONE'
    again=owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={});assert again.json()==value
    assert value['acknowledgment']['proposal_sha256']==proposal['proposal_sha256']
    assert not (root/'prime-spine.db').exists()


@pytest.mark.parametrize('defect',['missing','foreign'])
def test_configured_owner_address_cannot_be_dropped_or_changed_before_ack(domain,defect):
    root,store,proposal,enroll,app=domain;owner=enroll('OWNER')
    with sqlite3.connect(root/'owner-referrals.db') as db:
        value=proposal['proposal'].copy();value['owner_account_address']=None if defect=='missing' else 'foreign-owner'
        db.execute('UPDATE owner_referrals SET proposal_json=?',(referrals.canonical(value).decode(),))
    before=(root/'owner-referrals.db').read_bytes()
    reply=owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={})
    assert reply.status_code==422
    assert (root/'owner-referrals.db').read_bytes()==before

@pytest.mark.parametrize('kind',['member','anonymous','bearer_only','foreign_origin','approval_body','foreign_referral'])
def test_actual_owner_boundary_rejects_invalid_ack_without_store_write(domain,kind):
    root,store,proposal,enroll,app=domain
    client=enroll('MEMBER' if kind=='member' else 'OWNER');headers=dict(HEADERS);body={};path=url(proposal)+'/acknowledge'
    if kind in ('anonymous','bearer_only'):client.cookies.clear()
    if kind=='bearer_only':headers['Authorization']='Bearer '+TOKEN
    if kind=='foreign_origin':headers['Origin']='https://evil.invalid'
    if kind=='approval_body':body={'approval':'APPROVED','role':'OWNER'}
    if kind=='foreign_referral':path='/pwa/api/owner-referrals/'+str(uuid.uuid4())+'/acknowledge'
    before=(root/'owner-referrals.db').read_bytes()
    response=client.post(path,headers=headers,json=body)
    assert response.status_code in (401,403,422)
    assert (root/'owner-referrals.db').read_bytes()==before
    assert store.read(proposal['proposal']['referral_id'],deadline=time.monotonic()+5)['state']=='PENDING_OWNER_ACK'

@pytest.mark.parametrize('mutation',['revoked','role','expiry','expiry_extension','account','proposal','ack'])
def test_ack_original_session_and_referral_drift_is_rejected(domain,mutation):
    root,store,proposal,enroll,app=domain;owner=enroll('OWNER')
    response=owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={});assert response.status_code==200
    if mutation in ('proposal','ack'):
        with sqlite3.connect(root/'owner-referrals.db') as db:
            field='proposal_json' if mutation=='proposal' else 'acknowledgment_json'
            raw=db.execute('SELECT '+field+' FROM owner_referrals').fetchone()[0];value=json.loads(raw)
            value['approval']='APPROVED';db.execute('UPDATE owner_referrals SET '+field+'=?',(json.dumps(value),))
    else:
        with sqlite3.connect(root/'pwa-sessions.db') as db:
            field,value={'revoked':('revoked',1),'role':('role','MEMBER'),'expiry':('expires',time.time()-1),
                'expiry_extension':('expires',time.time()+999999),'account':('owner_account_id','foreign-owner')}[mutation]
            db.execute('UPDATE sessions SET '+field+'=?',(value,))
    with pytest.raises(referrals.ReferralError):store.verified_original(proposal['proposal']['referral_id'],deadline=time.monotonic()+5)

@pytest.mark.parametrize('mutation',['task_replay','foreign_account','oversized_db','expired_deadline'])
def test_native_proposal_and_original_domain_bounds(domain,mutation):
    root,store,proposal,enroll,app=domain
    if mutation=='task_replay':
        with pytest.raises(referrals.ReferralError):store.propose(task_id=proposal['proposal']['task_id'],source_revision='a'*40,registry_sha256='b'*64,
            runtime=proposal['proposal']['runtime'],created_at=datetime.now(timezone.utc).isoformat(),deadline=time.monotonic()+5)
    elif mutation=='foreign_account':
        owner=enroll('OWNER')
        with sqlite3.connect(root/'pwa-sessions.db') as db:db.execute('UPDATE sessions SET owner_account_id=?',('foreign-owner',))
        assert owner.post(url(proposal)+'/acknowledge',headers=HEADERS,json={}).status_code==422
    elif mutation=='oversized_db':
        with (root/'owner-referrals.db').open('ab') as f:f.write(b'0'*(referrals.MAX_DB_BYTES+1))
        with pytest.raises(referrals.ReferralError):store.read(proposal['proposal']['referral_id'],deadline=time.monotonic()+5)
    else:
        with pytest.raises(referrals.ReferralError):store.read(proposal['proposal']['referral_id'],deadline=time.monotonic()-1)
