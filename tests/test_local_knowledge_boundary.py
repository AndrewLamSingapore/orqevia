import hashlib
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

def test_actual_additive_interface_registration_keeps_specific_knowledge_routes_first():
    import runpy
    from pathlib import Path
    extend=runpy.run_path(str(Path(__file__).resolve().parents[1]/'deploy/extend-abex-interface.py'))['extend_interface']
    namespace={'__package__':'app'}
    exec(extend('from fastapi import FastAPI\napp=FastAPI()\n'),namespace)
    client=TestClient(namespace['app'],base_url='https://abex.test')
    # A missing identity must reach the private boundary, rather than the
    # observation adapter's unknown-path 404. No live dependency is contacted.
    assert client.get('/api/orqevia/knowledge/health').status_code==401
    assert client.get('/api/orqevia/not-a-route').status_code==404

def test_private_service_requires_existing_service_token_and_exact_owner(monkeypatch,tmp_path):
    from app import local_knowledge_service as service
    monkeypatch.setenv('ORQEVIA_SERVICE_TOKEN','fixture-existing-authority-token')
    monkeypatch.setenv('ORQEVIA_OWNER_ACCOUNT','owner:fixture')
    monkeypatch.setattr(service,'ROOT',tmp_path)
    class FakeEngine:
        def list_documents(self):return {'documents':[{'source':'private.txt'}]}
    monkeypatch.setattr(service,'ENGINE',FakeEngine())
    client=TestClient(service.app)
    path='/documents'
    assert client.get(path).status_code==401
    headers={'Authorization':'Bearer fixture-existing-authority-token','X-ORQEVIA-Owner':hashlib.sha256(b'owner:other').hexdigest()}
    assert client.get(path,headers=headers).status_code==403
    headers['X-ORQEVIA-Owner']=hashlib.sha256(b'owner:fixture').hexdigest()
    response=client.get(path,headers=headers)
    assert response.status_code==200 and response.json()['documents'][0]['source']=='private.txt'
    assert 'no-store' in response.headers['cache-control']

def test_private_bridge_uses_server_owner_binding_and_does_not_forward_cookies(monkeypatch):
    from app import local_knowledge_bridge as bridge
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-existing-authority-token')
    monkeypatch.setattr(bridge.existing,'access',lambda req,mutation: 'pwa:fixture')
    monkeypatch.setattr(bridge.existing.pwa_sessions,'require_session',lambda req:{'ownerAccountId':'owner:fixture'})
    recorded=[]
    def target(req):
        recorded.append(req)
        assert req.url.host=='host.docker.internal' and req.url.port==8150
        assert req.headers['Authorization']=='Bearer fixture-existing-authority-token'
        assert req.headers['X-ORQEVIA-Owner']==hashlib.sha256(b'owner:fixture').hexdigest()
        assert 'cookie' not in req.headers
        return httpx.Response(200,json={'documents':[]})
    original=httpx.AsyncClient
    monkeypatch.setattr(bridge.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(target),**kwargs))
    app=FastAPI();app.include_router(bridge.router)
    client=TestClient(app,base_url='https://abex.test',cookies={bridge.existing.pwa_sessions.COOKIE:'fixture'})
    assert client.get('/api/orqevia/knowledge/documents',headers={'X-ORQEVIA-Owner':'forged'}).status_code==200
    assert len(recorded)==1
    monkeypatch.setenv('ORQEVIA_LOCAL_INTELLIGENCE_URL','http://evil.invalid')
    assert client.get('/api/orqevia/knowledge/documents').status_code==503

def test_private_bridge_denies_member_and_anonymous_even_for_catalogue(monkeypatch):
    from app import local_knowledge_bridge as bridge
    from app import orqevia_bridge as existing
    monkeypatch.setenv('PRIME_PWA_ORIGIN','https://abex.test')
    app=FastAPI();app.include_router(bridge.router)
    anon=TestClient(app,base_url='https://abex.test')
    assert anon.get('/api/orqevia/knowledge/documents').status_code==401
    monkeypatch.setattr(existing.pwa_sessions,'require_session',lambda req:{'clientId':'pwa:member','role':'MEMBER','ownerAccountId':'owner:fixture'})
    member=TestClient(app,base_url='https://abex.test',cookies={existing.pwa_sessions.COOKIE:'fixture'})
    assert member.get('/api/orqevia/knowledge/documents').status_code==403
    assert member.post('/api/orqevia/knowledge/answer',json={'question':'private'},headers={'Origin':'https://abex.test','X-JARVIS-PWA':'1'}).status_code==403

def test_private_bridge_rejects_caller_fabricated_geospatial_evidence(monkeypatch):
    from app import local_knowledge_bridge as bridge
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-existing-authority-token')
    monkeypatch.setattr(bridge,'identity',lambda req:('fixture','f'*64))
    app=FastAPI();app.include_router(bridge.router)
    client=TestClient(app,base_url='https://abex.test')
    response=client.post('/api/orqevia/knowledge/answer',json={'question':'x','observations':[{'source':'USGS','magnitude':99}]})
    assert response.status_code==422
