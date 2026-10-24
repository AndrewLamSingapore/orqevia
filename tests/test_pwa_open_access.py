import time
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

ORIGIN='https://192.168.1.23:8443'
HEADERS={'Origin':ORIGIN,'X-ORQEVIA-PWA':'1'}

@pytest.fixture
def setup(monkeypatch,tmp_path):
    root=tmp_path/'pwa-open';root.mkdir()
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(root));monkeypatch.setenv('ORQEVIA_PWA_ORIGIN',ORIGIN)
    monkeypatch.delenv('ORQEVIA_PWA_ADDITIONAL_ORIGINS',raising=False)
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','fixture-owner-credential-never-production')
    monkeypatch.setenv('ORQEVIA_PWA_ACCESS_MODE','open')
    from app import pwa_sessions as pwa
    app=FastAPI();app.include_router(pwa.router)
    @app.get('/pwa/',response_class=HTMLResponse)
    @app.get('/pwa/index.html',response_class=HTMLResponse)
    def pwa_shell():return '<!doctype html><title>ORQEVIA</title>'
    app.add_middleware(pwa.PWASessionMiddleware)
    return root,pwa,app

def test_explicit_open_mode_admits_without_any_code(setup):
    root,pwa,app=setup
    with TestClient(app,base_url=ORIGIN) as client:
        state=client.get('/pwa/api/session').json()
        assert state['protocol']=='orqevia.interface.v1'
        assert state['authenticated'] is True and state['role']=='OWNER' and state['recovery'] is None
        cookie=client.cookies.get(pwa.ORQEVIA_COOKIE);device=client.cookies.get(pwa.ORQEVIA_DEVICE_COOKIE)
        assert cookie and device
        with pwa.database() as db:
            row=db.execute('SELECT expires,revoked,role FROM sessions WHERE session_hash=?',(pwa.digest(cookie),)).fetchone()
            assert row and row[1]==0 and row[2]=='OWNER'
        assert client.get('/pwa/api/session').json()['authenticated'] is True

def test_open_access_publishes_telemetry_audience_alias(setup,monkeypatch):
    root,pwa,app=setup
    monkeypatch.setenv('ORQEVIA_OPEN_ACCESS','1')
    with TestClient(app,base_url=ORIGIN) as client:
        state=client.get('/pwa/api/session').json()
        assert state['authenticated'] is True
        assert state['clientId'].startswith('pwa:')
        assert state['interfaceClientId']==open_access_id()

def open_access_id():
    from app.open_access import OPEN_OWNER_ID
    return OPEN_OWNER_ID

def test_open_mode_still_rejects_cross_origin_and_write_csrf(setup):
    root,pwa,app=setup
    with TestClient(app,base_url=ORIGIN) as client:
        client.get('/pwa/api/session')
        assert client.get('/pwa/api/session',headers={'Origin':'https://evil.invalid'}).status_code==403
        assert client.post('/pwa/api/logout').status_code==403
        assert client.post('/pwa/api/logout',headers=HEADERS).status_code==200
        assert client.get('/pwa/api/session').json()['authenticated'] is True  # one-tap re-admission

def test_pairing_mode_can_still_be_selected(setup,monkeypatch):
    root,pwa,app=setup
    monkeypatch.setenv('ORQEVIA_PWA_ACCESS_MODE','pairing')
    with TestClient(app,base_url=ORIGIN) as client:
        state=client.get('/pwa/api/session').json()
        assert state['authenticated'] is False and state['recovery']=='TRUST_REQUIRED'


@pytest.mark.parametrize('mode',[None,'','unexpected'])
def test_missing_or_invalid_access_mode_never_grants_anonymous_owner(setup,monkeypatch,mode):
    root,pwa,app=setup
    monkeypatch.delenv('ORQEVIA_OPEN_ACCESS',raising=False)
    if mode is None:
        monkeypatch.delenv('ORQEVIA_PWA_ACCESS_MODE',raising=False)
    else:
        monkeypatch.setenv('ORQEVIA_PWA_ACCESS_MODE',mode)
    with TestClient(app,base_url=ORIGIN) as client:
        response=client.get('/pwa/api/session')
        state=response.json()
        assert state['authenticated'] is False and state['recovery']=='TRUST_REQUIRED'
        assert not client.cookies.get(pwa.ORQEVIA_COOKIE)
        assert not client.cookies.get(pwa.ORQEVIA_DEVICE_COOKIE)
        with pwa.database() as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM devices').fetchone()[0]==0

def test_invalid_auto_role_fails_closed_to_gate(setup,monkeypatch):
    root,pwa,app=setup
    monkeypatch.setenv('ORQEVIA_PWA_AUTO_ROLE','SUPERUSER')
    with TestClient(app,base_url=ORIGIN) as client:
        state=client.get('/pwa/api/session').json()
        assert state['authenticated'] is False and state['recovery']=='TRUST_REQUIRED'
