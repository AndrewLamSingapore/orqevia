"""Exercise the container smoke driver against real HTTP routes and worker PEP."""
import hashlib
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cognitive_api, compute_queue_api, harness_api, spine_api
from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from app.spine import SpineStore, StableSpine
from scripts.verify_harness_release_smoke import read_evidence, run_smoke


def test_packaged_dispatch_worker_and_audit_contract(tmp_path, monkeypatch):
    token = "isolated-release-smoke-token"
    monkeypatch.setenv("PRIME_SPINE_TOKEN", token)
    monkeypatch.setenv("PRIME_HARNESS_PILOT_ENABLED", "1")
    monkeypatch.delenv("PRIME_HARNESS_SIGNING_SECRET", raising=False)
    monkeypatch.setenv("PRIME_HARNESS_DB", str(tmp_path / "action-harness.db"))
    monkeypatch.setattr(harness_api, "_runtime_cache", None)
    monkeypatch.setattr(harness_api, "_runtime_fingerprint", None)
    spine_path = str(tmp_path / "spine.db")
    monkeypatch.setattr(spine_api, "spine", StableSpine(SpineStore(spine_path)))
    queue = JobQueue(tmp_path / "compute-queue.db", QueuePolicy(global_concurrency=1))
    monkeypatch.setattr(compute_queue_api, "queue", queue)
    infer = Mock(return_value={"result": "bounded fixture output", "input_tokens": 12,
                              "output_tokens": 18, "actual_cost_usd": 0})
    monkeypatch.setattr(compute_queue_api, "_infer", infer)
    legacy = Mock(side_effect=AssertionError("legacy inference must never start"))
    monkeypatch.setattr(cognitive_api.orchestrator, "execute", legacy)
    monkeypatch.setattr(cognitive_api.multi, "run", legacy)
    app = FastAPI()
    for router in (harness_api.router, compute_queue_api.router, cognitive_api.router):
        app.include_router(router)
    worker = WorkerPool(queue, [Provider("ollama-fast", "local", "fixture", 8192, 0, 1)], compute_queue_api._execute)
    worker.start()
    try:
        with TestClient(app) as client:
            def request(path, body=None):
                response = client.request("GET" if body is None else "POST", path,
                    json=body, headers={"Authorization": "Bearer " + token})
                return response.status_code, response.json()
            run_smoke(request, lambda job: read_evidence(tmp_path, spine_path, job),
                      hashlib.sha256(b"JARVIS-HARNESS-V0\0" + token.encode()).digest())
        infer.assert_called_once()
        legacy.assert_not_called()
    finally:
        worker.stop()


def test_legacy_rejection_precedes_any_planning_or_specialist_work(monkeypatch):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "isolated-test-token")
    monkeypatch.setenv("PRIME_HARNESS_PILOT_ENABLED", "1")
    legacy = Mock(side_effect=AssertionError("legacy work started"))
    monkeypatch.setattr(cognitive_api.orchestrator, "execute", legacy)
    monkeypatch.setattr(cognitive_api.multi, "run", legacy)
    app = FastAPI()
    app.include_router(cognitive_api.router)
    with TestClient(app) as client:
        for path in ("/api/cognitive/reason", "/api/cognitive/multi-reason"):
            assert client.post(path, json={"intent": "any identity"}).status_code == 401
            assert client.post(path, json={"intent": "any identity"},
                headers={"Authorization": "Bearer isolated-test-token"}).status_code == 409
    legacy.assert_not_called()
