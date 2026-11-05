"""Freshly enrolled browser cookies traverse the real interface middleware/bridges."""

import hashlib
import hmac
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import interface_server, pwa_sessions


ORIGIN = "https://localhost:8443"
TOKEN = "synthetic-bridge-existing-owner-credential"
ACCOUNT = "cookie-compatibility-owner"
WRITE_HEADERS = {"Origin": ORIGIN, "X-ORQEVIA-PWA": "1"}
READ_PATHS = (
    "/pwa/api/project-workflows/templates",
    "/pwa/api/project-workflows",
    "/pwa/api/notebooks/health",
    "/pwa/api/academy/probability",
    "/interface/v1/osip/status",
    "/interface/v1/collective/status",
    "/interface/v1/collective/fabrics/registry",
    "/api/orqevia/knowledge/documents",
)
WRITE_PATHS = (
    "/pwa/api/project-workflows",
    "/pwa/api/notebooks/search",
    "/interface/v1/osip/plans",
    "/interface/v1/collective/commands",
    "/api/orqevia/knowledge/retrieve",
)


@pytest.fixture(params=("modern", "legacy"))
def browser(request, monkeypatch, tmp_path):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    monkeypatch.setenv("ORQEVIA_PWA_ACCESS_MODE", "pairing")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_COMPUTE_QUEUE_DB", str(tmp_path / "queue.db"))
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", TOKEN)
    monkeypatch.setenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("ORQEVIA_PWA_OWNER_ORIGIN", ORIGIN)
    monkeypatch.setenv("ORQEVIA_PWA_ORIGIN", ORIGIN)
    monkeypatch.setenv("ORQEVIA_PWA_DATA_CLASSIFICATION", "LOCAL_ONLY")
    monkeypatch.setenv("ORQEVIA_PWA_MAX_COST_USD", "0")
    monkeypatch.setenv("ORQEVIA_INTERFACE_CLIENTS_JSON", "{}")
    monkeypatch.delenv("ORQEVIA_PWA_ADDITIONAL_ORIGINS", raising=False)
    monkeypatch.delenv("ORQEVIA_NOTEBOOK_ADMIN_TOKEN", raising=False)

    owner_app = FastAPI()
    owner_app.include_router(pwa_sessions.owner_router)
    seen = []
    original_client = httpx.AsyncClient

    def upstream(outgoing):
        assert outgoing.url.host in {"backend", "host.docker.internal"}
        assert outgoing.headers["authorization"] == "Bearer " + TOKEN
        assert "cookie" not in outgoing.headers
        assert "x-client-id" not in outgoing.headers
        assert "x-orqevia-client-id" not in outgoing.headers
        if "x-orqevia-owner" in outgoing.headers:
            assert outgoing.headers["x-orqevia-owner"] == hashlib.sha256(ACCOUNT.encode()).hexdigest()
        seen.append(outgoing)
        return httpx.Response(200, json={"fixture_upstream": True, "execution_performed": False})

    def client_factory(**kwargs):
        return original_client(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    with (
        TestClient(owner_app, base_url=ORIGIN, client=("127.0.0.1", 43123)) as owner,
        TestClient(interface_server.app, base_url=ORIGIN) as client,
    ):

        def enroll(role="OWNER"):
            paired = owner.post(
                "/pwa/owner/pairing",
                headers={**WRITE_HEADERS, "Authorization": "Bearer " + TOKEN},
                json={"role": role},
            )
            assert paired.status_code == 200
            client.cookies.clear()
            enrolled = client.post("/pwa/api/enroll", headers=WRITE_HEADERS, json={"code": paired.json()["code"]})
            assert enrolled.status_code == 200 and enrolled.json()["role"] == role
            assert set(client.cookies.keys()) == {pwa_sessions.ORQEVIA_COOKIE, pwa_sessions.ORQEVIA_DEVICE_COOKIE}
            if request.param == "legacy":
                session = client.cookies.get(pwa_sessions.ORQEVIA_COOKIE)
                device = client.cookies.get(pwa_sessions.ORQEVIA_DEVICE_COOKIE)
                client.cookies.clear()
                client.cookies.set(pwa_sessions.COOKIE, session)
                client.cookies.set(pwa_sessions.DEVICE_COOKIE, device)
            return enrolled.json()["clientId"]

        client_id = enroll()
        yield client, seen, enroll, client_id


def test_fresh_owner_browser_can_read_every_affected_bridge(browser):
    client, seen, _, client_id = browser
    session = client.get("/pwa/api/session")
    assert session.status_code == 200 and session.json()["clientId"] == client_id
    for path in READ_PATHS:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert response.json()["fixture_upstream"] is True
        assert "no-store" in response.headers["cache-control"]
    assert len(seen) == len(READ_PATHS)
    for outgoing in seen:
        if outgoing.url.path.startswith("/api/agent-notebooks"):
            assert outgoing.headers["x-orqevia-actor"] == "owner"
            assert outgoing.headers["x-orqevia-role"] == "OWNER"
            expected = hmac.new(TOKEN.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256).hexdigest()
            assert outgoing.headers["x-orqevia-notebook-admin"] == expected
        elif "x-orqevia-actor" in outgoing.headers:
            assert outgoing.headers["x-orqevia-actor"] == client_id


def test_member_browser_cannot_inherit_owner_bridge_access(browser):
    client, seen, enroll, _ = browser
    enroll("MEMBER")
    for path in READ_PATHS:
        assert client.get(path).status_code == 403, path
        assert (
            client.get(path, headers={"X-ORQEVIA-Owner": hashlib.sha256(ACCOUNT.encode()).hexdigest()}).status_code
            == 403
        )
    assert seen == []


def test_browser_supplied_identity_headers_are_rejected_before_forwarding(browser):
    client, seen, _, _ = browser
    for path in READ_PATHS:
        for name in ("Authorization", "X-Client-Id", "X-ORQEVIA-Client-Id"):
            response = client.get(path, headers={name: "synthetic-spoofed-identity"})
            assert response.status_code == 400, (path, name, response.status_code)
    assert seen == []


def test_owner_bridge_requests_still_require_same_origin_and_csrf(browser):
    client, seen, _, _ = browser
    for path in READ_PATHS:
        assert client.get(path, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    for path in WRITE_PATHS:
        assert client.post(path, json={}).status_code == 403
        assert (
            client.post(path, json={}, headers={**WRITE_HEADERS, "Origin": "https://foreign.invalid"}).status_code
            == 403
        )
    assert seen == []
    for path in WRITE_PATHS:
        assert client.post(path, json={}, headers=WRITE_HEADERS).status_code == 200
    assert len(seen) == len(WRITE_PATHS)


@pytest.mark.parametrize("invalidity", ("revoked", "expired"))
def test_missing_invalid_revoked_and_expired_sessions_cannot_use_owner_bridges(browser, invalidity):
    client, seen, enroll, client_id = browser
    client.cookies.clear()
    for path in READ_PATHS:
        assert client.get(path).status_code == 401
    client.cookies.set(pwa_sessions.ORQEVIA_COOKIE, "malformed-session")
    for path in READ_PATHS:
        assert client.get(path).status_code == 401
    client_id = enroll()
    with pwa_sessions.database() as database:
        if invalidity == "revoked":
            database.execute("UPDATE sessions SET revoked=1 WHERE client_id=?", (client_id,))
        else:
            database.execute("UPDATE sessions SET expires=? WHERE client_id=?", (time.time() - 1, client_id))
    for path in READ_PATHS:
        assert client.get(path).status_code == 401
    assert seen == []


def test_interface_bridges_preserve_the_configured_owner_account_boundary(browser):
    client, seen, _, client_id = browser
    with pwa_sessions.database() as database:
        database.execute("UPDATE sessions SET owner_account_id='foreign-account' WHERE client_id=?", (client_id,))
    for path in ("/interface/v1/osip/status", "/interface/v1/collective/status"):
        assert client.get(path).status_code == 403
        assert (
            client.get(path, headers={"X-ORQEVIA-Owner": hashlib.sha256(ACCOUNT.encode()).hexdigest()}).status_code
            == 403
        )
    assert seen == []
