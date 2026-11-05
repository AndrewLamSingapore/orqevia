import hashlib
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.capability_depot import discover_capabilities, depot_snapshot, router


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    policies = {
        role.lower(): {
            "role": role,
            "token_sha256": hashlib.sha256(role.encode()).hexdigest(),
            "expires_at": time.time() + 300,
            "capabilities": ["health.read", "authority.owner.verify"],
        }
        for role in ("OWNER", "MEMBER")
    }
    monkeypatch.setenv("ORQEVIA_INTERFACE_CLIENTS_JSON", json.dumps(policies))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, base_url="https://testserver") as value:
        yield value


def headers(role):
    return {"X-Client-ID": role.lower(), "Authorization": "Bearer " + role}


def test_depot_uses_real_auth_and_denies_member_and_plaintext(client):
    assert client.get("/api/orqevia/depot").status_code == 401
    assert client.get("/api/orqevia/depot", headers=headers("MEMBER")).status_code == 403
    assert client.get("http://testserver/api/orqevia/depot", headers=headers("OWNER")).status_code == 426
    result = client.get("/api/orqevia/depot", headers=headers("OWNER"))
    assert result.status_code == 200
    assert result.json()["agents"]["registered_count"] == 21
    assert result.headers["cache-control"] == "private, no-store"


def test_observation_does_not_create_data_or_invent_balances(monkeypatch, tmp_path):
    absent = tmp_path / "never-created"
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(absent))
    snapshot = depot_snapshot()
    assert not absent.exists()
    assert snapshot["runtime"]["queue"]["status"] == "UNAVAILABLE"
    assert snapshot["wallet"]["balance"] is None
    assert snapshot["wallet"]["signing_available"] is False
    assert snapshot["service_management"]["docker_socket_exposed"] is False


def test_manifest_discovery_has_evidence_and_no_execution_or_secrets():
    items = discover_capabilities()
    assert len({item["id"] for item in items}) == len(items)
    assert {item["id"] for item in discover_capabilities("research")} >= {"local-knowledge"}
    assert all(item["available"] is None and item["runtime_status"] == "NOT_PROBED" for item in items)
    assert all(item["evidence"]["scope"] == "SOURCE_NOT_RUNTIME_QUALIFICATION" for item in items)
    assert "ORQEVIA_SPINE_TOKEN" not in json.dumps(items)


def test_evolution_endpoint_requires_owner_before_running(client):
    assert client.post("/api/orqevia/evolution/experiment").status_code == 401
    assert client.post("/api/orqevia/evolution/experiment", headers=headers("MEMBER")).status_code == 403


def test_owner_experiment_persists_evidence_and_rejects_changed_criteria(client):
    path = "/api/orqevia/evolution/experiment"
    denied = client.post(path, headers=headers("OWNER"), json={"criteria": "all pass"})
    assert denied.status_code == 422
    before = client.get("/api/orqevia/evolution/experiments", headers=headers("OWNER")).json()
    assert before["experiments"] == []
    result = client.post(path, headers=headers("OWNER"), json={})
    assert result.status_code == 200
    assert result.json()["production_policy_changed"] is False
    records = client.get("/api/orqevia/evolution/experiments", headers=headers("OWNER")).json()["experiments"]
    assert records[0]["run_id"] == result.json()["run_id"]
    assert records[0]["evidence_scope"] == "CONTROLLED_SYNTHETIC_HELDOUT_ONLY"
