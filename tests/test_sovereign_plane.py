"""Isolated contract/security fixtures. Live qualification is a separate receipt."""

import sqlite3
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import pwa_sessions, sovereign_plane as plane, sovereign_plane_bridge as bridge
from app import interface_server
from app.spine import SpineStore

TOKEN = "osip-isolated-fixture-token-20261023"
RAW_COOKIE = "s" * 43


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for key, value in {
        "ORQEVIA_SPINE_TOKEN": TOKEN,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": "test-owner",
        "ORQEVIA_DATA_DIR": str(tmp_path),
        "PRIME_DATA_DIR": str(tmp_path),
        "ORQEVIA_SPINE_DB": str(tmp_path / "spine.db"),
        "ORQEVIA_PWA_ORIGIN": "https://testserver",
        "ORQEVIA_OPEN_ACCESS": "0",
        "ORQEVIA_PWA_ACCESS_MODE": "pairing",
        "PRIME_PROVIDER_CATALOG": "",
    }.items():
        monkeypatch.setenv(key, value)
    with bridge._admission_lock:
        bridge._admissions.clear()
    app = FastAPI()
    app.include_router(plane.router)
    return tmp_path, TestClient(app, base_url="https://testserver")


def headers():
    return {"Authorization": "Bearer " + TOKEN}


def test_status_never_creates_stores_or_claims_unobserved_activity(environment):
    root, client = environment
    with (
        patch.object(
            plane,
            "model_runtime_readiness",
            return_value={
                "status": "UNAVAILABLE",
                "ready": False,
                "endpoint": "http://private-should-not-leak",
                "required_models": [],
                "missing_models": [],
            },
        ),
        patch.object(plane, "agent_activity", return_value=None),
    ):
        result = client.get("/api/osip/v1/status", headers=headers())
    assert result.status_code == 200
    value = result.json()
    assert value["read_only"] is True
    assert len(value["agents"]) == 21
    assert all(agent["availability"] == "NOT_OBSERVED" for agent in value["agents"])
    assert value["governance"]["approval_store"]["status"] == "UNAVAILABLE"
    assert value["memory"]["task_state"]["status"] == "UNAVAILABLE"
    assert not list(root.iterdir())
    assert "private-should-not-leak" not in result.text


def test_catalog_projection_excludes_endpoints_and_credentials(environment):
    _, client = environment
    catalog = [
        {
            "id": "fixture",
            "model": "measured-model",
            "tier": "MINI",
            "location": "local",
            "enabled": True,
            "endpoint": "http://do-not-expose",
            "secret_ref": "env:NEVER_EXPOSE_ME",
            "qualification_status": "QUALIFIED",
        }
    ]
    with (
        patch.object(plane, "load_catalog", return_value=catalog),
        patch.object(plane, "model_runtime_readiness", return_value={}),
        patch.object(plane, "agent_activity", return_value={}),
    ):
        response = client.get("/api/osip/v1/status", headers=headers())
    assert response.status_code == 200
    assert "NEVER_EXPOSE_ME" not in response.text and "do-not-expose" not in response.text
    assert response.json()["verification"]["provider_configuration_is_live_inference"] is False


def test_plan_uses_canonical_capabilities_and_never_executes(environment):
    root, client = environment
    response = client.post(
        "/api/osip/v1/plans", headers=headers(), json={"objective": "Plan a bounded architecture review"}
    )
    assert response.status_code == 200
    value = plane.Plan.model_validate(response.json())
    assert value.execution_performed is False and value.grants_execution_authority is False
    assert value.steps[1].depends_on == ["scope"] and value.steps[2].depends_on == ["reason"]
    canonical = {cap for a in plane.load_agent_registry()["agents"] for cap in a["capability_requirements"]}
    assert set(value.steps[1].capabilities) <= canonical
    assert not list(root.iterdir())
    for payload in ({"objective": " "}, {"objective": "x", "bypass": True}, {"objective": "x", "task_class": "shell"}):
        assert client.post("/api/osip/v1/plans", headers=headers(), json=payload).status_code == 422
    assert client.post("/api/osip/v1/plans", json={"objective": "x"}).status_code == 401


def test_approval_decision_reuses_existing_store_and_is_idempotent(environment):
    root, client = environment
    store = SpineStore(str(root / "spine.db"))
    envelope = {
        "idempotency_key": "fixture-approval",
        "correlation_id": "fixture-correlation",
        "action": "public.publish",
    }
    store.queue_approval(envelope, {"state": "GATED"})
    response = client.get("/api/osip/v1/approvals", headers=headers())
    assert response.status_code == 200 and response.json()["approvals"][0]["status"] == "PENDING"
    for path in ("/api/osip/v1/status", "/api/osip/v1/approvals"):
        assert client.get(path).status_code == 401
    response = client.post(
        "/api/osip/v1/approvals/fixture-approval",
        headers=headers(),
        json={"decision": "approve", "note": "Reviewed synthetic action only"},
    )
    assert response.status_code == 200 and response.json()["decision_recorded"] is True
    assert response.json()["execution_performed"] is False
    second = client.post(
        "/api/osip/v1/approvals/fixture-approval", headers=headers(), json={"decision": "reject", "note": "Replay"}
    )
    assert second.json()["decision_recorded"] is False and second.json()["status"] == "APPROVED"
    with sqlite3.connect(root / "spine.db") as db:
        assert db.execute("SELECT count(*) FROM event_bus").fetchone()[0] == 1
    assert (
        client.post(
            "/api/osip/v1/approvals/missing", headers=headers(), json={"decision": "approve", "note": "Test"}
        ).status_code
        == 404
    )


def test_unavailable_approvals_do_not_create_an_empty_authority(environment):
    root, client = environment
    assert client.get("/api/osip/v1/approvals", headers=headers()).status_code == 503
    assert (
        client.post(
            "/api/osip/v1/approvals/x", headers=headers(), json={"decision": "approve", "note": "test"}
        ).status_code
        == 503
    )
    assert not (root / "spine.db").exists()


def create_session(role="OWNER", account="test-owner"):
    actor = "pwa:" + "a" * 32
    with pwa_sessions.database() as db:
        db.execute(
            "INSERT INTO sessions(session_hash,client_id,expires,revoked,role,owner_account_id) VALUES(?,?,?,0,?,?)",
            (pwa_sessions.digest(RAW_COOKIE), actor, time.time() + 300, role, account),
        )
    return actor


def test_bridge_cookie_identity_origin_role_and_owner_binding(environment):
    root, _ = environment
    actor = create_session()
    original_client = httpx.AsyncClient
    seen = []

    def upstream(request):
        seen.append(request)
        assert request.url.host == "backend"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.headers["x-orqevia-actor"] == actor
        return httpx.Response(200, json={"protocol": "orqevia.osip.v1", "execution_performed": False})

    def factory(**kwargs):
        return original_client(transport=httpx.MockTransport(upstream), **kwargs)

    with (
        patch.object(bridge.httpx, "AsyncClient", side_effect=factory),
        TestClient(interface_server.app, base_url="https://testserver") as client,
    ):
        cookie = {"Cookie": pwa_sessions.COOKIE + "=" + RAW_COOKIE}
        assert client.get("/interface/v1/osip/status", headers=cookie).status_code == 200
        assert (
            client.get("/interface/v1/osip/status", headers={**cookie, "Authorization": "Bearer forged"}).status_code
            == 400
        )
        assert client.post("/interface/v1/osip/plans", headers=cookie, json={"objective": "test"}).status_code == 403
        assert (
            client.post(
                "/interface/v1/osip/plans",
                headers={**cookie, "Origin": "https://evil.invalid", "X-ORQEVIA-PWA": "1"},
                json={"objective": "test"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/interface/v1/osip/plans",
                headers={**cookie, "Origin": "https://testserver", "X-ORQEVIA-PWA": "1"},
                json={"objective": "test"},
            ).status_code
            == 200
        )
        with pwa_sessions.database() as db:
            db.execute("UPDATE sessions SET role='MEMBER'")
        assert client.get("/interface/v1/osip/status", headers=cookie).status_code == 403
        with pwa_sessions.database() as db:
            db.execute("UPDATE sessions SET role='OWNER',owner_account_id='other-owner'")
        assert client.get("/interface/v1/osip/status", headers=cookie).status_code == 403
        assert client.get("/interface/v1/osip/status").status_code == 401
    assert len(seen) == 2


def test_bridge_sanitizes_provider_validation_errors(environment):
    create_session()
    original_client = httpx.AsyncClient

    def factory(**kwargs):
        return original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(422, json={"detail": "PRIVATE_FIXTURE_INPUT"})
            ),
            **kwargs,
        )

    with (
        patch.object(bridge.httpx, "AsyncClient", side_effect=factory),
        TestClient(interface_server.app, base_url="https://testserver") as client,
    ):
        response = client.get("/interface/v1/osip/status", headers={"Cookie": pwa_sessions.COOKIE + "=" + RAW_COOKIE})
    assert response.status_code == 422 and "PRIVATE_FIXTURE_INPUT" not in response.text


def test_public_navigation_content_theme_and_transport(environment):
    with TestClient(interface_server.app, base_url="https://testserver") as client:
        for path in ("/", "/intelligence", "/capabilities", "/architecture", "/trust", "/access"):
            response = client.get(path)
            assert response.status_code == 200 and 'href="/pwa/"' in response.text
            assert response.text.count('aria-current="page"') == 1
            assert "host.docker.internal" not in response.text and TOKEN not in response.text
        assert client.get("/design/tokens.css").status_code == 200
        assert client.get("/public-assets/site.mjs").status_code == 200
        assert client.get("http://testserver/trust").status_code == 426
        assert client.get("/interface/v1/osip/status").status_code == 401
        assert client.get("/unavailable-public-page").status_code == 404


def test_request_capacity_is_bounded():
    with bridge._admission_lock:
        bridge._admissions.clear()
    for _ in range(60):
        bridge._admit("bounded-fixture")
    with pytest.raises(Exception) as error:
        bridge._admit("bounded-fixture")
    assert error.value.status_code == 429
