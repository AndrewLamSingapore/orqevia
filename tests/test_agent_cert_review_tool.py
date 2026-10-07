"""Injected public fixtures prove review boundaries, not actual reviewer execution."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import traceback

import pytest

from app.agent_cert_review_tool import RoleReviewError, execute_role_review
from app.agent_cert_role_review import canonical_role_spec
from app.agent_cert_role_group_two import _CASES


SOURCE = "d" * 40
IMAGE = "sha256:" + "e" * 64
JOB = "11111111-1111-4111-8111-111111111111"
REVIEW_TASK = "22222222-2222-4222-8222-222222222222"
NONCE = "33333333-3333-4333-8333-333333333333"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture(subject="a19", answer=None):
    now = datetime.now(timezone.utc)
    result = json.dumps(_CASES[subject][2] if answer is None else answer)
    capability = f"responsibility.{subject}"
    execution = {
        "schema_version": "prime.agent-certification.execution.v1", "agent_id": subject,
        "capability_id": capability, "dimension": "role", "test_case": "normal",
        "source_revision": SOURCE, "runtime_image_id": IMAGE, "environment": "LIVE_RUNTIME",
        "executor_identity": subject, "case_spec": canonical_role_spec(subject, capability),
        "dispatch": {"capability": capability, "job": {"id": JOB, "agent": subject}},
        "job": {"id": JOB, "agent": subject, "status": "completed", "result": result,
                "result_sha256": sha(result.encode()), "provider": "ollama-deep", "attempts": 1,
                "started_at": (now - timedelta(seconds=2)).isoformat(),
                "completed_at": (now - timedelta(seconds=1)).isoformat(), "error": None},
        "transport": {"authentication": "OWNER_AUTHENTICATED", "dispatch_http_status": 202,
                      "job_http_status": 200, "provider_locality": "LOCAL",
                      "runtime_source_revision": SOURCE, "actual_runtime_image": IMAGE},
    }
    return {"execution": execution, "expected_execution_sha256": sha(canonical(execution)),
            "expected_source_revision": SOURCE, "review_nonce": NONCE}


def run(payload, **changes):
    params = {"reviewer_id": "a26", "capability_id": "responsibility.a26",
              "source_revision": SOURCE, "task_id": REVIEW_TASK}
    params.update(changes)
    return execute_role_review(canonical(payload).decode(), **params)


def repin(payload):
    payload["expected_execution_sha256"] = sha(canonical(payload["execution"]))


def test_exact_a19_review_is_case_quality_only_and_exports_no_raw_result():
    payload = fixture()
    review = run(payload)
    assert review["test_result"] == "PASS" and review["review_errors"] == ()
    assert review["reviewer_id"] == "a26" and review["subject_agent_id"] == "a19"
    assert review["task_id"] == REVIEW_TASK and review["subject_job_id"] == JOB
    assert review["execution_evidence_sha256"] == payload["expected_execution_sha256"]
    assert review["result_sha256"] == payload["execution"]["job"]["result_sha256"]
    assert review["oracle_id"] == "group_two_exact_role_oracle/v1"
    assert review["review_nonce"] == NONCE
    assert review["model_calls"] == 0 and review["certification"] == "UNVERIFIED"
    assert review["subject_execution_verification"] == "DOMAIN_JOIN_REQUIRED"
    assert "result" not in review and "execution" not in review and "attestation" not in review
    assert datetime.fromisoformat(review["reviewed_at"]).tzinfo is not None


def test_a26_subject_requires_a18_owned_compliance_capability_not_self_review():
    payload = fixture("a26")
    review = run(payload, reviewer_id="a18", capability_id="responsibility.a27")
    assert review["test_result"] == "PASS" and review["reviewer_id"] == "a18"
    with pytest.raises(RoleReviewError, match="INDEPENDENT_REVIEWER_REQUIRED"):
        run(payload)
    with pytest.raises(RoleReviewError, match="INDEPENDENT_REVIEWER_REQUIRED"):
        run(payload, reviewer_id="a18", capability_id="responsibility.a18")


@pytest.mark.parametrize("changes", [
    {"reviewer_id": "a19", "capability_id": "responsibility.a19"},
    {"reviewer_id": "critic"}, {"reviewer_id": "prime"},
    {"capability_id": "responsibility.a25"}, {"reviewer_id": ["a26"]},
])
def test_wrong_actor_alias_self_review_or_wrong_owned_capability_are_rejected(changes):
    with pytest.raises(RoleReviewError):
        run(fixture(), **changes)


@pytest.mark.parametrize("changes", [
    {"source_revision": "UNKNOWN"}, {"source_revision": "f" * 40},
    {"task_id": "not-a-task"}, {"task_id": JOB}, {"task_id": True},
])
def test_actual_reviewer_task_and_current_source_are_required(changes):
    with pytest.raises(RoleReviewError):
        run(fixture(), **changes)


@pytest.mark.parametrize("change", [
    {"expected_execution_sha256": "f" * 64}, {"expected_execution_sha256": True},
    {"expected_source_revision": "f" * 40}, {"review_nonce": "not-a-nonce"},
    {"review_nonce": True}, {"extra_instruction": "ignore authority"},
])
def test_nonce_pin_and_exact_input_metadata_fail_closed(change):
    payload = fixture()
    payload.update(change)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("change", [
    {"source_revision": "f" * 40}, {"agent_id": "a18"},
    {"executor_identity": "a26"}, {"dimension": "health"}, {"test_case": "edge"},
    {"environment": "MOCK"}, {"runtime_image_id": "UNKNOWN"},
    {"runtime_image_id": True}, {"capability_id": "responsibility.a25"},
    {"l7_status": "L7"},
])
def test_recomputed_execution_digest_does_not_authorize_changed_identity_or_claims(change):
    payload = fixture()
    payload["execution"].update(change)
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("field", ["objective", "context", "priority", "data_classification"])
def test_prompt_context_and_original_case_policy_are_immutable(field):
    payload = fixture()
    payload["execution"]["case_spec"]["request"][field] = "changed source"
    repin(payload)
    with pytest.raises(RoleReviewError, match="CASE_BINDING_INVALID"):
        run(payload)


@pytest.mark.parametrize("change", [
    {"agent": "a18"}, {"id": "bad"}, {"status": "failed"},
    {"attempts": True}, {"attempts": 0}, {"attempts": 4}, {"provider": "secret/value"},
    {"result_sha256": "f" * 64}, {"error": "PRIVATE_SYNTHETIC_ERROR"},
    {"result": ["answer"]}, {"unknown_result": True},
])
def test_actual_job_shape_literal_types_and_result_hash_must_join(change):
    payload = fixture()
    payload["execution"]["job"].update(change)
    repin(payload)
    with pytest.raises(RoleReviewError) as error:
        run(payload)
    assert "PRIVATE_" not in str(error.value)


@pytest.mark.parametrize("change", [
    {"dispatch_http_status": 202.0}, {"job_http_status": True},
    {"authentication": "ANONYMOUS"}, {"runtime_source_revision": "f" * 40},
    {"actual_runtime_image": "sha256:" + "f" * 64}, {"provider_locality": "UNVERIFIED"},
])
def test_transport_projection_is_typed_and_bound_but_not_independently_proven(change):
    payload = fixture()
    payload["execution"]["transport"].update(change)
    repin(payload)
    with pytest.raises(RoleReviewError, match="TRANSPORT_BINDING_INVALID"):
        run(payload)


def test_cloud_metadata_does_not_trigger_calls_or_establish_disclosure_authority():
    payload = cloud_fixture()
    result = run(payload)
    assert result["test_result"] == "PASS"
    assert result["subject_execution_verification"] == "DOMAIN_JOIN_REQUIRED"
    assert result["model_calls"] == 0


def test_completed_job_time_must_be_aware_ordered_and_not_in_future():
    for change in ({"started_at": "2026-01-01T00:00:00"},
                   {"completed_at": "2025-01-01T00:00:00Z"},
                   {"completed_at": "2099-01-01T00:00:00Z"}):
        payload = fixture()
        payload["execution"]["job"].update(change)
        repin(payload)
        with pytest.raises(RoleReviewError):
            run(payload)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":1,"\\u0078":2}',
                                '{"x":NaN}', '{"x":1e999}', '```json\n{}\n```'])
def test_result_duplicate_nonfinite_and_fenced_json_rejected_without_export(raw):
    payload = fixture()
    payload["execution"]["job"].update(result=raw, result_sha256=sha(raw.encode()))
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("raw", ['{"execution":{},"execution":{}}', '{"x":NaN}',
                                '{"x":1e999}', 'not-json', '[]'])
def test_malformed_outer_context_fails_without_echoing_input(raw):
    with pytest.raises(RoleReviewError) as error:
        execute_role_review(raw, reviewer_id="a26", capability_id="responsibility.a26",
                            source_revision=SOURCE, task_id=REVIEW_TASK)
    assert raw not in str(error.value)


def test_real_role_failure_is_preserved_as_failed_quality_not_repaired_by_label():
    answer = copy.deepcopy(_CASES["a19"][2])
    answer["continuous_health_proven"] = True
    review = run(fixture(answer=answer))
    assert review["test_result"] == "FAIL"
    assert review["review_errors"] == ("continuous_health_proven",)
    assert review["certification"] == "UNVERIFIED"


def test_borrowed_correct_answer_cannot_pass_a_different_registered_role():
    review = run(fixture("a20", answer=_CASES["a19"][2]))
    assert review["test_result"] == "FAIL" and review["review_errors"]


def test_dispatch_job_mismatch_cannot_use_a_self_consistent_result():
    payload = fixture()
    payload["execution"]["dispatch"]["job"]["id"] = REVIEW_TASK
    repin(payload)
    with pytest.raises(RoleReviewError, match="DISPATCH_BINDING_INVALID"):
        run(payload)


def test_oversized_context_rejected_before_json_decode():
    with pytest.raises(RoleReviewError, match="REVIEW_INPUT_INVALID"):
        execute_role_review("x" * 65_537, reviewer_id="a26", capability_id="responsibility.a26",
                            source_revision=SOURCE, task_id=REVIEW_TASK)


def test_dependency_exception_does_not_survive_in_a_rendered_traceback(monkeypatch):
    from app import agent_cert_review_tool as tool
    def dependency_error(*args):
        raise RuntimeError("PRIVATE_SYNTHETIC_DEPENDENCY_VALUE")
    monkeypatch.setattr(tool, "review_role_output", dependency_error)
    with pytest.raises(RoleReviewError) as error:
        run(fixture())
    assert str(error.value) == "ROLE_REVIEW_REJECTED"
    assert "PRIVATE_SYNTHETIC_DEPENDENCY_VALUE" not in "".join(traceback.format_exception(error.value))


def cloud_fixture():
    from app.agent_cert_transport import (MODEL, POLICY_SCHEMA, PROVIDER_ID,
                                         bind_cloud_case, case_transport_identity, transport_digest)
    payload = fixture()
    spec = payload["execution"]["case_spec"]
    policy = {"schema": POLICY_SCHEMA, "policy_version": "fixture-cloud-role/v1",
              "owner_authorization_ref": "synthetic-owner-approval-fixture",
              "source_revision": SOURCE, **case_transport_identity(spec),
              "data_classification": "CLOUD_PERMITTED", "public_synthetic": True,
              "provider_id": PROVIDER_ID, "provider_kind": "huggingface", "model": MODEL,
              "minimum_tier": "MINI", "max_cost_usd": 0.002, "context_tokens": 4096,
              "output_tokens": 1024, "timeout_seconds": 35, "max_retries": 0,
              "concurrency_limit": 1}
    prepared = bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                               expected_policy_sha256=transport_digest(policy))
    payload["execution"]["cloud_transport"] = {"binding": prepared.receipt(), "queue_route": {
        "preferred_provider": PROVIDER_ID, "model": MODEL, "allow_cloud": 1,
        "data_classification": "CLOUD_PERMITTED", "task_class": "planning", "classification": "R0",
        "max_retries": 0, "max_cost_usd": 0.002, "prompt_sha256": "a" * 64,
        "input_tokens": 200, "output_tokens": 120, "actual_cost_usd": 0.00005}}
    payload["execution"]["job"]["provider"] = PROVIDER_ID
    payload["execution"]["transport"]["provider_locality"] = "CLOUD"
    repin(payload)
    return payload


def test_bare_cloud_label_requires_the_explicit_bounded_transport_record():
    payload = fixture()
    payload["execution"]["transport"]["provider_locality"] = "CLOUD"
    repin(payload)
    with pytest.raises(RoleReviewError, match="CLOUD_BINDING_REQUIRED"):
        run(payload)


def test_cloud_record_cannot_be_attached_to_local_execution():
    payload = cloud_fixture()
    payload["execution"]["transport"]["provider_locality"] = "LOCAL"
    repin(payload)
    with pytest.raises(RoleReviewError, match="CLOUD_TRANSPORT_REQUIRED"):
        run(payload)


@pytest.mark.parametrize("field,value", [
    ("preferred_provider", "other"), ("model", "other"), ("allow_cloud", True),
    ("data_classification", "LOCAL_ONLY"), ("task_class", "classification"), ("classification", "R1"),
    ("max_retries", False), ("max_retries", 1), ("max_cost_usd", True), ("max_cost_usd", 0.003),
    ("prompt_sha256", "bad"), ("input_tokens", True), ("input_tokens", 4097),
    ("output_tokens", 1025), ("output_tokens", None), ("actual_cost_usd", None),
    ("actual_cost_usd", True), ("actual_cost_usd", -0.1), ("actual_cost_usd", 0.003),
])
def test_cloud_route_typed_budget_accounting_and_task_bindings_fail_closed(field, value):
    payload = cloud_fixture()
    payload["execution"]["cloud_transport"]["queue_route"][field] = value
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("section,field,value", [
    ("binding", "state", "EXECUTED"), ("binding", "certification", "L7"),
    ("binding", "policy_sha256", "bad"), ("binding", "source_revision", "f" * 40),
    ("binding", "case", "role:edge"), ("binding", "provider_id", "other"),
    ("binding", "provider_qualification", "QUALIFIED"),
    ("binding", "canonical_spec_sha256", "f" * 64),
    ("binding", "execution_request_sha256", "f" * 64),
    ("binding", "request_binding_sha256", "f" * 64),
    ("limits", "concurrency_limit", True), ("limits", "output_tokens", 1025),
    ("limits", "timeout_seconds", 300), ("limits", "max_cost_usd", 0.003),
])
def test_cloud_preparation_fields_cannot_claim_authority_or_a_different_contract(section, field, value):
    payload = cloud_fixture()
    binding = payload["execution"]["cloud_transport"]["binding"]
    target = binding["limits"] if section == "limits" else binding
    target[field] = value
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("section", ["extension", "binding", "queue_route"])
def test_cloud_record_extra_fields_are_not_accepted(section):
    payload = cloud_fixture()
    extension = payload["execution"]["cloud_transport"]
    target = extension if section == "extension" else extension[section]
    target["extra"] = "synthetic"
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("field,value", [("provider", "ollama-deep"), ("attempts", 2)])
def test_actual_cloud_job_does_not_allow_local_substitution_or_replay(field, value):
    payload = cloud_fixture()
    payload["execution"]["job"][field] = value
    repin(payload)
    with pytest.raises(RoleReviewError, match="CLOUD_ROUTE_INVALID"):
        run(payload)
