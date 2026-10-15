import hashlib
import json
import secrets
import time
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

ORIGIN='https://192.168.1.23:8443'
PUBLIC_ORIGIN='https://jarvis.lamjarvis.com'
HEADERS={'Origin':ORIGIN,'X-Jarvis-PWA':'1'}

@pytest.fixture
def setup(monkeypatch,tmp_path):
    root=tmp_path/'pwa-fixture';root.mkdir()
    monkeypatch.setenv('PRIME_DATA_DIR',str(root));monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN)
    monkeypatch.delenv('PRIME_PWA_ADDITIONAL_ORIGINS',raising=False)
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-owner-credential-never-production')
    from app import pwa_sessions as pwa,interface_contract,interface_node
    app=FastAPI();app.include_router(pwa.router);app.include_router(pwa.owner_router);app.include_router(interface_contract.router)
    @app.get('/pwa/',response_class=HTMLResponse)
    @app.get('/pwa/index.html',response_class=HTMLResponse)
    def pwa_shell():return '<!doctype html><title>JARVIS</title>'
    app.add_middleware(pwa.PWASessionMiddleware)
    return root,pwa,app,interface_node

def enroll(pwa,client):
    code=secrets.token_urlsafe(16)
    with pwa.database() as db:db.execute('INSERT INTO pairing(code_hash,expires,used) VALUES(?,?,0)',(pwa.digest(code),time.time()+300))
    response=client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code})
    assert response.status_code==200
    return response,code

def test_cookie_flags_hash_storage_replay_logout(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        response,code=enroll(pwa,client)
        cookie=response.headers['set-cookie'];assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
        assert 'Domain=' not in cookie and 'Max-Age=28800' in cookie
        assert client.get('/pwa/api/session').json()['authenticated']
        rawcookie=client.cookies.get(pwa.COOKIE)
        with pwa.database() as db:
            assert db.execute('SELECT session_hash FROM sessions').fetchone()[0]==pwa.digest(rawcookie)
            assert db.execute('SELECT code_hash FROM pairing').fetchone()[0]==pwa.digest(code)
        assert client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code}).status_code==401
        assert client.post('/pwa/api/logout',headers=HEADERS).status_code==200
        client.cookies.set(pwa.COOKIE,rawcookie)
        assert not client.get('/pwa/api/session').json()['authenticated']

def test_csrf_host_spoof_and_caller_identity_rejected(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enroll(pwa,client)
        assert client.post('/pwa/api/logout').status_code==403
        assert client.post('/pwa/api/logout',headers={**HEADERS,'Origin':'https://evil.invalid'}).status_code==403
        assert client.get('/pwa/api/session',headers={'Host':'evil.invalid'}).status_code==403
        assert client.get('/interface/v1/health',headers={'Authorization':'Bearer spoof'}).status_code==400
        assert client.get('/interface/v1/health',headers={'X-Jarvis-Client-Id':'dell:spoof'}).status_code==400

def test_exact_public_origin_opt_in_preserves_lan_and_authentication(setup,monkeypatch):
    root,pwa,app,node=setup
    public_headers={'Origin':PUBLIC_ORIGIN,'X-Jarvis-PWA':'1'}
    with TestClient(app,base_url=ORIGIN) as lan,TestClient(app,base_url=PUBLIC_ORIGIN) as public:
        assert lan.get('/pwa/').status_code==200
        assert public.get('/pwa/').status_code==403
        monkeypatch.setenv('PRIME_PWA_ADDITIONAL_ORIGINS',PUBLIC_ORIGIN)
        assert lan.get('/pwa/').status_code==200
        assert public.get('/pwa/').status_code==200
        navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        assert public.get('/pwa/',headers=navigation).status_code==200
        assert public.get('/pwa/api/session',headers=navigation).status_code==403
        assert public.get('/pwa/api/session').json()['authenticated'] is False
        assert public.get('/interface/v1/health').status_code==401
        code=secrets.token_urlsafe(16)
        with pwa.database() as db:db.execute('INSERT INTO pairing(code_hash,expires,used) VALUES(?,?,0)',(pwa.digest(code),time.time()+300))
        enrolled=public.post('/pwa/api/enroll',headers=public_headers,json={'code':code})
        assert enrolled.status_code==200 and enrolled.json()['role']=='MEMBER'
        assert 'Secure' in enrolled.headers['set-cookie'] and 'Domain=' not in enrolled.headers['set-cookie']
        assert public.get('/pwa/api/session').json()['authenticated'] is True
        assert public.get(ORIGIN+'/pwa/api/session').json()['authenticated'] is False
        assert lan.get('/pwa/api/session').json()['authenticated'] is False
        assert public.post('/pwa/api/owner-authority-check',headers=public_headers).status_code==403
        assert public.post('/pwa/api/logout',headers=public_headers).status_code==200
        assert public.get('/pwa/api/session').json()['authenticated'] is False
        enroll(pwa,lan)
        assert lan.get('/pwa/api/session').json()['authenticated'] is True


def test_public_origin_rejects_host_origin_csrf_proxy_and_identity_spoofs(setup,monkeypatch):
    root,pwa,app,node=setup
    monkeypatch.setenv('PRIME_PWA_ADDITIONAL_ORIGINS',PUBLIC_ORIGIN)
    public_headers={'Origin':PUBLIC_ORIGIN,'X-Jarvis-PWA':'1'}
    with TestClient(app,base_url=PUBLIC_ORIGIN) as public,TestClient(app,base_url=ORIGIN) as lan:
        assert public.get('/pwa/',headers={'Host':'evil.invalid'}).status_code==403
        assert public.get('/pwa/',headers={'Origin':ORIGIN}).status_code==403
        assert lan.get('/pwa/',headers={'Origin':PUBLIC_ORIGIN}).status_code==403
        assert public.post('/pwa/api/logout').status_code==403
        assert public.post('/pwa/api/logout',headers={'Origin':PUBLIC_ORIGIN}).status_code==403
        assert public.post('/pwa/api/logout',headers={**public_headers,'Origin':ORIGIN}).status_code==403
        assert public.post('/pwa/api/logout',headers={**public_headers,'X-Jarvis-PWA':'0'}).status_code==403
        assert public.get('/pwa/api/session',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert public.options('/pwa/api/session',headers=public_headers).status_code==405
        assert public.post('/pwa/api/uploads',headers={**public_headers,'X-Filename':'note.txt'},content=b'text').status_code==401
        code=secrets.token_urlsafe(16)
        with pwa.database() as db:db.execute('INSERT INTO pairing(code_hash,expires,used) VALUES(?,?,0)',(pwa.digest(code),time.time()+300))
        assert public.post('/pwa/api/enroll',headers=public_headers,json={'code':code}).status_code==200
        assert public.post('/pwa/api/logout').status_code==403
        assert public.post('/pwa/api/logout',headers={'Origin':PUBLIC_ORIGIN}).status_code==403
        assert public.get('/pwa/api/session').json()['authenticated'] is True
        assert public.get('/interface/v1/health',headers={'X-Jarvis-Client-Id':'dell:spoof'}).status_code==400
        assert public.get('/interface/v1/health',headers={'Authorization':'Bearer spoof'}).status_code==400
        assert public.get('/interface/v1/health',headers={'Origin':ORIGIN}).status_code==403
        assert public.post('/interface/v1/objectives',headers={'Origin':PUBLIC_ORIGIN},json={'objective':'Not dispatched'}).status_code==403
        assert public.get('/interface/v1/health',headers={'Host':'evil.invalid','X-Forwarded-Host':'jarvis.lamjarvis.com'}).status_code==403
    with TestClient(app,base_url='https://evil.invalid') as spoofed:
        assert spoofed.get('/pwa/',headers={'X-Forwarded-Host':'jarvis.lamjarvis.com'}).status_code==403
    with TestClient(app,base_url='http://jarvis.lamjarvis.com') as insecure:
        assert insecure.get('/pwa/',headers={'X-Forwarded-Proto':'https'}).status_code==403


@pytest.mark.parametrize('invalid',[
    'http://jarvis.lamjarvis.com','https://jarvis.lamjarvis.com/',
    'https://jarvis.lamjarvis.com:443','https://jarvis.lamjarvis.com.evil.invalid','https://*.lamjarvis.com',
    'https://jarvis.lamjarvis.com,https://evil.invalid',' https://jarvis.lamjarvis.com',
])
def test_invalid_additional_origin_configuration_fails_closed(setup,monkeypatch,invalid):
    root,pwa,app,node=setup
    monkeypatch.setenv('PRIME_PWA_ADDITIONAL_ORIGINS',invalid)
    with TestClient(app,base_url=ORIGIN) as lan,TestClient(app,base_url=PUBLIC_ORIGIN) as public:
        assert lan.get('/pwa/').status_code==403
        assert public.get('/pwa/').status_code==403


def test_cross_site_top_level_navigation_can_load_only_the_unauthenticated_shell(setup):
    root,pwa,app,node=setup
    navigation={
        'Sec-Fetch-Site':'cross-site',
        'Sec-Fetch-Mode':'navigate',
        'Sec-Fetch-Dest':'document',
        'Referer':'https://authority-engine-app.vercel.app/jarvis',
        'User-Agent':'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1',
    }
    with TestClient(app,base_url=ORIGIN) as client:
        shell=client.get('/pwa/',headers=navigation)
        assert shell.status_code==200 and '<title>JARVIS</title>' in shell.text
        assert client.get('/pwa/index.html',headers=navigation).status_code==200
        # Cross-site navigation is never an authenticated API bypass.
        assert client.get('/pwa/api/session',headers=navigation).status_code==403
        assert client.get('/interface/v1/health',headers=navigation).status_code==401
        # Missing navigation metadata, an Origin, a write, or another PWA path stays rejected.
        assert client.get('/pwa/',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert client.get('/pwa/',headers={**navigation,'Origin':'https://authority-engine-app.vercel.app'}).status_code==403
        assert client.post('/pwa/',headers=navigation).status_code==403
        assert client.get('/pwa/app.mjs',headers=navigation).status_code==403

def test_two_clients_upload_ownership_and_expiry(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as first,TestClient(app,base_url=ORIGIN) as second:
        a,_=enroll(pwa,first);b,_=enroll(pwa,second)
        assert a.json()['clientId']!=b.json()['clientId']
        raw=b'hello bounded evidence'
        uploaded=first.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'notes.txt'},content=raw)
        assert uploaded.status_code==200
        artifact=uploaded.json();assert artifact['sha256']==hashlib.sha256(raw).hexdigest()
        path='/interface/v1/artifacts/'+artifact['artifactId']
        assert first.get(path).content==raw
        assert second.get(path).status_code==404
        assert first.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'../escape.txt'},content=raw).status_code==422
        assert first.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'binary.pdf'},content=raw).status_code==415
        assert first.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'huge.txt'},content=b'x'*(1024*1024+1)).status_code==413
        with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,a.json()['clientId']))
        assert first.get(path).status_code==401

def test_upload_context_materializes_only_owned_bytes(setup,monkeypatch):
    root,pwa,app,node=setup;seen=[]
    monkeypatch.setattr(node,'submit',lambda body,client,auth:seen.append(body.context) or {'id':'task','state':'COMPLETED'})
    with TestClient(app,base_url=ORIGIN) as first,TestClient(app,base_url=ORIGIN) as second:
        enroll(pwa,first);enroll(pwa,second)
        artifact=first.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'note.md'},content=b'The measured count is 12.').json()['artifactId']
        body={'objective':'Summarize evidence','uploaded_artifact_ids':[artifact]}
        headers={**HEADERS,'Idempotency-Key':'fixture-key-123'}
        assert second.post('/interface/v1/objectives',headers=headers,json=body).status_code==404
        assert first.post('/interface/v1/objectives',headers=headers,json=body).status_code==202
        assert len(seen)==1 and 'The measured count is 12.' in seen[0]

def test_pairing_requires_local_owner_and_api_not_exposed(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post('/pwa/owner/pairing',headers={**HEADERS,'Authorization':'Bearer fixture-owner-credential-never-production'}).status_code==403
        assert client.get('/api/agents/objectives').status_code==404
        assert client.options('/pwa/api/session',headers=HEADERS).status_code in {403,405}

def test_interactive_loopback_pairing_and_expired_code(setup):
    root,pwa,app,node=setup
    owner=FastAPI();owner.include_router(pwa.owner_router)
    with TestClient(owner,base_url='http://127.0.0.1:8000',client=('127.0.0.1',45000)) as local:
        headers={'Origin':'http://127.0.0.1:8000','X-Jarvis-PWA':'1','Authorization':'Bearer fixture-owner-credential-never-production'}
        response=local.post('/pwa/owner/pairing',headers=headers)
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert response.json()['role']=='MEMBER'
        code=response.json()['code']
        with pwa.database() as db:db.execute('UPDATE pairing SET expires=? WHERE code_hash=?',(time.time()-1,pwa.digest(code)))
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code}).status_code==401

def test_owner_and_member_roles_are_server_issued_and_persisted(setup):
    root,pwa,app,node=setup
    owner=FastAPI();owner.include_router(pwa.owner_router)
    headers={'Origin':'http://127.0.0.1:8000','X-Jarvis-PWA':'1','Authorization':'Bearer fixture-owner-credential-never-production'}
    with TestClient(owner,base_url='http://127.0.0.1:8000',client=('127.0.0.1',45000)) as local:
        owner_code=local.post('/pwa/owner/pairing',headers=headers,json={'role':'OWNER'}).json()['code']
        member_code=local.post('/pwa/owner/pairing',headers=headers,json={'role':'MEMBER'}).json()['code']
        assert local.post('/pwa/owner/pairing',headers=headers,json={'role':'ADMIN'}).status_code==422
    with TestClient(app,base_url=ORIGIN) as owner_client,TestClient(app,base_url=ORIGIN) as member_client:
        owner_session=owner_client.post('/pwa/api/enroll',headers=HEADERS,json={'code':owner_code}).json()
        member_session=member_client.post('/pwa/api/enroll',headers=HEADERS,json={'code':member_code}).json()
        assert owner_session['role']=='OWNER'
        assert member_session['role']=='MEMBER'
        assert owner_client.get('/pwa/api/session').json()['role']=='OWNER'
        assert member_client.get('/pwa/api/session').json()['role']=='MEMBER'
        owner_policy=pwa.client_policy(owner_session['clientId']);member_policy=pwa.client_policy(member_session['clientId'])
        assert owner_policy['role']=='OWNER' and member_policy['role']=='MEMBER'
        assert 'authority.owner.verify' in owner_policy['capabilities']
        assert 'authority.owner.verify' not in member_policy['capabilities']
        assert owner_client.post('/pwa/api/owner-authority-check',headers=HEADERS).json()=={
            'authorized':True,'role':'OWNER','capability':'authority.owner.verify'}
        denied=member_client.post('/pwa/api/owner-authority-check',headers=HEADERS)
        assert denied.status_code==403 and denied.json()=={'detail':'Owner authority required'}
        assert member_client.post('/pwa/api/owner-authority-check',headers={**HEADERS,'X-Role':'OWNER'}).status_code==403
        with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,owner_session['clientId']))
        assert owner_client.post('/pwa/api/owner-authority-check',headers=HEADERS).status_code==401

def test_missing_policy_config_stays_local_only_and_bounded(setup,monkeypatch):
    root,pwa,app,node=setup
    monkeypatch.delenv('PRIME_PWA_DATA_CLASSIFICATION',raising=False);monkeypatch.delenv('PRIME_PWA_MAX_COST_USD',raising=False)
    with TestClient(app,base_url=ORIGIN) as client:
        response,_=enroll(pwa,client);identity=response.json()['clientId']
        assert pwa.client_policy(identity)['data_classification']=='LOCAL_ONLY'
        monkeypatch.setenv('PRIME_PWA_DATA_CLASSIFICATION','CLOUD_PERMITTED');monkeypatch.setenv('PRIME_PWA_MAX_COST_USD','.05')
        assert pwa.client_policy(identity)['max_cost_usd']==.05
        monkeypatch.setenv('PRIME_PWA_MAX_COST_USD','1000')
        with pytest.raises(Exception):pwa.client_policy(identity)

def test_enrollment_attempt_bound_and_unauthenticated_upload(setup,monkeypatch):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'note.txt'},content=b'text').status_code==401
        code=secrets.token_urlsafe(16)
        moments=iter([59.9]*10+[60.1])
        monkeypatch.setattr(pwa,'clock',lambda:next(moments))
        for _ in range(10):assert client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code}).status_code==401
        assert client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code}).status_code==429

def test_explicit_owner_link_shares_exact_dell_task_artifact_only(setup,monkeypatch):
    root,pwa,app,node=setup
    from app.artifact_factory import ArtifactFactory
    dell='dell:fixture';token='fixture-dell-token'
    policy={dell:{'token_sha256':pwa.digest(token),'expires_at':time.time()+300,'capabilities':pwa.SCOPES,'owner_account_id':'owner:fixture'}}
    monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON',json.dumps(policy))
    meta=ArtifactFactory(root/'artifacts').create(kind='json',content='{"actual":12}',task_id='same-task',creator='a10',provenance='Fixture verified output')
    with node.db_connect() as db:db.execute('INSERT INTO requests VALUES(?,?,?,?)',(dell,'key','hash','same-task'))
    monkeypatch.setattr(node.objective_api,'get',lambda task,auth:{'id':task,'state':'COMPLETED','steps':[]})
    with TestClient(app,base_url=ORIGIN) as linked,TestClient(app,base_url=ORIGIN) as unrelated:
        code=secrets.token_urlsafe(16)
        with pwa.database() as db:db.execute('INSERT INTO pairing(code_hash,expires,owner_account_id) VALUES(?,?,?)',(pwa.digest(code),time.time()+300,'owner:fixture'))
        response=linked.post('/pwa/api/enroll',headers=HEADERS,json={'code':code});assert response.status_code==200
        enroll(pwa,unrelated)
        assert linked.get('/interface/v1/tasks/same-task').json()['taskId']=='same-task'
        route='/interface/v1/artifacts/'+meta['artifact_id']
        artifact=linked.get(route);assert artifact.status_code==200 and artifact.headers['x-artifact-sha256']==meta['sha256']
        assert unrelated.get('/interface/v1/tasks/same-task').status_code==404
        assert unrelated.get(route).status_code==404
        assert unrelated.get(route,headers={'X-Owner-Account-Id':'owner:fixture'}).status_code==404
        # Server-side rebinding is not allowed to silently change preserved ownership.
        policy[dell]['owner_account_id']='different-owner';monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON',json.dumps(policy))
        assert linked.get(route).status_code==503

def test_existing_unlinked_session_not_broadened_by_environment(setup,monkeypatch):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        response,_=enroll(pwa,client)
        monkeypatch.setenv('PRIME_PWA_OWNER_ACCOUNT_ID','owner:fixture')
        assert 'owner_account_id' not in pwa.client_policy(response.json()['clientId'])

def test_durable_device_refresh_preserves_identity_role_and_running_task(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId'];device_cookie=client.cookies.get(pwa.DEVICE_COOKIE)
        with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,identity))
        refreshed=client.get('/pwa/api/session')
        assert refreshed.status_code==200 and refreshed.json()['authenticated'] is True
        assert refreshed.json()['clientId']==identity and refreshed.json()['role']=='MEMBER'
        assert client.cookies.get(pwa.DEVICE_COOKIE)==device_cookie

def test_invalid_or_revoked_device_fails_closed_without_changing_identity(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId']
        with pwa.database() as db:
            db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,identity));db.execute('UPDATE devices SET revoked=1 WHERE client_id=?',(identity,))
        assert client.get('/pwa/api/session').json()['authenticated'] is False
        with pwa.database() as db:
            row=db.execute('SELECT client_id,role,revoked FROM devices WHERE client_id=?',(identity,)).fetchone()
        assert row==(identity,'MEMBER',1)

def test_revoked_device_cannot_be_reissued_while_short_session_is_active(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId'];old=client.cookies.get(pwa.DEVICE_COOKIE)
        with pwa.database() as db:db.execute('UPDATE devices SET revoked=1 WHERE client_id=?',(identity,))
        current=client.get('/pwa/api/session')
        assert current.json()['authenticated'] is False
        assert old and client.cookies.get(pwa.DEVICE_COOKIE) is None
        with pwa.database() as db:assert db.execute('SELECT revoked FROM devices WHERE client_id=?',(identity,)).fetchone()==(1,)

def test_revoked_session_cannot_be_resurrected_by_valid_device(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId']
        with pwa.database() as db:db.execute('UPDATE sessions SET revoked=1 WHERE client_id=?',(identity,))
        assert client.get('/pwa/api/session').json()['authenticated'] is False
        with pwa.database() as db:assert db.execute('SELECT revoked FROM sessions WHERE client_id=?',(identity,)).fetchone()==(1,)

def test_invalid_session_token_cannot_use_valid_device_for_silent_recovery(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enroll(pwa,client);client.cookies.set(pwa.COOKIE,secrets.token_urlsafe(32),domain='192.168.1.23',path='/')
        assert client.get('/pwa/api/session').json()['authenticated'] is False
        assert client.cookies.get(pwa.COOKIE) is None and client.cookies.get(pwa.DEVICE_COOKIE) is None

def test_mismatched_session_and_device_fail_closed_without_authority_switch(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as member,TestClient(app,base_url=ORIGIN) as owner:
        member_result,_=enroll(pwa,member)
        code=secrets.token_urlsafe(16)
        with pwa.database() as db:db.execute('INSERT INTO pairing(code_hash,expires,used,owner_account_id,role) VALUES(?,?,0,?,?)',(pwa.digest(code),time.time()+300,'owner:fixture','OWNER'))
        owner_result=owner.post('/pwa/api/enroll',headers=HEADERS,json={'code':code});assert owner_result.status_code==200
        member.cookies.set(pwa.DEVICE_COOKIE,owner.cookies.get(pwa.DEVICE_COOKIE),domain='192.168.1.23',path='/')
        assert member.get('/pwa/api/session').json()['authenticated'] is False
        assert member.cookies.get(pwa.COOKIE) is None and member.cookies.get(pwa.DEVICE_COOKIE) is None
        with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,member_result.json()['clientId']))
        refreshed=member.get('/pwa/api/session').json()
        assert refreshed['authenticated'] is False
        assert owner.get('/pwa/api/session').json()['clientId']==owner_result.json()['clientId']

def test_active_legacy_session_bootstraps_durable_device_without_reenrollment(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId']
        client.cookies.delete(pwa.DEVICE_COOKIE)
        with pwa.database() as db:db.execute('DELETE FROM devices WHERE client_id=?',(identity,))
        current=client.get('/pwa/api/session')
        assert current.json()['authenticated'] is True and current.json()['clientId']==identity
        assert client.cookies.get(pwa.DEVICE_COOKIE)

def test_pwa_close_reopen_and_service_restart_refresh_same_durable_identity(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as first:
        enrolled,_=enroll(pwa,first);identity=enrolled.json()['clientId'];device_token=first.cookies.get(pwa.DEVICE_COOKIE)
    # A new browser process/app instance represents close/reopen and server restart;
    # only the durable HttpOnly device credential is carried forward.
    with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()-1,identity))
    restarted=FastAPI();restarted.include_router(pwa.router);restarted.add_middleware(pwa.PWASessionMiddleware)
    with TestClient(restarted,base_url=ORIGIN) as reopened:
        reopened.cookies.set(pwa.DEVICE_COOKIE,device_token)
        current=reopened.get('/pwa/api/session')
        assert current.status_code==200 and current.json()['authenticated'] is True
        assert current.json()['clientId']==identity


def test_active_trusted_session_slides_without_changing_token_or_role(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client);identity=enrolled.json()['clientId']
        token=client.cookies.get(pwa.COOKIE);device=client.cookies.get(pwa.DEVICE_COOKIE)
        with pwa.database() as db:db.execute('UPDATE sessions SET expires=? WHERE client_id=?',(time.time()+30,identity))
        renewed=client.get('/pwa/api/session')
        assert renewed.json()['authenticated'] and renewed.json()['role']=='MEMBER'
        assert renewed.json()['expiresAt']>time.time()+pwa.SESSION_SECONDS-10
        assert client.cookies.get(pwa.COOKIE)==token and client.cookies.get(pwa.DEVICE_COOKIE)==device
        assert 'no-store' in renewed.headers['cache-control']
        assert client.post('/pwa/api/owner-authority-check',headers=HEADERS).status_code==403


def test_expired_device_reports_recovery_and_does_not_renew_session(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        enrolled,_=enroll(pwa,client)
        with pwa.database() as db:db.execute('UPDATE devices SET expires=? WHERE client_id=?',(time.time()-1,enrolled.json()['clientId']))
        denied=client.get('/pwa/api/session').json()
        assert denied['authenticated'] is False and denied['recovery']=='DEVICE_EXPIRED'


def test_service_worker_empty_destination_navigation_admits_only_public_shell(setup):
    root,pwa,app,node=setup
    headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'empty'}
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get('/pwa/',headers=headers).status_code==200
        assert client.get('/pwa/index.html',headers=headers).status_code==200
        assert client.get('/pwa/api/session',headers=headers).status_code==403
        assert client.post('/pwa/api/enroll',headers=headers,json={'code':'x'}).status_code==403
        assert client.get('/pwa/',headers={**headers,'Origin':'https://evil.invalid'}).status_code==403
        assert client.get('/pwa/',headers={**headers,'Sec-Fetch-Mode':'cors'}).status_code==403
