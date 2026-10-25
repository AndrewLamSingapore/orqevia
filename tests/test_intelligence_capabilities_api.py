"""Real SQLite/API integration; fixtures never establish predictive quality."""

import hashlib
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import collective_api, mel_api, pif_api
from app.pif import History, Observation, PIFService

TOKEN = "capability-api-fixture-20261025"
OWNER = "capability-owner-fixture"
PIF = "/api/collective/v1/intelligence/pif"
MEL = "/api/collective/v1/intelligence/mel"


@pytest.fixture
def context(tmp_path, monkeypatch):
    for name, value in {
        "ORQEVIA_DATA_DIR": str(tmp_path),
        "ORQEVIA_COMPUTE_QUEUE_DB": str(tmp_path / "compute-queue.db"),
        "ORQEVIA_SPINE_TOKEN": TOKEN,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": OWNER,
        "ORQEVIA_TENANT_ID": "fixture",
        "ORQEVIA_COLLECTIVE_ENABLED": "0",
        "ORQEVIA_PIF_ENABLED": "1",
        "ORQEVIA_MEL_ENABLED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    app = FastAPI()
    app.include_router(pif_api.router)
    app.include_router(mel_api.router)
    app.include_router(collective_api.router)
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "fixture-owner",
    }
    with TestClient(app, base_url="https://testserver", headers=headers) as client:
        yield client, tmp_path


@pytest.mark.parametrize("pif,mel", [(False, False), (True, False), (False, True), (True, True)])
def test_independent_flags_and_existing_core(context, monkeypatch, pif, mel):
    client, root = context
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", str(int(pif)))
    monkeypatch.setenv("ORQEVIA_MEL_ENABLED", str(int(mel)))
    assert client.get(PIF + "/status").json()["data"]["enabled"] is pif
    assert client.get(MEL + "/status").json()["data"]["enabled"] is mel
    # Both capability APIs work while the independently flagged board is off.
    assert client.get("/api/collective/v1/status").status_code == 503
    # Exercise the actual existing deterministic objective/dispatch path with
    # each feature combination. No external model or fabricated core response.
    from app.objective_api import ObjectiveRequest, get, submit

    monkeypatch.setenv("ORQEVIA_REGISTRY_V1_ENABLED", "1")
    response = submit(
        ObjectiveRequest(objective="Hash fixture", context="abc", deterministic_operation="sha256"), "Bearer " + TOKEN
    )
    actual = get(response["id"], "Bearer " + TOKEN)
    assert actual["state"] == "COMPLETED"
    assert actual["steps"][0]["dispatch"]["model_calls"] == 0


def test_auth_scope_cannot_be_supplied_in_body_or_bypassed_by_open_mode(context, monkeypatch):
    client, _ = context
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    for path in (PIF + "/status", MEL + "/status"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401
        assert client.get(path, headers={"X-ORQEVIA-Owner": "0" * 64}).status_code == 403
    assert client.post(PIF + "/fit", json={"queue": "/private/another-tenant.db"}).status_code == 422
    assert client.post(PIF + "/forecast", json={"start": "queued", "actor": "forged"}).status_code == 422
    assert client.post(PIF + "/scenario", json={"start": "queued", "samples": True}).status_code == 422


def test_missing_history_hidden_and_causal_data_are_explicit(context):
    client, root = context
    assert client.post(PIF + "/fit", json={}).json()["data"]["status"] == "INSUFFICIENT_DATA"
    assert client.post(PIF + "/forecast", json={}).json()["data"]["status"] == "INSUFFICIENT_DATA"
    for path in ("hidden-state", "intervention"):
        actual = client.post(PIF + "/" + path).json()["data"]
        assert actual["status"] in {"UNAVAILABLE", "INSUFFICIENT_DATA"}
        assert actual["grants_execution_authority"] is False


def test_shadow_forecast_scenario_evidence_and_model_rollback(context):
    client, root = context
    scope = hashlib.sha256(("fixture:" + hashlib.sha256(OWNER.encode()).hexdigest()).encode()).hexdigest()
    service = PIFService(tenant_id="owner:" + scope)
    rows = tuple(
        History(
            "fixture-" + str(i),
            (
                Observation("queued", f"2026-10-{i + 1:02d}T00:00:00Z", "a" + str(i)),
                Observation("completed", f"2026-10-{i + 1:02d}T00:00:01Z", "b" + str(i)),
            ),
            "fixture",
        )
        for i in range(30)
    )
    fitted = service.fit_history(rows, states=("queued", "completed"), absorbing_states=("completed",))
    version = fitted["model_version"]
    response = client.post(PIF + "/forecast", json={"start": "queued", "steps": 1}).json()["data"]
    assert response["status"] == "SHADOW"
    assert sum(response["data"]["probabilities"].values()) == pytest.approx(1)
    assert response["grants_execution_authority"] is False
    assert client.get(PIF + "/evidence/" + response["trace_id"]).status_code == 200
    scenario = client.post(PIF + "/scenario", json={"start": "queued", "steps": 2, "samples": 20, "seed": 7}).json()[
        "data"
    ]
    assert scenario["status"] == "SHADOW"
    assert client.post(PIF + "/rollback", json={"version": version}).status_code == 200
    # A new owner in the same tenant cannot read the prior owner's predictions.
    with pytest.MonkeyPatch.context() as change:
        change.setenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "other-owner")
        other = {"X-ORQEVIA-Owner": hashlib.sha256(b"other-owner").hexdigest()}
        assert client.get(PIF + "/model", headers=other).json()["data"]["status"] == "INSUFFICIENT_DATA"


def test_optional_storage_failure_does_not_disable_other_capability_or_core(context, monkeypatch):
    client, root = context
    unusable = root / "unusable"
    unusable.mkdir()
    monkeypatch.setenv("ORQEVIA_MODEL_REGISTRY_DB", str(unusable))
    assert client.get(PIF + "/status").json()["data"]["status"] == "DEGRADED"
    assert client.get(MEL + "/status").json()["data"]["status"] == "degraded"
    # Disable either capability without touching storage; remaining request
    # returns an explicit state rather than propagating an exception.
    monkeypatch.setenv("ORQEVIA_PIF_ENABLED", "0")
    assert client.post(PIF + "/fit", json={}).json()["data"]["status"] == "DISABLED"
    assert client.get(MEL + "/status").status_code == 200


def test_mel_evidence_validation_and_baseline_fallback(context):
    client, _ = context
    assert client.post(MEL + "/experiments", json={"evidence": {"forged": True}}).status_code == 422
    actual = client.get(MEL + "/recommendation").json()["data"]
    assert actual["status"] == "retain_baseline" and actual["model_routing_changed"] is False
    assert client.get(MEL + "/inventory").json()["data"]["model_routing_changed"] is False


def test_history_window_does_not_leak_later_outcomes(context):
    client, root = context
    with sqlite3.connect(root / "compute-queue.db") as db:
        db.executescript(
            "CREATE TABLE compute_jobs(id TEXT,agent TEXT,status TEXT,created_at TEXT,updated_at TEXT);"
            "CREATE TABLE compute_events(id TEXT,job_id TEXT,event_type TEXT,details_json TEXT,created_at TEXT);"
        )
        db.execute(
            "INSERT INTO compute_jobs VALUES(?,?,?,?,?)",
            ("window-job", "abex", "completed", "2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z"),
        )
        for event, kind, details, time in (
            ("submitted-window", "submitted", {"status": "queued"}, "2026-10-01T00:00:00Z"),
            ("claimed-window", "claimed", {}, "2026-10-02T00:00:00Z"),
            ("completed-window", "completed", {}, "2026-10-03T00:00:00Z"),
        ):
            db.execute(
                "INSERT INTO compute_events VALUES(?,?,?,?,?)", (event, "window-job", kind, json.dumps(details), time)
            )
    actual = client.post(PIF + "/fit", json={"until": "2026-10-01T12:00:00Z"}).json()["data"]
    assert actual["status"] == "INSUFFICIENT_DATA"
    assert actual["ingestion"]["diagnostics"]["jobs_retained"] == 1
    assert actual["model_provenance"]["transitions"] == 0
    end = actual["observation_period"][1]
    assert end is None or end <= "2026-10-01T12:00:00+00:00"
