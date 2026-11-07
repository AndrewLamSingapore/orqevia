"""Actual queue observations must satisfy the bounded F08 HTTP contract."""

import hashlib
import json
import sqlite3
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import fabric_runtime as runtime
from app.job_queue import JobQueue, QueuePolicy

OWNER = "queue-metrics-regression-owner"
TOKEN = "queue-metrics-regression-fixture-authority"
PUBLIC_FIELDS = {"statuses", "running", "cloud_inflight", "daily_spend_usd", "policy"}
POLICY_FIELDS = {
    "global_concurrency",
    "per_agent_concurrency",
    "background_concurrency",
    "local_ram_mb",
    "local_vram_mb",
    "cloud_wait_seconds",
    "starvation_interval_seconds",
    "starvation_boost_per_interval",
    "starvation_boost_cap",
    "cloud_concurrency",
    "max_job_cost_usd",
    "daily_cost_ceiling_usd",
}


@pytest.fixture
def observed_queue(tmp_path, monkeypatch):
    for name, value in {
        "ORQEVIA_DATA_DIR": str(tmp_path),
        "ORQEVIA_COMPUTE_QUEUE_DB": str(tmp_path / "imported-queue.db"),
        "ORQEVIA_SPINE_TOKEN": TOKEN,
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": OWNER,
        "ORQEVIA_COLLECTIVE_ENABLED": "1",
        "ORQEVIA_OPEN_ACCESS": "1",
        "ORQEVIA_RUNTIME_REVISION": "f" * 40,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ORQEVIA_RESOURCE_GUARDIAN_PROFILE", raising=False)
    from app import compute_queue_api
    from app.collective_api import router

    queue = JobQueue(tmp_path / "observed-queue.db", QueuePolicy())
    queue.submit(agent="a01", prompt="Synthetic metrics fixture; no model executes.", max_retries=0)
    monkeypatch.setattr(compute_queue_api, "queue", queue)
    app = FastAPI()
    app.include_router(router)
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-ORQEVIA-Owner": hashlib.sha256(OWNER.encode()).hexdigest(),
        "X-ORQEVIA-Actor": "queue-metrics-regression",
    }
    with TestClient(app) as client:
        yield queue, client, headers, tmp_path


@pytest.mark.parametrize("future_extensions", [False, True])
def test_actual_queue_metrics_and_future_internals_fit_full_wire_contract(
    observed_queue, monkeypatch, future_extensions
):
    queue, client, headers, _ = observed_queue
    actual_metrics = queue.metrics
    expected = actual_metrics()
    assert expected["statuses"] == {"queued": 1}
    assert "inference_lifecycle" in expected and "resource_guardian" in expected
    assert {"coordinated", "max_waiting_jobs"} <= expected["policy"].keys()
    if future_extensions:

        def extended_metrics():
            observed = actual_metrics()
            observed["future_internal"] = {"private": "synthetic-unpublished-marker"}
            observed["policy"]["future_internal"] = {"private": "synthetic-unpublished-marker"}
            return observed

        monkeypatch.setattr(queue, "metrics", extended_metrics)

    url = "/api/collective/v1/fabrics/f08/execute"
    body = {"operation": "queue_metrics", "parameters": {}, "execution_id": str(uuid.uuid4())}
    assert client.post(url, json=body).status_code == 401
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200
    wire = response.json()
    receipt = wire["data"]
    result = receipt["result"]
    assert receipt["status"] == "COMPLETED"
    assert set(result) == PUBLIC_FIELDS
    assert set(result["policy"]) == POLICY_FIELDS
    assert result == {
        "statuses": expected["statuses"],
        "running": expected["running"],
        "cloud_inflight": expected["cloud_inflight"],
        "daily_spend_usd": expected["daily_spend_usd"],
        "policy": {key: expected["policy"][key] for key in POLICY_FIELDS},
    }
    assert "synthetic-unpublished-marker" not in response.text
    contract = runtime.executable_contracts()["f08"]
    # Validate the actual complete HTTP envelope, receipt and nested result,
    # including the closed response/policy schemas and all supported assertions.
    runtime._validate_output(wire, runtime.execution_response_schema("f08", contract))
    stored = client.get("/api/collective/v1/fabrics/executions/" + receipt["execution_id"], headers=headers)
    assert stored.status_code == 200 and stored.json()["data"] == receipt
    assert (
        receipt["result_sha256"]
        == hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "unavailable",
    ["missing_statuses", "missing_policy_field", "null_statuses", "null_policy_field", "null_policy"],
)
def test_required_queue_observation_never_becomes_default_or_success(observed_queue, monkeypatch, unavailable):
    queue, client, headers, tmp_path = observed_queue
    actual_metrics = queue.metrics

    def unavailable_metrics():
        observed = actual_metrics()
        if unavailable == "missing_statuses":
            observed.pop("statuses")
        elif unavailable == "missing_policy_field":
            observed["policy"].pop("cloud_concurrency")
        elif unavailable == "null_statuses":
            observed["statuses"] = None
        elif unavailable == "null_policy_field":
            observed["policy"]["global_concurrency"] = None
        else:
            observed["policy"] = None
        return observed

    monkeypatch.setattr(queue, "metrics", unavailable_metrics)
    identifier = str(uuid.uuid4())
    response = client.post(
        "/api/collective/v1/fabrics/f08/execute",
        headers=headers,
        json={"operation": "queue_metrics", "parameters": {}, "execution_id": identifier},
    )
    assert response.status_code == 503
    path = tmp_path / "fabric-runtime/executions.db"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT status,error_code,result_json,result_sha256 FROM executions WHERE execution_id=?", (identifier,)
        ).fetchone()
    assert row == ("FAILED", "OutputContractViolation", None, None)
