"""Actual route/auth/storage integration regressions, with no provider spending."""
import json
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

def test_internal_auth_suspension_and_body_bounds(monkeypatch,tmp_path):
    from app.orqevia.security import install
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','test-existing-authority-token')
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

@pytest.mark.parametrize('kind',['documents','alerts'])
def test_failed_atomic_json_write_preserves_previous_restart_state(monkeypatch,tmp_path,kind):
    from app import atomic_json
    from app.rag_grounding import DocumentStore
    from app.event_detection import DetectionEngine
    if kind=='documents':
        path=tmp_path/'documents.json';store=DocumentStore()
        store.ingest(doc_id='public',text='earthquake preserved evidence',source='USGS',authority_class='PUBLIC_REFERENCE',scope='APPLICATION')
        store.save(path)
        operation=lambda:store.save(path)
        readback=lambda:DocumentStore.load(path).retrieve('earthquake',actor_scopes={'APPLICATION'})['status']=='GROUNDED'
    else:
        path=tmp_path/'alerts.json';store=DetectionEngine(path)
        store.add_rule('r',min_magnitude=5,geo_scope=None,severity='HIGH',cooldown_seconds=60)
        operation=lambda:store.add_rule('new',min_magnitude=6,geo_scope=None,severity='HIGH',cooldown_seconds=60)
        readback=lambda:set(DetectionEngine(path).data['rules'])=={'r'}
    before=path.read_bytes()
    monkeypatch.setattr(atomic_json.os,'replace',lambda *args:(_ for _ in ()).throw(OSError('controlled atomic commit failure')))
    with pytest.raises(OSError):operation()
    assert path.read_bytes()==before and readback()

def test_ui_health_uses_the_authenticated_companion_and_error_is_not_empty_map():
    root=Path(__file__).resolve().parents[1]
    js=(root/'app/orqevia/static/app.js').read_text(encoding='utf-8')
    assert "fetch('/api/orqevia/intelligence/health'" in js
    assert 'fetch("/api/orqevia/proxy/"' not in js
    mapjs=(root/'clients/pwa/command-map.mjs').read_text(encoding='utf-8')
    assert 'if (!res.ok) throw' in mapjs

def test_production_entry_requires_server_authentication(monkeypatch,tmp_path):
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','test-existing-authority-token')
    from app.orqevia.deployment import app
    client=TestClient(app)
    assert client.get('/api/orqevia/intelligence/health').status_code==401
    assert client.get('/api/orqevia/intelligence/health',headers={'Authorization':'Bearer test-existing-authority-token'}).status_code==200

def test_bridge_real_origin_checks_and_private_upstream_headers(monkeypatch):
    import httpx
    from app import orqevia_bridge as bridge
    monkeypatch.setenv('ORQEVIA_PWA_ORIGIN','https://abex.test')
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','test-existing-authority-token')
    monkeypatch.setattr(bridge.pwa_sessions,'require_session',lambda req:{'clientId':'pwa:fixture','role':'OWNER'})
    recorded=[]
    def upstream(request):
        assert request.url.host=='intelligence' and request.url.port==8100
        assert request.headers['Authorization']=='Bearer test-existing-authority-token'
        assert 'cookie' not in request.headers
        recorded.append(request)
        return httpx.Response(200,json={'ok':True})
    original=httpx.AsyncClient
    monkeypatch.setattr(bridge.httpx,'AsyncClient',lambda **options:original(transport=httpx.MockTransport(upstream),**options))
    app=FastAPI();app.include_router(bridge.router)
    client=TestClient(app,base_url='https://abex.test',cookies={bridge.pwa_sessions.COOKIE:'fixture'})
    path='/api/orqevia/intelligence/ingest/run'
    assert client.post(path).status_code==403
    assert client.post(path,headers={'Origin':'https://evil.test','X-ORQEVIA-PWA':'1'}).status_code==403
    assert client.post(path,headers={'Origin':'https://abex.test','X-ORQEVIA-PWA':'1'}).status_code==200
    assert len(recorded)==1
