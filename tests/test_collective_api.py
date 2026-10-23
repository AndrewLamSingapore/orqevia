"""Authenticated HTTP contracts over actual isolated SQLite, not live acceptance."""

import hashlib
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import collective_api as api, collective_bridge as bridge
from app import interface_server, pwa_sessions

TOKEN = "collective-fixture-service-token-20261023"
OWNER = "collective-fixture-owner"
COOKIE = "c" * 43


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for key, value in {
        "ORQEVIA_SPINE_TOKEN": TOKEN,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": OWNER,
        "ORQEVIA_DATA_DIR": str(tmp_path),
        "PRIME_DATA_DIR": str(tmp_path),
        "ORQEVIA_COLLECTIVE_ENABLED": "1",
        "ORQEVIA_PWA_ORIGIN": "https://testserver",
        "ORQEVIA_PWA_ACCESS_MODE": "pairing",
        "ORQEVIA_OPEN_ACCESS": "0",
        "ORQEVIA_TENANT_ID": "personal",
    }.items():
        monkeypatch.setenv(key, value)
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app, base_url="http://backend")
    yield tmp_path, client
    client.close()


def headers():
    return {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "fixture-owner-session",
    }


def test_service_auth_owner_scope_and_legacy_open_flag_cannot_bypass(environment, monkeypatch):
    _, client = environment
    assert client.get("/api/collective/v1/status").status_code == 401
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    assert client.get("/api/collective/v1/status").status_code == 401
    assert (
        client.get("/api/collective/v1/status", headers={**headers(), "X-ORQEVIA-Owner": "0" * 64}).status_code == 403
    )
    response = client.get("/api/collective/v1/status", headers=headers())
    assert response.status_code == 200
    value = response.json()
    assert value["protocol"] == api.PROTOCOL and value["grants_execution_authority"] is False
    assert value["data"]["metrics"]["agents"]["registered"] == 21
    assert value["data"]["metrics"]["agents"]["verified_contributing_agents"] == 0
    assert value["data"]["metrics"]["registry_health"] == "PASS"
    assert response.headers["cache-control"] == "private, no-store"
    policy = client.get(
        "/api/collective/v1/lookup",
        params={
            "kind": "policies",
            "id": "policy:authorized-board-participation",
        },
        headers=headers(),
    ).json()["data"]
    assert policy["data"]["default_enrolled"] is True
    assert policy["data"]["board_content_is_untrusted"] is True
    assert policy["data"]["contribution_grants_authority"] is False
    monkeypatch.setenv("ORQEVIA_COLLECTIVE_ENABLED", "0")
    assert client.get("/api/collective/v1/status", headers=headers()).status_code == 503


def test_request_cannot_self_assign_verifier_system_or_agent_role(environment):
    _, client = environment
    base = {"operation": "registry.observe", "idempotency_key": "fixture-observe", "payload": {}}
    assert client.post("/api/collective/v1/commands", headers=headers(), json=base).status_code == 403
    base["operation"] = "evidence.record"
    base["roles"] = ["SYSTEM"]
    assert client.post("/api/collective/v1/commands", headers=headers(), json=base).status_code == 422
    base.pop("roles")
    base["payload"] = {"kind": "VERIFICATION", "source": "self", "content": {}, "environment": "fixture"}
    assert client.post("/api/collective/v1/commands", headers=headers(), json=base).status_code == 403
    for operation in ("gap.execute", "gap.verify", "claim.review", "puzzle.complete"):
        base["operation"] = operation
        assert client.post("/api/collective/v1/commands", headers=headers(), json=base).status_code == 403


def test_actual_http_observation_lookup_audit_idempotency_and_query_bounds(environment):
    _, client = environment
    body = {
        "operation": "evidence.record",
        "idempotency_key": "fixture-observation",
        "payload": {
            "kind": "OBSERVATION",
            "source": "isolated HTTP fixture",
            "content": {"sample": "observed"},
            "environment": "FIXTURE",
        },
    }
    response = client.post("/api/collective/v1/commands", headers=headers(), json=body)
    assert response.status_code == 200
    record = response.json()["data"]["record"]
    assert record["state"] == "UNVERIFIED"
    again = client.post("/api/collective/v1/commands", headers=headers(), json=body).json()["data"]
    assert again["record"]["id"] == record["id"] and again["replayed"] is True
    assert (
        client.get(
            "/api/collective/v1/lookup", params={"kind": "evidence", "id": record["id"]}, headers=headers()
        ).json()["data"]["id"]
        == record["id"]
    )
    assert client.get("/api/collective/v1/audit", headers=headers()).status_code == 200
    for params in (
        {"kind": "agents;DROP TABLE registry_records"},
        {"kind": "agents", "limit": 1000},
        {"kind": "agents", "offset": -1},
    ):
        assert client.get("/api/collective/v1/lookup", params=params, headers=headers()).status_code == 422
    body["payload"]["content"] = {"sample": "changed"}
    assert client.post("/api/collective/v1/commands", headers=headers(), json=body).status_code == 409


def test_cookie_gateway_enforces_origin_current_role_and_bound_owner(environment):
    with pwa_sessions.database() as db:
        db.execute(
            "INSERT INTO sessions(session_hash,client_id,expires,revoked,role,owner_account_id) VALUES(?,?,?,0,?,?)",
            (pwa_sessions.digest(COOKIE), "pwa:" + "b" * 32, time.time() + 300, "OWNER", OWNER),
        )
    original_client = httpx.AsyncClient
    seen = []

    def upstream(request):
        seen.append(request)
        assert request.url.host == "backend" and request.url.path.startswith("/api/collective/v1/")
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.headers["x-orqevia-owner"] == hashlib.sha256(OWNER.encode()).hexdigest()
        return httpx.Response(200, json={"protocol": api.PROTOCOL, "data": {"fixture": True}})

    with patch.object(
        bridge.httpx,
        "AsyncClient",
        side_effect=lambda **kw: original_client(transport=httpx.MockTransport(upstream), **kw),
    ):
        client = TestClient(interface_server.app, base_url="https://testserver")
        cookie = {"Cookie": pwa_sessions.COOKIE + "=" + COOKIE}
        assert client.get("/interface/v1/collective/status", headers=cookie).status_code == 200
        assert client.post("/interface/v1/collective/reconcile", headers=cookie, json={}).status_code == 403
        assert (
            client.post(
                "/interface/v1/collective/reconcile",
                headers={**cookie, "Origin": "https://evil.invalid", "X-ORQEVIA-PWA": "1"},
                json={},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/interface/v1/collective/status", headers={**cookie, "Authorization": "Bearer forged"}
            ).status_code
            == 400
        )
        assert client.get("/interface/v1/collective/arbitrary/endpoint", headers=cookie).status_code == 404
        with pwa_sessions.database() as db:
            db.execute("UPDATE sessions SET role='MEMBER'")
        assert client.get("/interface/v1/collective/status", headers=cookie).status_code == 403
        with pwa_sessions.database() as db:
            db.execute("UPDATE sessions SET role='OWNER',owner_account_id='another-owner'")
        assert client.get("/interface/v1/collective/status", headers=cookie).status_code == 403
        client.close()
    assert len(seen) == 1


def test_gateway_sanitizes_untrusted_error_body(environment):
    with pwa_sessions.database() as db:
        db.execute(
            "INSERT INTO sessions(session_hash,client_id,expires,revoked,role,owner_account_id) VALUES(?,?,?,0,?,?)",
            (pwa_sessions.digest(COOKIE), "pwa:" + "c" * 32, time.time() + 300, "OWNER", OWNER),
        )
    original_client = httpx.AsyncClient
    with patch.object(
        bridge.httpx,
        "AsyncClient",
        side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(422, text="SECRET_UNTRUSTED_INPUT")), **kw
        ),
    ):
        client = TestClient(interface_server.app, base_url="https://testserver")
        response = client.get("/interface/v1/collective/status", headers={"Cookie": pwa_sessions.COOKIE + "=" + COOKIE})
        client.close()
    assert response.status_code == 422 and "SECRET_UNTRUSTED_INPUT" not in response.text
