"""Synthetic session-bound product boundary; no workers, models or live data."""
from pathlib import Path
import secrets
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

ORIGIN = 'https://192.168.1.23:8443'
PUBLIC = 'https://jarvis.lamjarvis.com'
ROUTES = ('/pwa/control-center', '/pwa/api/control-center')


@pytest.fixture
def surface(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_PWA_ORIGIN', ORIGIN)
    monkeypatch.delenv('PRIME_PWA_ADDITIONAL_ORIGINS', raising=False)
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'synthetic-test-secret-never-production')
    from app import product_surfaces, pwa_sessions
    app = FastAPI()
    app.include_router(product_surfaces.router)
    app.include_router(pwa_sessions.router)
    app.add_middleware(pwa_sessions.PWASessionMiddleware)
    return app, pwa_sessions


def bind(client, pwa, role='OWNER', *, expiry=None, revoked=0, device=True):
    raw = secrets.token_urlsafe(32)
    trusted = secrets.token_urlsafe(32)
    client_id = 'pwa:' + secrets.token_hex(16)
    with pwa.database() as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                   (pwa.digest(raw), client_id, expiry or time.time() + 600,
                    revoked, 'synthetic-account', role))
        if device:
            db.execute('INSERT INTO devices VALUES(?,?,?,0,?,?)',
                       (pwa.digest(trusted), client_id, time.time() + 600,
                        'synthetic-account', role))
    client.cookies.set(pwa.COOKIE, raw)
    if device:
        client.cookies.set(pwa.DEVICE_COOKIE, trusted)
    return client_id, raw, trusted


@pytest.mark.parametrize('route', ROUTES)
def test_anonymous_and_member_are_denied_on_server(surface, route):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(route).status_code == 401
        bind(client, pwa, 'MEMBER')
        assert client.get(route).status_code == 403
        for header in ('X-Role', 'X-Owner', 'X-Client-Id', 'X-Jarvis-Client-Id', 'Authorization'):
            assert client.get(route, headers={header: 'OWNER'}).status_code == 403


def test_owner_read_only_projection_has_no_operational_or_secret_uplift(surface):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        client_id, raw, trusted = bind(client, pwa)
        response = client.get(ROUTES[1])
        assert response.status_code == 200
        value = response.json()
        assert value['authority'] == {'role': 'OWNER', 'session': 'VERIFIED',
                                     'scope': 'READ_ONLY_SESSION_STATUS',
                                     'grants_operational_authority': False}
        assert value['runtime_health'] == value['agent_certification'] == 'UNMEASURED'
        assert value['operational_projections'] == 'NOT_CONNECTED'
        assert value['workspace'] == '/pwa/'
        for private in (raw, trusted, client_id, 'synthetic-account', 'synthetic-test-secret-never-production'):
            assert private not in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert "default-src 'self'" in response.headers['content-security-policy']
        page = client.get(ROUTES[0])
        assert page.status_code == 200 and 'PRIME Control Center' in page.text
        assert '/control' not in page.text.replace('/pwa/api/control-center', '').replace('/pwa/control-center', '')
        assert '<script' not in page.text and '<style' not in page.text
        assert 'not connected' in page.text
        for route in ROUTES:
            assert client.post(route, headers={'Origin': ORIGIN, 'X-Jarvis-PWA': '1'}).status_code == 405


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('mode', ('expired', 'revoked', 'invalid', 'device_revoked', 'device_mismatch'))
def test_no_silent_owner_refresh_or_revocation_bypass(surface, route, mode):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        client_id, raw, trusted = bind(client, pwa,
                                     expiry=time.time() - 1 if mode == 'expired' else None,
                                     revoked=1 if mode == 'revoked' else 0)
        if mode == 'invalid':
            client.cookies.set(pwa.COOKIE, 'malformed')
        if mode.startswith('device_'):
            with pwa.database() as db:
                if mode == 'device_revoked':
                    db.execute('UPDATE devices SET revoked=1 WHERE client_id=?', (client_id,))
                else:
                    db.execute("UPDATE devices SET role='MEMBER' WHERE client_id=?", (client_id,))
        assert client.get(route).status_code == 401
        with pwa.database() as db:
            assert db.execute('SELECT session_hash FROM sessions WHERE client_id=?', (client_id,)).fetchone()[0] == pwa.digest(raw)


@pytest.mark.parametrize('headers', (
    {'Host': 'evil.invalid'}, {'Origin': 'https://evil.invalid'},
    {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'},
    [('Origin', ORIGIN), ('Origin', 'https://evil.invalid')],
    [('Host', '192.168.1.23:8443'), ('Host', 'evil.invalid')],
    {'Authorization': 'Bearer synthetic-test-secret-never-production'},
))
def test_origin_and_caller_authority_are_not_proxied(surface, headers):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        bind(client, pwa)
        for route in ROUTES:
            assert client.get(route, headers=headers).status_code == 403


def test_http_and_unapproved_public_origin_denied(surface, monkeypatch):
    app, pwa = surface
    for base in ('http://192.168.1.23:8443', PUBLIC):
        with TestClient(app, base_url=base) as client:
            bind(client, pwa)
            for route in ROUTES:
                assert client.get(route).status_code == 403
    monkeypatch.setenv('PRIME_PWA_ADDITIONAL_ORIGINS', PUBLIC)
    with TestClient(app, base_url=PUBLIC) as client:
        bind(client, pwa)
        assert client.get(ROUTES[0]).status_code == 200
        assert client.get(ROUTES[1]).status_code == 200
        assert client.get(ROUTES[1], headers={'Origin': ORIGIN}).status_code == 403


def test_legacy_valid_owner_session_remains_readable_without_new_device_issuance(surface):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        bind(client, pwa, device=False)
        assert client.get(ROUTES[1]).status_code == 200
        with pwa.database() as db:
            assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0] == 0


def test_current_session_role_is_authoritative_after_server_demotion(surface):
    app, pwa = surface
    with TestClient(app, base_url=ORIGIN) as client:
        client_id, _, _ = bind(client, pwa)
        assert client.get(ROUTES[1]).status_code == 200
        with pwa.database() as db:
            db.execute("UPDATE sessions SET role='MEMBER' WHERE client_id=?", (client_id,))
        assert client.get(ROUTES[1]).status_code == 403


def test_interface_wires_surface_before_static_mount_without_ambient_console():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'interface_server.py').read_text(encoding='utf-8')
    assert source.index('app.include_router(product_surfaces_router)') < source.index("app.mount('/pwa'")
    boundary = (Path(__file__).resolve().parents[1] / 'app' / 'product_surfaces.py').read_text(encoding='utf-8')
    assert 'local_authorization' not in boundary and 'internal_token(' not in boundary
    assert 'authenticate_owner' not in boundary and 'requests.' not in boundary
