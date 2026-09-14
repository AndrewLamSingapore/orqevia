import hashlib
import json
import secrets
import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORIGIN='https://192.168.1.23:8443'
HEADERS={'Origin':ORIGIN,'X-Jarvis-PWA':'1'}

@pytest.fixture
def setup(monkeypatch,tmp_path):
    root=tmp_path/'pwa-fixture';root.mkdir()
    monkeypatch.setenv('PRIME_DATA_DIR',str(root));monkeypatch.setenv('PRIME_PWA_ORIGIN',ORIGIN)
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-owner-credential-never-production')
    from app import pwa_sessions as pwa,interface_contract,interface_node
    app=FastAPI();app.include_router(pwa.router);app.include_router(pwa.owner_router);app.include_router(interface_contract.router)
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
        code=response.json()['code']
        with pwa.database() as db:db.execute('UPDATE pairing SET expires=? WHERE code_hash=?',(time.time()-1,pwa.digest(code)))
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post('/pwa/api/enroll',headers=HEADERS,json={'code':code}).status_code==401

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

def test_enrollment_attempt_bound_and_unauthenticated_upload(setup):
    root,pwa,app,node=setup
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post('/pwa/api/uploads',headers={**HEADERS,'X-Filename':'note.txt'},content=b'text').status_code==401
        code=secrets.token_urlsafe(16)
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
