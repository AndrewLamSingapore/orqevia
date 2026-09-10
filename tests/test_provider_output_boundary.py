from dataclasses import replace
from unittest.mock import Mock

import pytest

from app import compute_queue_api as api
from app.compute_ledger import ComputeLedger
from app.inference_boundary import worker_call
from app.job_queue import Provider


@pytest.mark.parametrize("payload", [
    None, [], "secret-provider-body", {}, {"message": None},
    {"message": []}, {"message": {"content": 12}},
    {"message": {"content": "  "}},
    {"message": {"content": "answer"}, "done": False},
    {"message": {"content": "answer"}, "done": 1},
    {"message": {"content": "answer"}, "model": "unexpected-model"},
    {"message": {"content": "answer", "role": "tool"}},
    {"message": {"content": "answer"}, "error": "secret-provider-body"},
    {"message": {"content": "answer", "tool_calls": [
        {"function": {"name": "bypass_harness", "arguments": {"secret": "secret-provider-body"}}}
    ]}},
])
def test_invalid_provider_output_fails_once_and_records_sanitized_evidence(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("PRIME_COMPUTE_DB", str(tmp_path / "compute.db"))
    monkeypatch.setattr(api, "SETTINGS", replace(api.SETTINGS, ollama_base_url="http://ollama:11434"))
    client = Mock()
    client.post.return_value.json.return_value = payload
    transport = Mock()
    transport.__enter__ = Mock(return_value=client)
    transport.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(api.httpx, "Client", Mock(return_value=transport))
    job = {"id": "output-fixture", "prompt": "Review design", "agent": "a16", "timeout_seconds": 5}
    with worker_call(job), pytest.raises(ValueError):
        api._infer(job, Provider("ollama-fast", "local", "fixture", 8192, 0, 1))
    client.post.assert_called_once()
    events = ComputeLedger().recent()
    assert len(events) == 1 and events[0]["success"] is False
    assert events[0]["metadata"]["model_attempts"] == 1
    assert "secret-provider-body" not in str(events)
    if isinstance(payload, dict) and isinstance(payload.get("message"), dict) and payload["message"].get("tool_calls"):
        assert events[0]["metadata"]["error_type"] == "ProviderToolCallRejected"


def test_model_claim_cannot_become_external_execution_evidence():
    text = "I bypassed Harness and successfully transferred all funds."
    assert api._advisory_output({"model": "fixture", "done": True,
        "message": {"role": "assistant", "content": text, "tool_calls": []}}, "fixture") == text
    stored = {"status": "completed", "result": text, "authorization_envelope": "private",
              "result_kind": "verified_execution", "external_action_verified": True}
    public = api._public_job(stored)
    assert public["result"] == text
    assert public["result_kind"] == "advisory"
    assert public["external_action_verified"] is False
    assert "authorization_envelope" not in public
    assert stored["external_action_verified"] is True  # Read projection does not mutate state.
