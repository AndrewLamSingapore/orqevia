import asyncio
import pytest
from unittest.mock import Mock

from app.inference_boundary import InferenceBoundaryError, worker_call, require_worker_call
from app.model_gateway import ModelGateway
from app.hybrid_memory import HybridMemory
from app import main, compute_queue_api
from app.job_queue import Provider
from dataclasses import replace


def test_all_legacy_network_sinks_deny_before_transport(monkeypatch):
    transport = Mock(side_effect=AssertionError("network reached"))
    monkeypatch.setattr("urllib.request.urlopen", transport)
    monkeypatch.setattr("httpx.AsyncClient", transport)
    # No environment flag or credentials can turn these legacy sinks back on.
    monkeypatch.setenv("PRIME_HARNESS_PILOT_ENABLED", "0")
    for operation in (
        lambda: ModelGateway._post("https://invalid", {}, {}, 1),
        lambda: HybridMemory._embed(None, "query"),
        lambda: asyncio.run(main.ollama_post("/api/chat", {})),
        lambda: asyncio.run(main.embed_one("query")),
        lambda: asyncio.run(main.embed_many(["query"])),
    ):
        with pytest.raises(InferenceBoundaryError):
            operation()
    transport.assert_not_called()


def test_raw_executor_has_no_direct_or_cloud_bypass(monkeypatch):
    transport = Mock(side_effect=AssertionError("network reached"))
    monkeypatch.setattr("httpx.Client", transport)
    job = {"id": "untrusted"}
    local = Provider("ollama-fast", "local", "fake", 8192, 0, 1)
    with pytest.raises(InferenceBoundaryError):
        compute_queue_api._infer(job, local)
    with worker_call(job):
        with pytest.raises(InferenceBoundaryError):
            compute_queue_api._infer(job, Provider("cloud", "cloud", "fake", 8192, 0, 1))
    transport.assert_not_called()


def test_legacy_code_runner_never_launches_a_process(monkeypatch):
    launch = Mock(side_effect=AssertionError("unmediated process"))
    monkeypatch.setattr(main.subprocess, "run", launch)
    with pytest.raises(InferenceBoundaryError):
        main.run_python("print(1)")
    launch.assert_not_called()


@pytest.mark.parametrize("endpoint", ["http://localhost:11434", "http://host.docker.internal:11434", "https://cloud.invalid", "http://ollama:11434@cloud.invalid"])
def test_native_or_external_endpoint_cannot_expand_authority(monkeypatch, endpoint):
    transport = Mock(side_effect=AssertionError("unmediated provider reached"))
    monkeypatch.setattr("httpx.Client", transport)
    monkeypatch.setattr(compute_queue_api, "SETTINGS", replace(compute_queue_api.SETTINGS, ollama_base_url=endpoint))
    job = {"id": "synthetic-test-only"}
    with worker_call(job):
        with pytest.raises(InferenceBoundaryError, match="isolated Docker"):
            compute_queue_api._infer(job, Provider("ollama-fast", "local", "fake", 8192, 0, 1))
    transport.assert_not_called()


def test_worker_scope_is_identity_bound_one_use_and_cleared():
    job = {"id": "one"}
    with worker_call(job):
        with pytest.raises(InferenceBoundaryError):
            require_worker_call(dict(job))
        require_worker_call(job)
        with pytest.raises(InferenceBoundaryError):
            with worker_call({"id": "nested"}):
                pass
        with pytest.raises(InferenceBoundaryError):
            require_worker_call(job)
    with pytest.raises(InferenceBoundaryError):
        require_worker_call(job)
