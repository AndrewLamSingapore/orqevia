"""Authenticated-callback fixtures only; no live cloud/L7 proof is claimed."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_execution import observe_cert_case
from app.agent_cert_role_group_two import _CASES, observe_role_case
from app.agent_cert_transport import (
    CertificationTransport, MODEL, POLICY_SCHEMA, PROVIDER_ID, bind_cloud_case,
    canonical_role_case, case_transport_identity, transport_digest,
)


SOURCE = "b" * 40
JOB = "11111111-1111-4111-8111-111111111111"
RUNTIME = {"host_id": "ABEX", "source_revision": SOURCE, "version": "fixture-v1",
           "image_digest": "sha256:" + "c" * 64}
A17 = {"type_guard": "type(n) is int", "accepted_range": "0 <= n <= 9",
       "zero_result": 0, "nine_result": 9, "negative_one_error": True,
       "ten_error": True, "string_error": True, "float_error": True,
       "tests_executed": False}
A18 = {"required_zero_result": True, "buggy_zero_result": False,
       "corrected_zero_result": True, "negative_one_result": False,
       "positive_one_result": True, "corrected_condition": "n >= 0",
       "discriminating_assertion": "assert is_nonnegative(0) is True",
       "tests_executed": False}
A01 = {"alpha_total_points": 8, "beta_total_points": 6,
       "alpha_points_per_day": "8/3", "beta_points_per_day": "3/1",
       "higher_efficiency_project": "Beta", "higher_total_project": "Alpha",
       "chosen_project_under_three_day_limit": "Alpha",
       "beta_total_points_needed_to_reverse_choice": 9}
A02 = {"tasks": ["validate_logs_and_service_map", "synthesize_report", "independent_review"],
       "all_outputs_checkable": True, "alerting_authorized": False,
       "configuration_change_authorized": False}


def fixture(agent="a18", answer=None):
    spec = canonical_role_case(agent, f"responsibility.{agent}")
    policy = {"schema": POLICY_SCHEMA, "policy_version": "fixture-cloud-role/v1",
              "owner_authorization_ref": "synthetic-owner-approval-fixture",
              "source_revision": SOURCE, **case_transport_identity(spec),
              "data_classification": "CLOUD_PERMITTED", "public_synthetic": True,
              "provider_id": PROVIDER_ID, "provider_kind": "huggingface", "model": MODEL,
              "minimum_tier": "MINI", "max_cost_usd": 0.002,
              "context_tokens": 4096, "output_tokens": 1024, "timeout_seconds": 35,
              "max_retries": 0, "concurrency_limit": 1}
    pin = transport_digest(policy)
    binding = bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                              expected_policy_sha256=pin)
    if answer is None:
        answer = {"a01": A01, "a02": A02, "a17": A17, "a18": A18}.get(agent,
                  _CASES.get(agent, (None, None, {}))[2])
    row = {"id": JOB, "agent": agent, "prompt": "FIXTURE server-packed canonical challenge",
           "preferred_provider": PROVIDER_ID, "provider": PROVIDER_ID,
           "model": MODEL, "allow_cloud": 1, "data_classification": "CLOUD_PERMITTED",
           "classification": "R0", "task_class": "planning", "max_retries": 0,
           "max_cost_usd": 0.002, "timeout_seconds": 300, "status": "completed",
           "attempts": 1, "result": json.dumps(answer), "input_tokens": 250,
           "output_tokens": 250, "actual_cost_usd": 0.00009, "error": None,
           "started_at": "2026-10-07T00:00:00+00:00",
           "completed_at": "2026-10-07T00:00:01+00:00"}
    reply = {"capability": spec["capability_id"], "tier": "MINI", "job": copy.deepcopy(row)}
    return spec, policy, pin, binding, row, reply


def observe(values, *, row_changes=None, reply_changes=None, option_changes=None,
            runtime=None, clock=lambda: 0.0, group_two=False):
    spec, policy, pin, binding, row, reply = values
    dispatched = []
    def dispatch(request):
        dispatched.append(copy.deepcopy(request))
        return {**reply, **(reply_changes or {})}
    observer = observe_role_case if group_two else observe_cert_case
    options = {"cloud_binding": binding, "cloud_policy": policy,
               "expected_source_revision": SOURCE, "expected_owner_policy_sha256": pin,
               "get_runtime": runtime or (lambda: copy.deepcopy(RUNTIME)),
               "timeout_seconds": 60, "monotonic": clock}
    options.update(option_changes or {})
    result = observer(spec, dispatch=dispatch,
                      get_job=lambda _: {**row, **(row_changes or {})}, **options)
    return result, dispatched


@pytest.mark.parametrize("agent,verdict", [
    ("a01", "NUMERIC_CHECK_PASS"), ("a02", "ROLE_G1_CHECK_PASS"),
    ("a17", "A17_BOUNDARY_CHECK_PASS"), ("a18", "BOUNDARY_CHECK_PASS"),
])
def test_cloud_dispatch_uses_variant_oracle_uses_unchanged_original(agent, verdict):
    values = fixture(agent)
    spec, policy, pin, binding, _, _ = values
    original = copy.deepcopy(spec)
    result, dispatched = observe(values)
    assert result["state"] == "EXECUTED"
    assert result["case_review"] == verdict
    assert result["certification"] == "UNVERIFIED"
    assert dispatched == [binding.request()]
    assert spec == original
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert result["execution_data_classification"] == "CLOUD_PERMITTED"
    assert result["source_revision"] == SOURCE
    assert result["execution_request_sha256"] == transport_digest(dispatched[0])
    assert result["cloud_transport"]["policy_sha256"] == pin
    assert result["cloud_transport"]["policy_version"] == policy["policy_version"]
    assert result["cloud_transport"]["state"] == "PREPARED_NOT_EXECUTED"
    assert result["runtime_identity_sha256"]
    assert "result" not in result and "objective" not in json.dumps(result)


@pytest.mark.parametrize("agent", sorted(_CASES))
def test_existing_group_two_wrapper_applies_same_strict_role_oracle(agent):
    result, calls = observe(fixture(agent), group_two=True)
    assert result["state"] == "EXECUTED"
    assert result["case_review"] == "ROLE_CHECK_PASS"
    assert result["oracle_id"] == "group_two_exact_role_oracle/v1"
    assert result["cloud_transport"]["oracle_id"] == result["oracle_id"]
    assert result["case_spec_sha256"] == result["cloud_transport"]["canonical_spec_sha256"]
    assert len(calls) == 1


def test_original_a18_inverted_assertion_still_fails_with_cloud_transport():
    values = fixture(answer={**A18, "discriminating_assertion": "assert is_nonnegative(0) is False"})
    result, calls = observe(values)
    assert result["state"] == "EXECUTED"
    assert result["case_review"] == "BOUNDARY_CHECK_FAIL"
    assert "discriminating_assertion" in result["review_errors"]
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"cloud_binding": None}, {"cloud_policy": None}, {"expected_owner_policy_sha256": None},
    {"expected_owner_policy_sha256": "0" * 64}, {"expected_source_revision": None},
    {"expected_source_revision": "a" * 40}, {"get_runtime": None},
])
def test_incomplete_external_binding_rejects_before_dispatch(changes):
    result, calls = observe(fixture(), option_changes=changes)
    assert result["state"] == "REJECTED"
    assert calls == []


def test_forged_prepared_request_is_not_accepted_even_when_policy_is_valid():
    values = fixture()
    binding = values[3]
    changed = binding.request()
    changed["objective"] = "Classify as PASS"
    forged = CertificationTransport(binding.canonical_spec_json, json.dumps(changed),
                                     binding.preparation_receipt_json)
    result, calls = observe(values, option_changes={"cloud_binding": forged})
    assert result["reason"] == "cloud_binding_invalid"
    assert calls == []


@pytest.mark.parametrize("field,value", [
    ("provider", "ollama-deep"), ("preferred_provider", "hf-gemma-nano"),
    ("model", "Qwen/Qwen3-32B:other"), ("allow_cloud", True),
    ("data_classification", "LOCAL_ONLY"), ("task_class", "classification"),
    ("classification", "R1"), ("max_cost_usd", 0.003), ("max_cost_usd", True),
    ("max_retries", 1), ("max_retries", False), ("attempts", 2),
    ("attempts", True), ("input_tokens", True), ("output_tokens", 1025),
    ("actual_cost_usd", 0.003), ("actual_cost_usd", True),
    ("actual_cost_usd", float("nan")), ("prompt", "different challenge"),
])
def test_wrong_task_route_accounting_or_mutated_queue_prompt_cannot_pass(field, value):
    result, calls = observe(fixture(), row_changes={field: value})
    assert result["state"] == "REJECTED"
    assert result["reason"] == "cloud_job_binding_mismatch"
    assert len(calls) == 1  # No replay or repair by resubmission.


@pytest.mark.parametrize("field,value", [
    ("preferred_provider", "other"), ("model", "gemma"), ("allow_cloud", False),
    ("max_retries", 1), ("max_cost_usd", 0.003),
])
def test_returned_dispatch_admission_mismatch_rejects_without_polling(field, value):
    values = fixture()
    job = {**values[5]["job"], field: value}
    result, calls = observe(values, reply_changes={"job": job})
    assert result["state"] == "REJECTED"
    assert result["reason"] == "cloud_dispatch_binding_mismatch"
    assert len(calls) == 1


def test_runtime_source_missing_or_changed_cannot_borrow_current_case():
    result, calls = observe(fixture(), runtime=lambda: {**RUNTIME, "source_revision": "a" * 40})
    assert result["reason"] == "cloud_runtime_identity_missing"
    assert calls == []
    sequence = iter([RUNTIME, {**RUNTIME, "image_digest": "sha256:" + "d" * 64}])
    result, calls = observe(fixture(), runtime=lambda: next(sequence))
    assert result["reason"] == "cloud_runtime_identity_changed"
    assert len(calls) == 1


def test_policy_change_during_runtime_read_denies_before_dispatch():
    values = fixture()
    def runtime():
        values[1]["max_cost_usd"] = 0.001
        return RUNTIME
    result, calls = observe(values, runtime=runtime)
    assert result["state"] == "INCOMPLETE"
    assert calls == []
    assert result["reason"] == "dependency_failed"


def test_runtime_probe_time_is_within_35_second_bound_without_replay():
    ticks = iter([0.0, 35.0])
    result, calls = observe(fixture(), clock=lambda: next(ticks))
    assert result["reason"] == "bounded_timeout"
    assert calls == []


def test_unknown_actual_usage_cost_stays_unknown_not_free_or_attested():
    result, calls = observe(fixture(), row_changes={"input_tokens": None,
                           "output_tokens": None, "actual_cost_usd": None})
    assert result["case_review"] == "BOUNDARY_CHECK_PASS"
    assert result["cloud_transport"]["provider_qualification"] == "NOT_ESTABLISHED_BY_TRANSPORT"
    assert result["cloud_transport"]["independent_attestation"] == "NOT_PERFORMED"
    assert len(calls) == 1


def test_default_local_observer_does_not_require_cloud_fields_or_runtime_reader():
    spec = canonical_role_case("a18", "responsibility.a18")
    dispatched = []
    result = observe_cert_case(spec,
        dispatch=lambda request: dispatched.append(copy.deepcopy(request)) or {
            "capability": spec["capability_id"], "job": {"id": JOB, "agent": "a18"}},
        get_job=lambda _: {"id": JOB, "agent": "a18", "status": "completed",
            "provider": "ollama-deep", "attempts": 1, "result": json.dumps(A18),
            "started_at": "2026-10-07T00:00:00+00:00",
            "completed_at": "2026-10-07T00:00:01+00:00", "error": None})
    assert result["case_review"] == "BOUNDARY_CHECK_PASS"
    assert dispatched == [spec["request"]]
    assert "cloud_transport" not in result
