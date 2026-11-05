"""Real session, task-ownership and evidence-store checks for the unified console."""

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from app import evidence_lens_bridge, interface_contract, pwa_sessions

ORIGIN = "https://localhost:8443"
HEADERS = {"Origin": ORIGIN, "X-ORQEVIA-PWA": "1"}


@pytest.fixture
def console(monkeypatch, tmp_path):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_COMPUTE_QUEUE_DB", str(tmp_path / "queue.db"))
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "synthetic-lens-owner-credential")
    monkeypatch.setenv("ORQEVIA_PWA_ORIGIN", ORIGIN)
    clients = {}
    with pwa_sessions.database() as db:
        for label, char, role, account in (
            ("owner", "a", "OWNER", "account-one"),
            ("peer", "b", "OWNER", "account-one"),
            ("other", "c", "OWNER", "account-two"),
            ("member", "d", "MEMBER", "account-one"),
        ):
            raw = char.upper() * 43
            db.execute(
                "INSERT INTO sessions(session_hash,client_id,expires,revoked,owner_account_id,role) "
                "VALUES(?,?,?,0,?,?)",
                (pwa_sessions.digest(raw), "pwa:" + char * 32, time.time() + 600, account, role),
            )
            clients[label] = raw
    app = FastAPI()
    app.add_middleware(pwa_sessions.PWASessionMiddleware)
    app.include_router(interface_contract.router)
    app.include_router(evidence_lens_bridge.router)
    app.mount("/pwa", StaticFiles(directory=Path(__file__).resolve().parents[1] / "clients/pwa", html=True))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, clients, tmp_path


def _session(client, clients, label):
    client.cookies.clear()
    if label:
        client.cookies.set(pwa_sessions.COOKIE, clients[label])


def _task(client, clients):
    _session(client, clients, "owner")
    result = client.post(
        "/interface/v1/objectives",
        headers=HEADERS,
        json={"objective": "How many agents do you have?", "idempotency_key": "lens-fixture"},
    )
    assert result.status_code == 202, result.text
    return result.json()["task_id"]


def test_owned_evidence_capture_is_explicit_deduplicated_and_not_claim_verification(console):
    client, clients, root = console
    task_id = _task(client, clients)
    path = "/interface/v1/lens/evidence/from-objective/" + task_id
    assert client.get(path).status_code == 404
    assert not (root / "evidence-lens.db").exists()
    task = client.get("/interface/v1/lens/objectives/" + task_id)
    assert task.status_code == 200 and task.json()["id"] == task_id
    first = client.post(path, headers=HEADERS, json={})
    assert first.status_code == 201, first.text
    value = first.json()
    assert value["integrity"] == "VALID" and value["verification"] == "UNVERIFIED"
    assert value["proof"]["time_freshness"] == "UNKNOWN"
    assert "independent_claim_verification" in value["proof"]["unproven"]
    replay = client.post(path, headers=HEADERS, json={})
    assert replay.status_code == 201 and replay.json() == value
    _session(client, clients, "peer")
    readback = client.get(path)
    assert readback.status_code == 200 and readback.json() == value
    assert "no-store" in readback.headers["cache-control"]
    assert "synthetic-lens-owner-credential" not in first.text + task.text + readback.text


def test_owner_role_task_account_and_csrf_are_enforced_before_capture(console):
    client, clients, root = console
    task_id = _task(client, clients)
    path = "/interface/v1/lens/evidence/from-objective/" + task_id
    for label, status in ((None, 401), ("member", 403), ("other", 404)):
        _session(client, clients, label)
        assert client.get(path).status_code == status
        assert client.post(path, headers=HEADERS, json={}).status_code == status
    _session(client, clients, "owner")
    assert client.post(path, json={}).status_code == 403
    assert client.post(path, headers={**HEADERS, "Origin": "https://foreign.invalid"}, json={}).status_code == 403
    assert client.get(path, headers={"X-ORQEVIA-Client-ID": "owner"}).status_code == 400
    assert client.post(path, headers=HEADERS, json={"authorization": "expand"}).status_code == 422
    assert client.post(path, headers=HEADERS, content=b"x" * 1025).status_code == 413
    assert not (root / "evidence-lens.db").exists()


def test_expired_owner_session_cannot_inspect_or_capture_evidence(console):
    client, clients, _ = console
    task_id = _task(client, clients)
    with pwa_sessions.database() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    path = "/interface/v1/lens/evidence/from-objective/" + task_id
    assert client.get(path).status_code == 401
    assert client.post(path, headers=HEADERS, json={}).status_code == 401


def test_https_canary_uses_real_scoped_sessions_and_records_only_unverified_proof(console, monkeypatch):
    from app import objective_api
    from scripts import lens_live_canary

    client, clients, _ = console
    _session(client, clients, "owner")
    calls = []

    def no_model(*args, **kwargs):
        pytest.fail("Deterministic canary must not invoke a model")

    def transport(base, method, path, *, payload=None, origin=None):
        assert base == ORIGIN
        calls.append(path)
        headers = {"X-ORQEVIA-PWA": "1", **({"Origin": origin} if origin else {})}
        response = client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.content

    monkeypatch.setattr(objective_api, "dispatch_request", no_model)
    monkeypatch.setattr(lens_live_canary, "_request", transport)
    result = lens_live_canary.run()
    assert result["integrity"] == "VALID" and result["currentness"] == "CURRENT"
    assert result["verification"] == "UNVERIFIED" and result["model_invoked"] is False
    assert result["scope"] == "ONE_DETERMINISTIC_LOCAL_SYNTHETIC_OBJECTIVE"
    assert all(not path.startswith("/control") for path in calls)
    readback = client.get("/interface/v1/lens/evidence/from-objective/" + result["task_id"])
    assert readback.status_code == 200 and readback.json()["record_id"] == result["record_id"]
    with pytest.raises(ValueError, match="HTTPS"):
        lens_live_canary.run("http://127.0.0.1:8000")


def test_canary_missing_or_ambiguous_credentials_fail_before_network(monkeypatch):
    from scripts import lens_live_canary

    for name in ("ORQEVIA_CANARY_CLIENT_ID", "ORQEVIA_CANARY_CLIENT_TOKEN", "ORQEVIA_CANARY_SESSION_COOKIE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lens_live_canary, "build_opener", lambda *args: pytest.fail("No network without credentials"))
    with pytest.raises(ValueError, match="credential"):
        lens_live_canary._request(ORIGIN, "GET", "/interface/v1/health")
    monkeypatch.setenv("ORQEVIA_CANARY_SESSION_COOKIE", "A" * 43)
    monkeypatch.setenv("ORQEVIA_CANARY_CLIENT_ID", "owner")
    with pytest.raises(ValueError, match="one scoped"):
        lens_live_canary._request(ORIGIN, "GET", "/interface/v1/health")
