import hashlib
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import compute_queue_api, harness_api, spine_api
from app.compute_ledger import ComputeLedger
from app.deterministic_compute import assess
from app.inference_boundary import InferenceBoundaryError, worker_call
from app.job_queue import JobQueue, Provider, QueuePolicy
from app.spine import SpineStore, StableSpine


@pytest.mark.parametrize("prompt,result", [
    ("calculate 0.1 + 0.2", "3/10"), ("What is (12 + 4) / 2?", "8"),
    ("2/3 + 1/3", "1"), ("compute -2 * (3 + 4)", "-14"),
    ("sha256 text: abc", hashlib.sha256(b"abc").hexdigest()),
    ("sha256 text: abc\n", hashlib.sha256(b"abc\n").hexdigest()),
])
def test_exact_contracts(prompt, result):
    route = assess(prompt)
    assert route.resolution_path == "deterministic"
    assert route.result == result


@pytest.mark.parametrize("prompt", [
    "calculate 1/0", "calculate 2**100000000", "calculate 1 + __import__('os').system('x')",
    "calculate 1+2 then transfer funds", "calculate " + "1+" * 600 + "1",
    "calculate " + "(" * 300 + "1" + ")" * 300,
])
def test_invalid_exact_contract_never_falls_back_to_a_model(prompt):
    assert assess(prompt).resolution_path == "reject"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "test-owner-token")
    monkeypatch.setenv("PRIME_COMPUTE_DB", str(tmp_path / "compute.db"))
    monkeypatch.setenv("PRIME_HARNESS_DB", str(tmp_path / "harness.db"))
    monkeypatch.setenv("PRIME_HARNESS_PILOT_ENABLED", "1")
    monkeypatch.setattr(harness_api, "_runtime_cache", None)
    monkeypatch.setattr(harness_api, "_runtime_fingerprint", None)
    monkeypatch.setattr(spine_api, "spine", StableSpine(SpineStore(str(tmp_path / "spine.db"))))
    monkeypatch.setattr(compute_queue_api, "queue", JobQueue(tmp_path / "queue.db", QueuePolicy()))
    app = FastAPI()
    app.include_router(harness_api.router)
    return TestClient(app), {"Authorization": "Bearer test-owner-token"}


def test_deterministic_completion_offline_without_issuer_or_worker(api, monkeypatch):
    client, headers = api
    forbidden = Mock(side_effect=AssertionError("inference or authority issuer reached"))
    monkeypatch.setattr(harness_api, "_runtime", forbidden)
    monkeypatch.setattr(compute_queue_api, "_infer", forbidden)
    response = client.post("/api/harness/intent", headers=headers, json={"intent": "calculate 6*7"})
    assert response.status_code == 200
    assert response.json()["result"] == "42"
    assert response.json()["model_invocations"] == 0
    assert not response.json()["action_authority"]
    forbidden.assert_not_called()
    assert compute_queue_api.queue.list() == []
    ledger = ComputeLedger()
    assert ledger.summary()["accounting"]["confirmed_model_invocations"] == 0
    event = ledger.recent()[0]
    assert "calculate" not in str(event)
    assert event["input_units"] == 0


@pytest.mark.parametrize("intent,actor", [
    ("Review architecture tradeoffs", "a16"),
    ("Inspect duplicate dataset identifiers", "a14"), ("Assess model cost", "a21"),
])
def test_intent_selects_one_role_and_uses_existing_signed_queue(api, intent, actor):
    client, headers = api
    response = client.post("/api/harness/intent", headers=headers, json={"intent": intent})
    assert response.status_code == 202, response.text
    job = compute_queue_api.queue.list()[0]
    assert job["agent"] == actor
    assert job["authorization_envelope"]
    assert response.json()["routing"]["resolution_path"] == "local_inference"
    assert len(compute_queue_api.queue.list()) == 1


def test_exact_requests_cannot_force_a_model_through_pilot(api):
    client, headers = api
    response = client.post("/api/harness/pilot/dispatch", headers=headers,
                           json={"actor_id": "a16", "prompt": "calculate 2+2", "model_role": "deep"})
    assert response.status_code == 200
    assert response.json()["model_invocations"] == 0
    assert compute_queue_api.queue.list() == []


def test_invalid_exact_request_and_missing_auth_never_enqueue(api):
    client, headers = api
    assert client.post("/api/harness/intent", json={"intent": "2+2"}).status_code == 401
    response = client.post("/api/harness/intent", headers=headers, json={"intent": "calculate 1/0"})
    assert response.status_code == 422
    assert response.json()["routing"]["resolution_path"] == "reject"
    assert compute_queue_api.queue.list() == []


def test_routing_ledger_failure_does_not_fall_back_to_inference(api, monkeypatch):
    client, headers = api
    monkeypatch.setattr(harness_api, "ComputeLedger", Mock(side_effect=OSError("unavailable")))
    assert client.post("/api/harness/intent", headers=headers, json={"intent": "2+2"}).status_code == 503
    assert compute_queue_api.queue.list() == []


def test_consumed_job_still_cannot_force_deterministic_work_into_provider(monkeypatch):
    monkeypatch.setattr(compute_queue_api, "SETTINGS", replace(compute_queue_api.SETTINGS, ollama_base_url="http://ollama:11434"))
    network = Mock(side_effect=AssertionError("transport reached"))
    monkeypatch.setattr(compute_queue_api.httpx, "Client", network)
    job = {"id": "test", "prompt": "2+2"}
    with worker_call(job), pytest.raises(InferenceBoundaryError, match="feasibility"):
        compute_queue_api._infer(job, Provider("ollama-fast", "local", "fake", 8192, 0, 1))
    network.assert_not_called()


@pytest.mark.parametrize("usage", [{}, {"prompt_eval_count": None, "eval_count": -2},
                                  {"prompt_eval_count": True, "eval_count": "n/a"}])
def test_missing_or_invalid_provider_usage_stays_unknown(tmp_path, monkeypatch, usage):
    monkeypatch.setenv("PRIME_COMPUTE_DB", str(tmp_path / "compute.db"))
    monkeypatch.setattr(compute_queue_api, "SETTINGS", replace(compute_queue_api.SETTINGS, ollama_base_url="http://ollama:11434"))
    response = Mock()
    response.json.return_value = {"message": {"content": "advisory"}, **usage}
    client = Mock()
    client.post.return_value = response
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(compute_queue_api.httpx, "Client", Mock(return_value=context))
    job = {"id": "test", "prompt": "Review design", "agent": "a16", "model_role": "auto", "timeout_seconds": 5}
    with worker_call(job):
        result = compute_queue_api._infer(job, Provider("ollama-fast", "local", "fake", 8192, 0, 1))
    assert result["input_tokens"] is None and result["output_tokens"] is None
    summary = ComputeLedger().summary()
    assert summary["groups"][0]["input_units"] is None
    assert not summary["groups"][0]["output_usage_complete"]
    assert summary["accounting"]["confirmed_model_invocations"] == 1


def test_queue_preserves_unknown_tokens_after_completion(tmp_path):
    queue = JobQueue(tmp_path / "q.db", QueuePolicy())
    provider = Provider("ollama-fast", "local", "fake", 8192, 0, 1)
    job = queue.submit(agent="a16", prompt="Review")
    assert queue.claim("worker", [provider])
    completed = queue.finish(job["id"], result="advisory")
    assert completed["input_tokens"] is None
    assert completed["output_tokens"] is None


def test_failed_provider_attempt_is_audited_without_claiming_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIME_COMPUTE_DB", str(tmp_path / "compute.db"))
    monkeypatch.setattr(compute_queue_api, "SETTINGS", replace(compute_queue_api.SETTINGS, ollama_base_url="http://ollama:11434"))
    monkeypatch.setattr(compute_queue_api.httpx, "Client", Mock(side_effect=TimeoutError("PRIVATE RESPONSE")))
    job = {"id": "test", "prompt": "Review design", "agent": "a16", "model_role": "auto", "timeout_seconds": 5}
    with worker_call(job), pytest.raises(TimeoutError):
        compute_queue_api._infer(job, Provider("ollama-fast", "local", "fake", 8192, 0, 1))
    ledger = ComputeLedger()
    event = ledger.recent()[0]
    assert not event["success"]
    assert event["input_units"] is None
    assert "PRIVATE RESPONSE" not in str(event)
    accounting = ledger.summary()["accounting"]
    assert accounting["confirmed_model_invocations"] == 0
    assert accounting["unknown_model_invocations"] == 1
    assert accounting["model_attempts"] == 1
