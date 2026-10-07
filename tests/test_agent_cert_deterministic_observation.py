"""Pure fixture joins, not live execution, grades or certification evidence."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case


SOURCE = "d" * 40
REGISTRY = "b" * 64
TASK = "11111111-1111-4111-8111-111111111111"
ARTIFACT = "a" * 32
BEGIN = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


def fixture():
    report = {
        "schema_version": "jarvis.runtime-status.v1", "task_id": TASK,
        "captured_at": (BEGIN + timedelta(milliseconds=100)).isoformat(),
        "prime_health": {"observation": "UNAVAILABLE", "status": "UNKNOWN"},
        "registry": {"status": "OBSERVED", "agent_count": 21,
                     "registry_version": "1.0.0", "source_sha256": REGISTRY},
        "tasks": {"status": "UNAVAILABLE", "count": None, "active_count": None},
        "qualified_compute": {"status": "UNAVAILABLE", "execution_backends": {}},
        "protocol": {"interface_contract": "jarvis.interface.v1"},
        "execution": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "method": "DETERMINISTIC_READ_ONLY", "fresh_inference_performed": False},
    }
    raw = json.dumps(report).encode()
    metadata = {
        "artifact_id": ARTIFACT, "task_id": TASK, "type": "json",
        "creator_agents": ["a19"], "timestamp":
        (BEGIN + timedelta(milliseconds=200)).isoformat(), "version": "1.0.0",
        "provenance": "Deterministic computation; zero model calls",
        "runtime_revision": SOURCE, "validation_state": "STRUCTURE_VALIDATED",
        "content_validation": "Not independently established by structural validation",
        "location": "artifact.json", "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "delivery_state": "AVAILABLE",
    }
    reply = {"task_id": TASK, "state": "COMPLETED", "artifact": copy.deepcopy(metadata),
             "model_calls": 0, "execution_model": "DETERMINISTIC", "agent_id": "a19",
             "capability": "responsibility.a19", "runtime_source_revision": SOURCE}
    runtime = {"host_id": "ABEX", "source_revision": SOURCE, "version": "4.0.0",
               "image_digest": "sha256:" + "e" * 64}
    return report, raw, metadata, reply, runtime


def run(*, spec=None, report_changes=None, metadata_changes=None, reply_changes=None,
        retrieved_changes=None, runtime_changes=None, after_changes=None, raw_override=None,
        callback_error=False, options=None):
    report, raw, metadata, reply, runtime = fixture()
    if report_changes:
        report.update(report_changes)
        raw = json.dumps(report).encode()
    if raw_override is not None:
        raw = raw_override
    metadata.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    metadata.update(metadata_changes or {})
    reply["artifact"] = copy.deepcopy(metadata)
    reply.update(reply_changes or {})
    retrieved = copy.deepcopy(metadata)
    retrieved.update(retrieved_changes or {})
    runtime.update(runtime_changes or {})
    after = {**runtime, **(after_changes or {})}
    runtimes = iter((runtime, after))
    times = iter((BEGIN, BEGIN + timedelta(seconds=1)))
    calls = []

    def dispatch(request):
        calls.append("authenticated_dispatch")
        return reply

    def artifact(artifact_id):
        calls.append(("authenticated_artifact_read", artifact_id))
        if callback_error:
            raise PermissionError("sensitive credential and raw context must never be returned")
        return retrieved, raw

    def no_queue(job_id):
        raise AssertionError("deterministic artifact has no queue job")

    kwargs = dict(dispatch=dispatch, get_job=no_queue, get_artifact=artifact,
                  get_runtime=lambda: next(runtimes), expected_source_revision=SOURCE,
                  expected_registry_sha256=REGISTRY, wall_clock=lambda: next(times),
                  monotonic=lambda: 0, timeout_seconds=1)
    kwargs.update(options or {})
    return observe_cert_case(spec or challenge("baseline:identity", agent_id="a19"), **kwargs), calls


def test_completed_runtime_artifact_is_observed_without_fabricating_a_queue_job():
    observation, calls = run()
    assert observation["state"] == "EXECUTED"
    assert observation["case_review"] == "RUNTIME_STATUS_ARTIFACT_CHECK_PASS"
    assert observation["certification"] == "UNVERIFIED"
    assert observation["source_revision"] == SOURCE
    assert observation["registry_sha256"] == REGISTRY
    assert observation["task_id"] == TASK and observation["artifact_id"] == ARTIFACT
    assert observation["result_sha256"] == fixture()[2]["sha256"]
    assert observation["model_calls"] == 0
    assert "job_id" not in observation and "result" not in observation
    assert "prime_health" not in observation and "qualified_compute" not in observation
    assert calls == ["authenticated_dispatch", ("authenticated_artifact_read", ARTIFACT)]


@pytest.mark.parametrize("options", [
    {"get_artifact": None}, {"get_runtime": None}, {"expected_source_revision": "UNKNOWN"},
    {"expected_registry_sha256": None}, {"expected_source_revision": True},
    {"wall_clock": lambda: datetime(2026, 10, 7)},
])
def test_missing_readers_or_source_provenance_fail_before_dispatch(options):
    observation, calls = run(options=options)
    assert observation["state"] == "REJECTED"
    assert calls == []


@pytest.mark.parametrize("runtime_changes", [
    {"source_revision": "f" * 40}, {"image_digest": None}, {"host_id": "UNKNOWN"},
    {"version": "UNKNOWN"}, {"image_digest": "not-an-image"}, {"host_id": ["ABEX"]},
])
def test_unknown_or_mismatched_runtime_identity_never_executes(runtime_changes):
    observation, calls = run(runtime_changes=runtime_changes)
    assert observation["reason"] == "runtime_identity_missing"
    assert calls == []


@pytest.mark.parametrize("after_changes", [
    {"source_revision": "f" * 40}, {"image_digest": "sha256:" + "f" * 64},
    {"host_id": "OTHER"}, {"version": "4.0.1"},
])
def test_runtime_change_during_observation_is_not_accepted(after_changes):
    observation, _ = run(after_changes=after_changes)
    assert observation["state"] == "REJECTED"
    assert observation["reason"] == "runtime_identity_changed"


@pytest.mark.parametrize("reply_changes", [
    {"model_calls": False}, {"model_calls": 1}, {"execution_model": "MODEL"},
    {"state": "completed"}, {"job": {"id": TASK, "agent": "a19"}},
    {"agent_id": "a18"}, {"capability": "responsibility.a18"},
    {"runtime_source_revision": "f" * 40},
])
def test_deterministic_dispatch_must_be_literal_and_have_no_queue_alias(reply_changes):
    observation, calls = run(reply_changes=reply_changes)
    assert observation["state"] == "REJECTED"
    assert observation["reason"] == "deterministic_dispatch_invalid"
    assert calls == ["authenticated_dispatch"]


@pytest.mark.parametrize("metadata_changes", [
    {"task_id": "22222222-2222-4222-8222-222222222222"}, {"creator_agents": ["a18"]},
    {"creator_agents": ["a19", "a26"]}, {"type": "markdown"},
    {"runtime_revision": "UNKNOWN"}, {"runtime_revision": "f" * 40},
    {"sha256": "f" * 64}, {"bytes": True}, {"bytes": 0},
    {"delivery_state": "MISSING"}, {"validation_state": "PASS"},
    {"location": "../private.json"},
])
def test_artifact_task_creator_source_integrity_and_delivery_are_bound(metadata_changes):
    observation, _ = run(metadata_changes=metadata_changes)
    assert observation["state"] == "REJECTED"
    assert observation["reason"] == "artifact_binding_mismatch"


def test_retrieved_metadata_must_equal_dispatch_metadata_not_only_share_a_hash():
    observation, _ = run(retrieved_changes={"provenance": "different provenance"})
    assert observation["reason"] == "artifact_binding_mismatch"


@pytest.mark.parametrize("report_changes", [
    {"task_id": "22222222-2222-4222-8222-222222222222"},
    {"registry": {"status": "OBSERVED", "agent_count": True, "source_sha256": REGISTRY}},
    {"registry": {"status": "OBSERVED", "agent_count": 29, "source_sha256": REGISTRY}},
    {"registry": {"status": "OBSERVED", "agent_count": 21, "source_sha256": "f" * 64}},
    {"captured_at": (BEGIN - timedelta(seconds=1)).isoformat()},
    {"captured_at": BEGIN.replace(tzinfo=None).isoformat()},
    {"execution": {"model_calls": False, "input_tokens": 0, "output_tokens": 0,
                   "method": "DETERMINISTIC_READ_ONLY", "fresh_inference_performed": False}},
    {"execution": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                   "method": "DETERMINISTIC_READ_ONLY", "fresh_inference_performed": 0}},
])
def test_self_consistent_tampered_report_fails_exact_identity_and_zero_call_contract(report_changes):
    observation, _ = run(report_changes=report_changes)
    assert observation["state"] == "REJECTED"
    assert observation["reason"] == "runtime_report_binding_mismatch"


@pytest.mark.parametrize("raw", [b'{"task_id":"one","task_id":"two"}',
                                  b'{"bad":NaN}', b"not-json", b"x" * 200_001],
                         ids=("duplicate", "nonfinite", "malformed", "oversized"))
def test_duplicate_nonfinite_malformed_and_oversized_reports_cannot_pass(raw):
    observation, _ = run(raw_override=raw)
    assert observation["state"] != "EXECUTED"
    assert "bad" not in observation and "raw" not in observation


def test_dependency_authentication_failure_returns_no_secret_or_raw_context():
    observation, _ = run(callback_error=True)
    assert observation["state"] == "INCOMPLETE"
    assert observation["reason"] == "dependency_failed"
    assert "sensitive" not in json.dumps(observation)


def test_changed_case_context_or_borrowed_a19_case_cannot_receive_artifact_verdict():
    spec = challenge("baseline:identity", agent_id="a19")
    spec["request"]["context"] = "changed source context"
    observation, calls = run(spec=spec)
    assert observation["reason"] == "runtime_case_source_mismatch"
    assert calls == []


def test_elapsed_observation_retains_incomplete_not_completion():
    ticks = iter((0, 0, 2))
    observation, _ = run(options={"monotonic": lambda: next(ticks)})
    assert observation["state"] == "INCOMPLETE"
    assert observation["reason"] == "bounded_timeout"


def test_future_artifact_timestamp_cannot_be_accepted():
    observation, _ = run(metadata_changes={"timestamp": (BEGIN + timedelta(seconds=2)).isoformat()})
    assert observation["state"] == "REJECTED"
    assert observation["reason"] == "observation_time_invalid"
