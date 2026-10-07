"""Strict queue-success error representation, using no live inference or signing.

The completed SQLite fixture is produced by the real JobQueue writer. All
authenticated runtime/reviewer bindings remain explicitly synthetic fixtures.
Raw error values are preserved in the execution evidence, never normalized.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.agent_cert_review_tool import RoleReviewError
from app.agent_registry import agent_record
from app.job_queue import JobQueue, Provider, QueuePolicy
from scripts.agent_cert_reviewed_signing import CertificationReviewError, _review
from tests import test_agent_cert_review_tool as review_fixture
from tests import test_agent_cert_reviewed_signing as signing_fixture
from tests import test_collect_agent_cert_case as collection_fixture


SUCCESS_ERRORS = (None, "")
INVALID_ERRORS = (False, 0, 0.0, " ", "\n", "upstream failed", [], {})


def row_for_collection(state, collected):
    review = json.loads(collected.review_bytes)
    return {
        "agent_id": state.agent, "capability_id": f"responsibility.{state.agent}",
        "dimension": "role", "test_case": "normal", "certification_test": "role-normal",
        "test_version": "1", "test_result": "PASS", "verifier": review["reviewer_identity"],
        "executor_identity": state.agent, "source_revision": collection_fixture.SOURCE,
        "review_source_revision": collection_fixture.SOURCE,
        "reviewer_code_revision": collection_fixture.CODE,
        "authority_scope": agent_record(state.agent)["authority"],
        "certified_at": collection_fixture.NOW.isoformat(),
        "last_revalidated": collection_fixture.NOW.isoformat(),
        "expires_at": (collection_fixture.NOW + timedelta(hours=1)).isoformat(),
        "review_run_id": review["review_run_id"],
        "review_test_version": review["review_test_version"],
    }


def review_collected(state, collected):
    options = {name: state.options.get(name) for name in (
        "cloud_binding", "cloud_policy", "expected_owner_policy_sha256")}
    return _review(row_for_collection(state, collected), collected.execution_bytes,
        collected.review_bytes, source_revision=collection_fixture.SOURCE,
        runtime_image_id=collection_fixture.IMAGE, reviewer_code_revision=collection_fixture.CODE,
        now=collection_fixture.NOW, **options)


@pytest.mark.parametrize("writer_error", SUCCESS_ERRORS)
def test_actual_queue_finish_success_retained_through_all_three_readers(
        tmp_path, monkeypatch, writer_error):
    # This is a temporary SQLite queue with a synthetic cloud provider. No
    # transport, worker thread, model, privileged telemetry or real state runs.
    queue = JobQueue(tmp_path / "synthetic-queue.db", QueuePolicy(cloud_wait_seconds=0))
    answer = json.dumps(collection_fixture._CASES["a19"][2])
    provider = Provider(collection_fixture.PROVIDER_ID, "cloud", collection_fixture.MODEL,
        ram_mb=0, vram_mb=0, concurrency=1, input_cost_per_mtok=0.08,
        output_cost_per_mtok=0.28, max_output_tokens=1024, explicit_selection_required=True)
    submitted = queue.submit(agent="a19", prompt="Bound public synthetic prompt",
        model=provider.model, preferred_provider=provider.name, allow_cloud=True,
        data_classification="CLOUD_PERMITTED", task_class="planning", max_retries=0,
        max_cost_usd=0.002, ram_mb=0)
    claimed = queue.claim("synthetic-worker", [provider])
    assert claimed is not None and claimed["id"] == submitted["id"]
    options = {} if writer_error == "" else {"error": None}
    completed = queue.finish(submitted["id"], result=answer, input_tokens=100,
        output_tokens=50, actual_cost_usd=0.000022, retryable=False, **options)
    assert completed["status"] == "completed"
    assert type(completed["error"]) is type(writer_error)
    assert completed["error"] == writer_error
    original_queue = deepcopy(completed)
    monkeypatch.setattr(collection_fixture, "JOB", completed["id"])
    monkeypatch.setattr(collection_fixture, "NOW", datetime.now(timezone.utc) + timedelta(seconds=2))
    state = collection_fixture.SyntheticOperator(agent="a19", cloud=True)
    state.job.update(completed)
    collected = state.run()
    assert collected.summary["state"] == "UNSIGNED_CASE_EVIDENCE", collected.summary
    execution = json.loads(collected.execution_bytes)
    assert type(execution["job"]["error"]) is type(writer_error)
    assert execution["job"]["error"] == writer_error
    assert execution["job"]["id"] == completed["id"]
    for field in ("result", "started_at", "completed_at", "provider", "attempts"):
        assert execution["job"][field] == completed[field]
    # Apply the real pure reviewer to the collector's ORIGINAL raw-error
    # execution, separately from the synthetic artifact transport callback.
    review_context = json.loads(state.last_review_request["context"])
    # The dispatcher consumes this owned Objective lookup key before invoking
    # the pure review tool's existing exact four-field context contract.
    assert review_context.pop("subject_objective_id") == collection_fixture.OBJECTIVE
    verdict = review_fixture.run(review_context)
    assert verdict["test_result"] == "PASS" and verdict["certification"] == "UNVERIFIED"
    assert review_collected(state, collected) is True
    assert queue.get(completed["id"]) == original_queue
    assert state.calls.count("submit") == state.calls.count("review") == 1


@pytest.mark.parametrize("value", SUCCESS_ERRORS)
def test_collector_accepts_only_known_success_shapes_without_normalization(value):
    state = collection_fixture.SyntheticOperator(agent="a19")
    state.job["error"] = value
    before = deepcopy(state.job)
    collected = state.run()
    assert collected.summary["state"] == "UNSIGNED_CASE_EVIDENCE", collected.summary
    raw = json.loads(collected.execution_bytes)
    assert type(raw["job"]["error"]) is type(value) and raw["job"]["error"] == value
    assert state.job == before and review_collected(state, collected) is True


@pytest.mark.parametrize("value", INVALID_ERRORS)
def test_collector_rejects_false_whitespace_or_error_payload_without_review(value):
    state = collection_fixture.SyntheticOperator(agent="a19")
    state.job["error"] = value
    collected = state.run()
    assert collected.summary["reason"] == "COMPLETED_JOB_INVALID"
    assert state.calls.count("submit") == 1 and "review" not in state.calls
    assert type(state.job["error"]) is type(value) and state.job["error"] == value


@pytest.mark.parametrize("value", SUCCESS_ERRORS)
def test_registered_review_preserves_exact_success_error_digest(value):
    payload = review_fixture.fixture()
    payload["execution"]["job"]["error"] = value
    review_fixture.repin(payload)
    original = review_fixture.canonical(payload)
    result = review_fixture.run(payload)
    assert result["test_result"] == "PASS"
    assert result["execution_evidence_sha256"] == payload["expected_execution_sha256"]
    assert review_fixture.canonical(payload) == original


@pytest.mark.parametrize("value", INVALID_ERRORS)
def test_registered_review_rejects_false_whitespace_or_error_payload(value):
    payload = review_fixture.fixture()
    payload["execution"]["job"]["error"] = value
    review_fixture.repin(payload)
    with pytest.raises(RoleReviewError, match="SUBJECT_JOB_INVALID"):
        review_fixture.run(payload)


def prepare_signing_fixture(tmp_path, value):
    state = signing_fixture.fixture(tmp_path, agent="a19",
        answer=collection_fixture._CASES["a19"][2])
    state["execution"]["job"]["error"] = value
    state["review"]["observations"]["reviewer_execution"] = (
        signing_fixture.mocked_reviewer_execution(state))
    signing_fixture.persist(state)
    return state


def pure_signing_review(state):
    return _review(state["row"], signing_fixture.canon(state["execution"]),
        signing_fixture.canon(state["review"]), source_revision=signing_fixture.EXECUTION_SOURCE,
        runtime_image_id=signing_fixture.IMAGE, reviewer_code_revision=signing_fixture.REVIEWER_CODE,
        now=signing_fixture.NOW)


@pytest.mark.parametrize("value", SUCCESS_ERRORS)
def test_protected_bridge_preserves_success_error_and_actual_artifact_digest(tmp_path, value):
    state = prepare_signing_fixture(tmp_path, value)
    original = signing_fixture.canon(state["execution"])
    assert pure_signing_review(state) is True
    assert signing_fixture.canon(state["execution"]) == original
    proof = state["review"]["observations"]["reviewer_execution"]
    content = json.loads(proof["artifact_content_utf8"])
    assert content["execution_evidence_sha256"] == signing_fixture.sha(original)
    assert state["calls"] == []  # No signing operation requested.


@pytest.mark.parametrize("value", INVALID_ERRORS)
def test_protected_bridge_rejects_false_whitespace_or_error_payload(tmp_path, value):
    state = prepare_signing_fixture(tmp_path, value)
    with pytest.raises(CertificationReviewError, match="COMPLETED_EXECUTION_INVALID"):
        pure_signing_review(state)
    assert state["calls"] == []


def test_none_and_empty_string_are_distinct_evidence_not_interchangeable(tmp_path):
    none = prepare_signing_fixture(tmp_path / "none", None)
    empty = prepare_signing_fixture(tmp_path / "empty", "")
    assert signing_fixture.canon(none["execution"]) != signing_fixture.canon(empty["execution"])
    assert none["row"]["evidence_sha256"] != empty["row"]["evidence_sha256"]
    # A changed raw representation without a new independent review/artifact
    # binding must still fail, although both representations alone are valid.
    none["execution"]["job"]["error"] = ""
    with pytest.raises(CertificationReviewError):
        pure_signing_review(none)


@pytest.mark.parametrize("status", ("failed", "cancelled", "queued", "running"))
def test_empty_error_does_not_convert_noncompleted_job_into_evidence(status):
    payload = review_fixture.fixture()
    payload["execution"]["job"].update(error="", status=status)
    review_fixture.repin(payload)
    with pytest.raises(RoleReviewError, match="SUBJECT_JOB_INVALID"):
        review_fixture.run(payload)


def test_empty_error_does_not_weaken_a19_substantive_oracle(tmp_path):
    state = prepare_signing_fixture(tmp_path, "")
    answer = json.loads(state["execution"]["job"]["result"])
    answer["can_restart_production"] = True
    state["execution"]["job"]["result"] = json.dumps(answer)
    state["execution"]["job"]["result_sha256"] = signing_fixture.sha(
        state["execution"]["job"]["result"].encode())
    state["review"]["observations"]["result_sha256"] = state["execution"]["job"]["result_sha256"]
    state["review"]["observations"]["reviewer_execution"] = signing_fixture.mocked_reviewer_execution(state)
    signing_fixture.persist(state)
    with pytest.raises(CertificationReviewError, match="CASE_ORACLE_FAILED"):
        pure_signing_review(state)
