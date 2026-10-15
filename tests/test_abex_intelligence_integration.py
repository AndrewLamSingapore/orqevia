"""Actual route/auth/storage integration regressions, with no provider spending."""
import json
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

def test_internal_auth_suspension_and_body_bounds(monkeypatch,tmp_path):
    from app.orqevia.security import install
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('PRIME_SPINE_TOKEN','test-existing-authority-token')
    app=FastAPI()
    called=[]
    @app.post('/api/orqevia/intelligence/ingest/run')
    def ingest():called.append(True);return {'ok':True}
    install(app);client=TestClient(app)
    path='/api/orqevia/intelligence/ingest/run'
    assert client.post(path).status_code==401
    headers={'Authorization':'Bearer test-existing-authority-token'}
    assert client.post(path,headers=headers,content=b'x'*16385).status_code==413
    (tmp_path/'suspended').write_text('owner suspended')
    assert client.post(path,headers=headers).status_code==503
    (tmp_path/'suspended').unlink()
    assert client.post(path,headers=headers).status_code==200
    assert called==[True]
    events=[json.loads(r) for r in (tmp_path/'execution-audit.jsonl').read_text().splitlines()]
    assert [r['phase'] for r in events]==['started','completed']

def test_bridge_member_write_denied_and_no_identity_header_ambiguity(monkeypatch):
    from app import orqevia_bridge as bridge
    from starlette.requests import Request
    def request(extra=()):
        return Request({'type':'http','method':'POST','scheme':'https','path':'/api/orqevia/intelligence/ingest/run',
            'server':('abex.test',443),'query_string':b'',
            'headers':[(b'host',b'abex.test'),(b'cookie',(bridge.pwa_sessions.COOKIE+'=fixture').encode()),*extra]})
    monkeypatch.setattr(bridge.pwa_sessions,'origin_valid',lambda req,write:True)
    monkeypatch.setattr(bridge.pwa_sessions,'require_session',lambda req:{'clientId':'pwa:fixture','role':'MEMBER'})
    assert bridge.access(request())=='pwa:fixture'
    with pytest.raises(HTTPException) as denied:bridge.access(request(),mutation=True)
    assert denied.value.status_code==403
    with pytest.raises(HTTPException) as denied:bridge.access(request([(b'authorization',b'Bearer spoof')]))
    assert denied.value.status_code==400

def test_ingestion_alert_history_and_restart(monkeypatch,tmp_path):
    from app.orqevia import intelligence_api as api
    from app import geo_ingest
    from app.geo_ingest import ObservationStore
    from app.rag_grounding import DocumentStore
    from app.event_detection import DetectionEngine
    monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    monkeypatch.setattr(api,'OBSERVATIONS',ObservationStore(tmp_path/'observations.db'))
    monkeypatch.setattr(api,'DOCUMENTS',DocumentStore())
    monkeypatch.setattr(api,'DETECTION',DetectionEngine(tmp_path/'alerts.json'))
    feature={'type':'Feature','id':'usgs-controlled-integration','properties':{'mag':5.5,'place':'controlled public-data fixture',
        'time':1760000000000,'url':'https://earthquake.usgs.gov/eventpage/usgs-controlled-integration'},
        'geometry':{'type':'Point','coordinates':[103.8,1.3,10]}}
    monkeypatch.setattr(geo_ingest,'_http_fetch',lambda url,timeout:{'features':[feature]})
    application=FastAPI();application.include_router(api.router)
    client=TestClient(application)
    path='/api/orqevia/intelligence'
    assert client.post(path+'/ingest/run').json()['inserted']==1
    assert len(client.get(path+'/detection/alerts').json()['alerts'])==1
    assert client.post(path+'/ingest/run').json()['updated']==1
    assert len(client.get(path+'/detection/alerts').json()['alerts'])==1
    assert client.get(path+'/history/timeline').json()['record_count']==1
    assert client.get(path+'/geo/events?limit=-1').status_code==400
    assert client.get(path+'/geo/radius?lat=1&lon=100&radius_km=-1').status_code==400
    assert client.post(path+'/rag/retrieve',json={'query':'earthquake magnitude'}).json()['status']=='GROUNDED'
    assert len(DetectionEngine(tmp_path/'alerts.json').alerts())==1
    assert DocumentStore.load(tmp_path/'documents.json').retrieve('earthquake',actor_scopes={'APPLICATION'})['status']=='GROUNDED'

def test_bridge_does_not_forward_unallowlisted_routes(monkeypatch):
    from app import orqevia_bridge as bridge
    app=FastAPI();app.include_router(bridge.router);client=TestClient(app,base_url='https://abex.test')
    assert client.get('/api/orqevia/private-records').status_code==404
    assert client.post('/api/orqevia/intelligence/sources').status_code==405

def test_active_gods_eye_is_map_and_extension_preserves_existing_runtime():
    root=Path(__file__).resolve().parents[1]
    html=(root/'app/orqevia/static/index.html').read_text(encoding='utf-8')
    assert 'src="/orqevia/gods-eye/map.html"' in html
    extension=(root/'deploy/extend-abex-interface.py').read_text()
    assert 'text+' in extension and "text.replace(needle,needle+" in extension
    docker=(root/'deploy/Dockerfile.interface-intelligence-abex').read_text()
    assert 'COPY app /app/app' not in docker
