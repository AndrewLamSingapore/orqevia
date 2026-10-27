import copy
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.observability_health import (
    CANARY_CHECKS,
    CANARY_SCHEMA,
    COLLECTOR_CHECKS,
    RECEIPT_SCHEMA,
    SERVICE_SPECS,
    operational_health_snapshot,
)

NOW = datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc).timestamp()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def observation(check_id, kind, at=NOW, status="PASS"):
    return {
        "check_id": check_id,
        "kind": kind,
        "status": status,
        "observed_at": iso(at),
        "last_success_at": iso(at) if status == "PASS" else None,
        "scope": "DECLARED_TEST_SCOPE",
        "source": "https://localhost:8443/fixture" if kind == "HTTPS_READINESS" else "fixture-source",
        "certificate_verified": kind == "HTTPS_READINESS",
        "reason": "OBSERVED_" + status,
    }


def receipt(at=NOW):
    services = []
    for service_id, (container, docker, checks) in SERVICE_SPECS.items():
        services.append(
            {
                "service_id": service_id,
                "container_name": container,
                "observed_at": iso(at),
                "process_state": "running",
                "docker_health": "healthy" if docker else None,
                "health_observed_at": iso(at) if docker else None,
                "health_last_success_at": iso(at) if docker else None,
                "checks": [observation(name, kind, at) for name, kind in checks.items()],
            }
        )
    return {
        "schema_version": RECEIPT_SCHEMA,
        "host_id": "fixture-host",
        "boot_id": "fixture-boot",
        "observed_at": iso(at),
        "cadence_seconds": 60,
        "services": services,
        "collector_checks": [observation(name, "CONFIGURATION", at) for name in COLLECTOR_CHECKS],
        "canary": {
            "schema_version": CANARY_SCHEMA,
            "observed_at_utc": iso(at),
            "check_count": len(CANARY_CHECKS),
            "failed_count": 0,
            "overall": "PASS",
            "checks": [{"name": name, "status": "PASS", "observed_at": iso(at)} for name in CANARY_CHECKS],
        },
    }


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setenv("ORQEVIA_INTERFACE_HOST_ID", "fixture-host")
    monkeypatch.delenv("ORQEVIA_HOST_BOOT_ID", raising=False)
    monkeypatch.delenv("ORQEVIA_OPERATIONAL_HEALTH_RECEIPT", raising=False)


def snapshot(tmp_path, value, now=NOW):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return operational_health_snapshot(receipt_path=path, data_dir=tmp_path / "data", now=now)


def test_complete_monitoring_preserves_observation_and_yields_current_zero(tmp_path):
    value = receipt(NOW - 10)
    report = snapshot(tmp_path, value)
    assert report["service_health"]["status"] == "HEALTHY"
    assert report["service_health"]["observed_at"] == iso(NOW - 10)
    assert report["service_health"]["evaluated_at"] == iso(NOW)
    assert report["service_health"]["coverage"]["expected_service_count"] == 9
    assert report["critical_issues"]["critical_count"] == 0
    assert report["critical_issues"]["coverage_complete"] is True


def test_no_collector_is_not_configured_and_not_a_current_zero(tmp_path):
    report = operational_health_snapshot(data_dir=tmp_path, now=NOW)
    assert report["service_health"]["status"] == "NOT_CONFIGURED"
    assert report["critical_issues"]["critical_count"] is None
    assert report["critical_issues"]["known_critical_count"] == 0
    assert not (tmp_path / "operational-health.db").exists()


@pytest.mark.parametrize(
    "change",
    [
        "missing_service",
        "disposable_stage",
        "missing_probe",
        "unverified_https",
        "wrong_host",
        "wrong_boot",
        "stale_receipt",
        "stale_canary",
        "contradictory_canary",
        "duplicate_service",
        "constant_ready",
    ],
)
def test_incomplete_or_invalid_monitoring_cannot_claim_current_zero(tmp_path, monkeypatch, change):
    value = receipt()
    if change == "missing_service":
        value["services"].pop()
    elif change == "disposable_stage":
        stage = copy.deepcopy(value["services"][0])
        stage["service_id"] = "stage"
        value["services"].append(stage)
    elif change == "missing_probe":
        value["services"][-1]["checks"] = []
    elif change == "unverified_https":
        value["services"][1]["checks"][0]["certificate_verified"] = False
    elif change == "wrong_host":
        value["host_id"] = "different-host"
    elif change == "wrong_boot":
        monkeypatch.setenv("ORQEVIA_HOST_BOOT_ID", "different-boot")
    elif change == "stale_receipt":
        value["observed_at"] = iso(NOW - 121)
    elif change == "stale_canary":
        value["canary"]["observed_at_utc"] = iso(NOW - 1201)
    elif change == "contradictory_canary":
        value["canary"]["failed_count"] = 1
    elif change == "duplicate_service":
        value["services"].append(copy.deepcopy(value["services"][0]))
    elif change == "constant_ready":
        value["services"][0]["checks"][1]["scope"] = "INTERFACE_READY"
    report = snapshot(tmp_path, value)
    assert report["critical_issues"]["critical_count"] is None
    assert report["service_health"]["coverage"]["complete"] is False
    assert report["service_health"]["status"] != "HEALTHY"


def test_running_tunnel_without_functional_probes_is_unmeasured(tmp_path):
    value = receipt()
    value["services"][-1]["checks"] = []
    report = snapshot(tmp_path, value)
    tunnel = report["service_health"]["services"][-1]
    assert tunnel["process_state"] == "RUNNING"
    assert tunnel["status"] == "NOT_CONFIGURED"
    assert tunnel["coverage_complete"] is False


def test_observed_tls_failure_is_an_incident_not_a_healthy_or_unmeasured_probe(tmp_path):
    value = receipt()
    value["services"][-1]["checks"][-1].update(
        status="FAIL", certificate_verified=False, reason="TLS_VERIFICATION_FAILED"
    )
    issues = snapshot(tmp_path, value)["critical_issues"]
    assert issues["critical_count"] == 1
    assert issues["incidents"][0]["reason"] == "TLS_VERIFICATION_FAILED"


def test_failure_replays_deduplicate_recover_and_reopen_with_original_times(tmp_path):
    value = receipt()
    check = value["services"][-1]["checks"][-1]
    check.update(status="FAIL", last_success_at=iso(NOW - 100), first_failure_at=iso(NOW - 50))
    for _ in range(2):
        report = snapshot(tmp_path, value)
    issues = report["critical_issues"]
    assert issues["critical_count"] == issues["known_critical_count"] == 1
    assert len(issues["transitions"]) == 1
    assert issues["incidents"][0]["opened_at"] == iso(NOW - 50)
    assert issues["incidents"][0]["last_success_at"] == iso(NOW - 100)
    recovered = snapshot(tmp_path, receipt(NOW + 10), NOW + 10)
    assert recovered["critical_issues"]["critical_count"] == 0
    assert [row["transition"] for row in recovered["critical_issues"]["transitions"]] == ["RECOVERED", "OPENED"]
    value = receipt(NOW + 20)
    value["services"][-1]["checks"][-1]["status"] = "FAIL"
    reopened = snapshot(tmp_path, value, NOW + 20)
    assert reopened["critical_issues"]["known_critical_count"] == 1
    assert len(reopened["critical_issues"]["transitions"]) == 3


def test_stale_unknown_and_older_receipts_do_not_recover_failure(tmp_path):
    value = receipt()
    value["services"][-1]["checks"][-1]["status"] = "FAIL"
    snapshot(tmp_path, value)
    stale = snapshot(tmp_path, value, NOW + 130)
    assert stale["critical_issues"]["critical_count"] is None
    assert stale["critical_issues"]["known_critical_count"] == 1
    assert len(stale["critical_issues"]["transitions"]) == 1
    older = snapshot(tmp_path, receipt(NOW - 10))
    assert older["critical_issues"]["critical_count"] is None
    assert older["critical_issues"]["known_critical_count"] == 1
    assert older["critical_issues"]["reason"] == "OBSERVATION_REGRESSION_OR_CONFLICT"


def test_identity_mismatch_is_preserved_as_degraded_with_historical_seed(tmp_path):
    value = receipt()
    next(row for row in value["canary"]["checks"] if row["name"] == "deployment-identity")["status"] = "FAIL"
    value["canary"].update(failed_count=1, overall="FAIL")
    value["canary_check_history"] = {
        "deployment-identity": {"last_success_at": iso(NOW - 300), "first_failure_at": iso(NOW - 200)}
    }
    report = snapshot(tmp_path, value)
    assert report["service_health"]["status"] == "DEGRADED"
    assert report["critical_issues"]["known_open_count"] == 1
    assert report["critical_issues"]["critical_count"] == 0
    incident = report["critical_issues"]["incidents"][0]
    assert incident["check_id"] == "deployment-identity"
    assert incident["opened_at"] == iso(NOW - 200)


def test_corrupt_incident_store_is_unavailable_and_not_zero(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "operational-health.db").write_text("not sqlite", encoding="utf-8")
    issues = snapshot(tmp_path, receipt())["critical_issues"]
    assert issues["store_status"] == "UNAVAILABLE"
    assert issues["critical_count"] is issues["known_critical_count"] is None


def test_unverified_collector_source_does_not_recover_known_failure(tmp_path):
    value = receipt()
    value["services"][-1]["checks"][-1]["status"] = "FAIL"
    snapshot(tmp_path, value)
    value = receipt(NOW + 10)
    value["collector_checks"][0]["status"] = "FAIL"
    report = snapshot(tmp_path, value, NOW + 10)
    assert report["critical_issues"]["critical_count"] is None
    assert report["critical_issues"]["known_critical_count"] == 1
    assert all(row["status"] == "UNKNOWN" for row in report["service_health"]["services"])


def test_retention_preserves_open_incidents_and_recent_recovery(tmp_path):
    value = receipt()
    value["services"][-1]["checks"][-1]["status"] = "FAIL"
    snapshot(tmp_path, value)
    db_path = tmp_path / "data" / "operational-health.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO operational_incidents(incident_key,service_id,check_id,severity,state,reason,opened_at,last_observed_at,recovered_at) VALUES('old','fixture','old','DEGRADED','RECOVERED','FIXTURE',?,?,?)",
            (NOW - 40 * 86400,) * 3,
        )
    snapshot(tmp_path, value)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM operational_incidents WHERE state='OPEN'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM operational_incidents WHERE incident_key='old'").fetchone()[0] == 0
