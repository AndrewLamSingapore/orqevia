"""Explicit unrestricted mode is opt-in and leaves default security intact."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.action_harness import HarnessedExecutor
from app.client_auth import authenticate_owner
from app.host_guard import EffectClass, enforce_at_execution
from app.interface_node import client_identity, client_policy
from app.open_access import OPEN_OWNER_ID
from app.sink_guard import PROTECTED, SinkGuard, SinkIntent


def test_default_mode_preserves_authentication_and_host_guard(monkeypatch):
    monkeypatch.delenv("ORQEVIA_OPEN_ACCESS", raising=False)
    with pytest.raises(Exception):
        authenticate_owner(None)
    assert client_policy("unknown") == {}
    with pytest.raises(PermissionError):
        enforce_at_execution({"action": "host.execute", "parameters": {}})
    sink = SimpleNamespace(
        connector_id="test",
        action_id="security-change",
        operation_tags=frozenset({"security_change"}),
    )
    with pytest.raises(PermissionError):
        SinkGuard().check(sink, {}, task_id="task", agent_id="a01")


def test_open_mode_uses_owner_identity_without_credentials(monkeypatch):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    authenticate_owner(None)
    assert client_identity(None, None, "objective.submit") == OPEN_OWNER_ID
    policy = client_policy("arbitrary-client")
    assert policy["role"] == "OWNER"
    assert "authority.owner.verify" in policy["capabilities"]
    assert policy["data_classification"] == "CLOUD_PERMITTED"
    assert policy["max_cost_usd"] == 100


def test_open_mode_bypasses_effect_and_sink_guards(monkeypatch):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    assert enforce_at_execution(
        {"action": "host.execute", "parameters": {"command": "remove everything"}}
    ) == EffectClass.HOST_HIGH_RISK
    sink = SimpleNamespace(
        connector_id="test",
        action_id="security-change",
        operation_tags=frozenset({"security_change"}),
    )
    SinkGuard().check(sink, {}, task_id="task", agent_id="a01")
    assert PROTECTED


def test_open_mode_executes_harnessed_payload_without_lease(monkeypatch):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")

    class NeverCalledHarness:
        def revalidate_for_execution(self, *_args, **_kwargs):
            raise AssertionError("security gate must not run")

    payload = {"message": "open"}
    result = HarnessedExecutor(NeverCalledHarness(), lambda value: value["message"]).execute(
        payload
    )
    assert result == "open"


def test_open_mode_accepts_http_and_cross_origin_pwa(monkeypatch, tmp_path):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "fixture-open-access-token")
    from app import pwa_sessions

    app = FastAPI()
    app.include_router(pwa_sessions.router)
    app.add_middleware(pwa_sessions.PWASessionMiddleware)

    @app.get("/pwa/", response_class=HTMLResponse)
    def shell():
        return "<!doctype html><title>ORQEVIA</title>"

    with TestClient(app, base_url="http://public.example") as client:
        response = client.get(
            "/pwa/",
            headers={
                "Origin": "https://elsewhere.example",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
        )
        assert response.status_code == 200
        state = client.get("/pwa/api/session").json()
        assert state["authenticated"] is True
        assert state["role"] == "OWNER"


def test_open_mode_interface_contract_accepts_http_without_bearer(monkeypatch):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    from app.interface_contract import authorize

    app = FastAPI()

    @app.get("/fixture")
    def fixture(request: Request):
        return {"client": authorize(request, "health.read")[0]}

    with TestClient(app, base_url="http://public.example") as client:
        assert client.get("/fixture").json() == {"client": OPEN_OWNER_ID}
