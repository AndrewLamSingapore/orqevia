import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fabric_registry import load_fabric_registry, registry_report
from app.fabric_verification import apply_evidence

NOW = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
REVISION = "a" * 40


def observation(root, *, status="PASS", kind="FUNCTIONAL", age=30, check_status="PASS"):
    record = {
        "fabric_id": "f06",
        "version": "1.0.0",
        "runtime_revision": REVISION,
        "kind": kind,
        "scope": "SYNTHETIC_QUADRATIC_REFERENCE_ONLY",
        "observed_at": (NOW - timedelta(seconds=age)).isoformat(),
        "expires_at": (NOW - timedelta(seconds=age) + timedelta(hours=1)).isoformat(),
        "status": status,
        "checks": [{"name": "quadratic-oracle", "status": check_status}],
    }
    raw = json.dumps(record).encode()
    (root / "execution.json").write_bytes(raw)
    ref = {k: v for k, v in record.items() if k not in {"status", "checks"}}
    ref.update(path="execution.json", sha256=hashlib.sha256(raw).hexdigest())
    return {"schema": "orqevia.fabric-evidence.v1", "observations": [ref]}


def result(root, index, revision=REVISION):
    registry = apply_evidence(load_fabric_registry(), index, root, runtime_revision=revision, now=NOW)
    return next(x for x in registry["fabrics"] if x["id"] == "f06")


def test_old_catalog_receipts_cannot_self_certify_current_runtime():
    assert registry_report()["state_counts"]["VERIFIED"] == 0
    assert all(x["verification"]["status"] == "UNVERIFIED" for x in load_fabric_registry()["fabrics"])


def test_catalog_snapshots_do_not_share_mutable_state():
    first = load_fabric_registry()
    first["fabrics"][0]["evidence"].append({"fake": True})
    assert {"fake": True} not in load_fabric_registry()["fabrics"][0]["evidence"]


def test_recent_hashed_functional_receipt_verifies_only_its_scope(tmp_path):
    item = result(tmp_path, observation(tmp_path))
    assert item["state"] == "VERIFIED"
    assert item["verification"]["scope"] == "SYNTHETIC_QUADRATIC_REFERENCE_ONLY"


@pytest.mark.parametrize("revision", ["b" * 40, "UNKNOWN"])
def test_evidence_for_another_runtime_is_unverified(tmp_path, revision):
    item = result(tmp_path, observation(tmp_path), revision)
    assert item["state"] == "IMPLEMENTED"
    assert item["verification"]["reason"] == "SOURCE_MISMATCH"


def test_readiness_is_not_functional_verification(tmp_path):
    item = result(tmp_path, observation(tmp_path, kind="READINESS"))
    assert item["state"] != "VERIFIED"
    assert item["verification"]["reason"] == "FUNCTIONAL_EVIDENCE_REQUIRED"


def test_expired_and_future_receipts_do_not_pass(tmp_path):
    assert result(tmp_path, observation(tmp_path, age=4000))["state"] == "DEGRADED"
    assert result(tmp_path, observation(tmp_path, age=-30))["state"] == "IMPLEMENTED"


def test_hash_mismatch_is_unverified(tmp_path):
    index = observation(tmp_path)
    (tmp_path / "execution.json").write_text("{}")
    item = result(tmp_path, index)
    assert item["state"] == "IMPLEMENTED"
    assert item["verification"]["reason"] == "EVIDENCE_HASH_MISMATCH"


def test_fail_cannot_be_overridden_by_summary_pass(tmp_path):
    assert result(tmp_path, observation(tmp_path, check_status="FAIL"))["state"] == "FAILED"


def test_caller_cannot_relabel_a_different_fabric_receipt(tmp_path):
    index = observation(tmp_path)
    index["observations"][0]["fabric_id"] = "f05"
    registry = apply_evidence(load_fabric_registry(), index, tmp_path, runtime_revision=REVISION, now=NOW)
    item = next(x for x in registry["fabrics"] if x["id"] == "f05")
    assert item["state"] == "IMPLEMENTED"
    assert item["verification"]["reason"] == "RECEIPT_BINDING_MISMATCH"


def test_missing_executed_checks_cannot_pass(tmp_path):
    index = observation(tmp_path)
    path = tmp_path / "execution.json"
    receipt = json.loads(path.read_text())
    receipt["checks"] = []
    path.write_text(json.dumps(receipt))
    index["observations"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result(tmp_path, index)["verification"]["reason"] == "EXECUTED_CHECKS_REQUIRED"


def test_path_traversal_cannot_read_outside_evidence_root(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    index = observation(tmp_path)
    index["observations"][0]["path"] = "../execution.json"
    assert result(root, index)["state"] != "VERIFIED"


def test_duplicate_observations_are_rejected(tmp_path):
    index = observation(tmp_path)
    index["observations"].append(dict(index["observations"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        result(tmp_path, index)


def test_registry_api_uses_existing_bound_owner_authentication(tmp_path, monkeypatch):
    from app.collective_api import router

    token = "fixture-collective-token-long-enough"
    account = "fixture-owner"
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", token)
    monkeypatch.setenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", account)
    monkeypatch.setenv("ORQEVIA_COLLECTIVE_ENABLED", "1")
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = "/api/collective/v1/fabrics/registry"
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer " + token, "X-ORQEVIA-Owner": "wrong", "X-ORQEVIA-Actor": "owner"}
    assert client.get(path, headers=headers).status_code == 403
    headers["X-ORQEVIA-Owner"] = hashlib.sha256(account.encode()).hexdigest()
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    registry = response.json()["data"]
    assert registry["fabric_count"] == 36
    assert registry["summary"]["state_counts"]["VERIFIED"] == 0
    assert registry["evidence_index_status"] == "NOT_CONFIGURED"
