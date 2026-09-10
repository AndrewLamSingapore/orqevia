from unittest.mock import Mock
from dataclasses import replace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import harness_api, compute_queue_api
from app.deterministic_compute import assess
from app.inference_boundary import worker_call, InferenceBoundaryError
from app.job_queue import Provider


@pytest.mark.parametrize("prompt", ["hello", "do anything", "choose a model", "run a transfer", "review 2+2", "invent an authority", ""])
def test_unknown_work_does_not_imply_inference_need(prompt):
    route = assess(prompt)
    assert route.resolution_path == "reject"
    assert route.reason_code == "INFERENCE_NEED_NOT_ESTABLISHED"


def test_unknown_request_rejects_before_issuer_or_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-only")
    monkeypatch.setenv("PRIME_COMPUTE_DB", str(tmp_path / "compute.db"))
    issuer = Mock(side_effect=AssertionError("issuer reached"))
    monkeypatch.setattr(harness_api, "_runtime", issuer)
    app = FastAPI()
    app.include_router(harness_api.router)
    response = TestClient(app).post("/api/harness/intent", headers={"Authorization":"Bearer fixture-only"}, json={"intent":"do anything"})
    assert response.status_code == 422
    assert response.json()["model_invocations"] == 0
    assert response.json()["routing"]["reason_code"] == "INFERENCE_NEED_NOT_ESTABLISHED"
    issuer.assert_not_called()


def test_provider_rechecks_unknown_work_even_inside_worker_scope(monkeypatch):
    monkeypatch.setattr(compute_queue_api, "SETTINGS", replace(compute_queue_api.SETTINGS, ollama_base_url="http://ollama:11434"))
    transport = Mock(side_effect=AssertionError("transport reached"))
    monkeypatch.setattr(compute_queue_api.httpx, "Client", transport)
    job = {"id":"fixture", "prompt":"do anything", "timeout_seconds":5}
    with worker_call(job), pytest.raises(InferenceBoundaryError, match="deterministic feasibility forbids"):
        compute_queue_api._infer(job, Provider("local", "local", "fixture", 8192, 0, 1))
    transport.assert_not_called()
