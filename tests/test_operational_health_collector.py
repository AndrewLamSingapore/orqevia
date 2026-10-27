import copy
import json
import ssl
import urllib.error

import pytest

from app.observability_health import SERVICE_SPECS, operational_health_snapshot
from scripts import collect_operational_health as producer

NOW = 1793077200.0


class FakeRunner:
    def __init__(self, worker=True):
        self.worker = worker
        self.calls = []

    def run(self, args, *, script=None, timeout=3):
        self.calls.append(args)
        if "inspect" in args:
            rows = []
            for service_id, (name, _) in producer.SERVICES.items():
                rows.append(
                    {
                        "container_id": "backend-id" if service_id == "backend" else service_id,
                        "name": "/" + name,
                        "process_state": "running",
                        "started_at": producer.iso(NOW - 600),
                        "source_revision": "a" * 40,
                        "network_mode": "container:backend-id" if service_id == "otel-collector" else "fixture-network",
                        "docker_health": "healthy" if SERVICE_SPECS[service_id][1] else None,
                        "health_observations": [{"observed_at": producer.iso(NOW - 20), "exit_code": 0}]
                        if SERVICE_SPECS[service_id][1]
                        else [],
                    }
                )
            return 0, "\n".join(json.dumps(row) for row in rows)
        if script == producer.BACKEND_READ:
            return 0, json.dumps(
                {
                    "database_read": True,
                    "observed_at": producer.iso(NOW),
                    "worker_started_at": producer.iso(NOW - 20) if self.worker else None,
                    "worker_completed_at": producer.iso(NOW - 15) if self.worker else None,
                    "required_models": ["fixture:1"],
                }
            )
        if script == producer.COACHING_READ:
            return 0, json.dumps({"tick_epoch": NOW - 10, "source_revision": "a" * 40})
        if "logs" in args:
            return 0, producer.iso(NOW - 12) + ' Metrics {"otelcol.signal": "metrics", "data points": 9}'
        return 0, "NAME ID SIZE MODIFIED\nfixture:1 abc 1GB now\n"


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(producer.time, "time", lambda: NOW)
    monkeypatch.setenv("ORQEVIA_INTERFACE_HOST_ID", "fixture-host")
    return {
        "native_identity": {"host_id": "fixture-host", "boot_id": producer.iso(NOW - 3600)},
        "host_receipt": {
            "schema": "orqevia.host-metrics.v1",
            "collector_id": "abex-host-metrics-v1",
            "host_id": "fixture-host",
            "boot_id": producer.iso(NOW - 3600),
            "captured_at": NOW - 5,
            "cadence_seconds": 60,
        },
        "integrity": {
            "status": "PASS",
            "observed_at": producer.iso(NOW - 1),
            "reason": "EXPECTED_DIGESTS_AND_ACLS_MATCH",
        },
    }


def https_fixture(path, context, timeout):
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert path in {"/pwa/", "/api/orqevia/intelligence/health"}
    assert 0 < timeout <= 3
    return 200, b'{"ok":true,"observation_count":10}' if path.endswith("/health") else b"ORQEVIA"


def collect(context, tmp_path, *, runner=None, previous=None, canary=None):
    return producer.collect(
        context,
        runner=runner or FakeRunner(),
        budget=producer.Budget(),
        now=NOW,
        previous=previous,
        canary=canary,
        archive_root=tmp_path,
        reader=https_fixture,
        tls_context=ssl.create_default_context(),
    )


def test_actual_inventory_and_timestamp_contract(context, tmp_path):
    runner = FakeRunner()
    report = collect(context, tmp_path, runner=runner)
    assert set(producer.SERVICES) == set(SERVICE_SPECS)
    assert all(checks == SERVICE_SPECS[name][2] for name, (_, checks) in producer.SERVICES.items())
    assert len(report["services"]) == 9
    backend = report["services"][0]
    assert backend["health_observed_at"] == producer.iso(NOW - 20)
    assert backend["checks"][1]["observed_at"] == producer.iso(NOW - 15)
    assert report["services"][4]["checks"][0]["observed_at"] == producer.iso(NOW - 10)
    assert report["services"][5]["checks"][0]["observed_at"] == producer.iso(NOW - 12)
    assert all(row["status"] == "PASS" for row in report["collector_checks"])
    assert all("generate" not in arg and "get-secret" not in arg for call in runner.calls for arg in call)
    assert ".Env" not in producer.INSPECT_FORMAT and ".Output" not in producer.INSPECT_FORMAT


def test_process_and_db_read_do_not_invent_worker_or_tunnel_readiness(context, tmp_path):
    report = collect(context, tmp_path, runner=FakeRunner(worker=False))
    backend = report["services"][0]["checks"][1]
    assert backend["status"] == "UNKNOWN"
    assert backend["reason"] == "WORKER_HEARTBEAT_NOT_EXPOSED"
    for service in report["services"][-3:]:
        assert service["process_state"] == "running"
        assert service["checks"][-1]["status"] == "NOT_CONFIGURED"
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    projected = operational_health_snapshot(receipt_path=path, data_dir=tmp_path / "data", now=NOW)
    assert projected["critical_issues"]["critical_count"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("host_id", "other-host"),
        ("boot_id", "bad-boot"),
        ("captured_at", NOW - 121),
        ("cadence_seconds", 600),
        ("captured_at", float("nan")),
    ],
)
def test_host_identity_and_original_freshness_are_required(context, tmp_path, field, value):
    context["host_receipt"][field] = value
    report = collect(context, tmp_path)
    assert any(row["status"] != "PASS" for row in report["collector_checks"])


def test_otel_current_namespace_is_required():
    metadata = {
        producer.SERVICES["backend"][0]: {"container_id": "new-backend"},
        producer.SERVICES["otel-collector"][0]: {"network_mode": "container:old-backend"},
    }
    row = producer.otel_check(metadata, producer.iso(NOW - 1) + ' {"otelcol.signal": "metrics", "data points": 9}', NOW)
    assert row["status"] == "FAIL"
    assert row["reason"] == "OTEL_BACKEND_NAMESPACE_MISMATCH"


def test_missing_namespace_metadata_is_unavailable_without_asserting_a_mismatch():
    metadata = {producer.SERVICES["backend"][0]: {"container_id": "current-backend"}}
    row = producer.otel_check(metadata, "", NOW)
    assert row["status"] == "UNKNOWN"
    assert row["reason"] == "OTEL_NAMESPACE_OBSERVATION_UNAVAILABLE"


def test_no_healthcheck_metadata_survives_an_unrelated_malformed_record():
    name = producer.SERVICES["otel-collector"][0]
    raw = "partial invalid JSON\n" + json.dumps(
        {"name": "/" + name, "network_mode": "container:current-backend", "docker_health": None}
    )
    metadata = producer.inspect_metadata(raw)
    metadata[producer.SERVICES["backend"][0]] = {"container_id": "current-backend"}
    exported = producer.iso(NOW - 1) + ' {"otelcol.signal": "metrics", "data points": 9}'
    row = producer.otel_check(metadata, exported, NOW)
    assert row["status"] == "PASS"
    assert row["observed_at"] == producer.iso(NOW - 1)


def test_https_verification_failure_has_no_plaintext_fallback(context):
    calls = []

    def failed(path, tls_context, timeout):
        calls.append(path)
        raise urllib.error.URLError(ssl.SSLCertVerificationError("fixture"))

    row = producer.tls_check("interface-https", "/pwa/", ssl.create_default_context(), producer.Budget(), reader=failed)
    assert calls == ["/pwa/"]
    assert row["status"] == "FAIL" and row["certificate_verified"] is False
    assert row["source"] == "https://localhost:8443/pwa/"


def test_original_canary_and_history_are_not_redated(context, tmp_path):
    passed = {
        "schema_version": "orqevia.full-stack-canary.v1",
        "checks": [{"name": "deployment-identity", "status": "PASS", "observed_at": producer.iso(NOW - 1200)}],
    }
    failed = {
        "schema_version": "orqevia.full-stack-canary.v1",
        "observed_at_utc": producer.iso(NOW - 600),
        "checks": [{"name": "deployment-identity", "status": "FAIL", "observed_at": producer.iso(NOW - 610)}],
    }
    (tmp_path / "FULL-STACK-CANARY-01.json").write_text(json.dumps(passed), encoding="utf-8")
    (tmp_path / "FULL-STACK-CANARY-02.json").write_text(json.dumps(failed), encoding="utf-8")
    original = copy.deepcopy(failed)
    report = collect(context, tmp_path, canary=failed)
    assert report["canary"] == original
    assert report["canary_check_history"]["deployment-identity"] == {
        "last_success_at": producer.iso(NOW - 1200),
        "first_failure_at": producer.iso(NOW - 610),
    }


def test_unknown_interval_preserves_first_failure_until_real_recovery():
    previous = {
        "services": [
            {
                "service_id": "interface",
                "checks": [
                    {
                        "check_id": "interface-https",
                        "status": "UNKNOWN",
                        "last_success_at": producer.iso(NOW - 200),
                        "first_failure_at": producer.iso(NOW - 100),
                    }
                ],
            }
        ]
    }
    report = {
        "services": [
            {
                "service_id": "interface",
                "checks": [
                    producer.check(
                        "interface-https", "HTTPS_READINESS", "FAIL", producer.iso(NOW), "FIXTURE", "fixture", "FIXTURE"
                    )
                ],
            }
        ]
    }
    producer.merge_check_history(report, previous)
    assert report["services"][0]["checks"][0]["first_failure_at"] == producer.iso(NOW - 100)


def test_atomic_publication_replaces_complete_json_and_leaves_no_tempfile(tmp_path):
    path = tmp_path / "operational-health.json"
    producer.atomic_write(path, {"old": True})
    producer.atomic_write(path, {"new": True})
    assert json.loads(path.read_bytes()) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


def test_budget_does_not_start_another_operation_after_expiry(monkeypatch):
    monkeypatch.setattr(producer.time, "monotonic", lambda: 100)
    budget = producer.Budget(seconds=1)
    monkeypatch.setattr(producer.time, "monotonic", lambda: 102)
    with pytest.raises(TimeoutError):
        budget.remaining(3)
