"""Injected queue fixtures prove observation boundaries, not agent grades."""
import hashlib
import json

import pytest

from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case


JOB_ID = "11111111-1111-4111-8111-111111111111"
CORRECT = {
    "alpha_total_points": 8, "beta_total_points": 6,
    "alpha_points_per_day": "8/3", "beta_points_per_day": "3/1",
    "higher_efficiency_project": "Beta", "higher_total_project": "Alpha",
    "chosen_project_under_three_day_limit": "Alpha",
    "beta_total_points_needed_to_reverse_choice": 9,
}


def _run(spec, result, *, row_changes=None, reply_changes=None):
    row = {"id": JOB_ID, "agent": spec["agent_id"], "status": "completed",
           "result": result, "provider": "ollama-deep", "attempts": 1,
           "started_at": "2026-10-04T06:00:00+00:00",
           "completed_at": "2026-10-04T06:00:01+00:00", "error": None}
    row.update(row_changes or {})
    reply = {"capability": spec["capability_id"],
             "job": {"id": JOB_ID, "agent": spec["agent_id"]}}
    reply.update(reply_changes or {})
    return observe_cert_case(spec, dispatch=lambda request: reply,
                             get_job=lambda job_id: row, timeout_seconds=1)


def test_a01_exact_numeric_check_is_separate_from_certification():
    spec = challenge("role:normal", agent_id="a01")
    raw = json.dumps(CORRECT)
    observation = _run(spec, raw)
    assert observation["state"] == "EXECUTED"
    assert observation["case_review"] == "NUMERIC_CHECK_PASS"
    assert observation["result_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert observation["certification"] == "UNVERIFIED"
    assert "result" not in observation


def test_a01_false_efficiency_and_invalid_json_are_observed_failures():
    spec = challenge("role:normal", agent_id="a01")
    wrong = json.dumps({**CORRECT, "higher_efficiency_project": "Alpha"})
    failed = _run(spec, wrong)
    assert failed["state"] == "EXECUTED"
    assert failed["case_review"] == "NUMERIC_CHECK_FAIL"
    assert "higher_efficiency_project" in failed["review_errors"]
    assert _run(spec, '{"alpha_points_per_day":8 / 3}')["review_errors"] == ("not_strict_json",)


def test_other_agent_case_remains_unreviewed_not_auto_passed():
    spec = challenge("role:normal", agent_id="a26")
    observation = _run(spec, "Plausible prose")
    assert observation["state"] == "EXECUTED"
    assert observation["case_review"] == "UNREVIEWED"
    assert observation["certification"] == "UNVERIFIED"


def test_a12_rate_check_is_scoped_and_never_certifies():
    spec = challenge("role:normal", agent_id="a12", capability_id="responsibility.a12")
    answer = {"week1_failures": 10, "week1_requests": 100,
              "week2_failures": 15, "week2_requests": 300,
              "week1_rate": "1/10", "week2_rate": "1/20",
              "failure_count_change": "UP", "failure_rate_change": "DOWN",
              "cause": "UNKNOWN"}
    observed = _run(spec, json.dumps(answer))
    assert observed["case_review"] == "RATE_CHECK_PASS"
    assert observed["certification"] == "UNVERIFIED"
    assert "result" not in observed
    failed = _run(spec, json.dumps({**answer, "failure_rate_change": "UP"}))
    assert failed["case_review"] == "RATE_CHECK_FAIL"
    assert "failure_rate_change" in failed["review_errors"]
    forged = {**spec, "request": {**spec["request"], "context": "different numbers"}}
    assert _run(forged, json.dumps(answer))["reason"] == "rate_oracle_source_mismatch"


def test_a04_weighted_tie_case_rejects_false_winner_and_never_certifies():
    spec = challenge("role:normal", agent_id="a04", capability_id="responsibility.a04")
    answer = {"reliability_weight": 2, "speed_weight": 1,
              "a_reliability": 4, "a_speed": 1, "b_reliability": 2, "b_speed": 5,
              "a_score": 9, "b_score": 9, "decision": "TIE",
              "missing_tie_breaker": True}
    observed = _run(spec, json.dumps(answer))
    assert observed["state"] == "EXECUTED"
    assert observed["case_review"] == "WEIGHTED_CHECK_PASS"
    assert observed["certification"] == "UNVERIFIED"
    assert "result" not in observed
    failed = _run(spec, json.dumps({**answer, "decision": "A"}))
    assert failed["case_review"] == "WEIGHTED_CHECK_FAIL"
    assert "decision" in failed["review_errors"]
    forged = {**spec, "request": {**spec["request"], "context": "different weights"}}
    assert _run(forged, json.dumps(answer))["reason"] == "weighted_oracle_source_mismatch"


def test_a18_zero_boundary_case_preserves_failure_repair_and_unverified_status():
    spec = challenge("role:normal", agent_id="a18", capability_id="responsibility.a18")
    answer = {"required_zero_result": True, "buggy_zero_result": False,
              "corrected_zero_result": True, "negative_one_result": False,
              "positive_one_result": True, "corrected_condition": "n >= 0",
              "discriminating_assertion": "assert is_nonnegative(0) is True",
              "tests_executed": False}
    corrected = _run(spec, json.dumps(answer))
    assert corrected["case_review"] == "BOUNDARY_CHECK_PASS"
    assert corrected["certification"] == "UNVERIFIED"
    inverted = _run(spec, json.dumps({**answer,
                                      "discriminating_assertion": "assert is_nonnegative(0) is False"}))
    assert inverted["case_review"] == "BOUNDARY_CHECK_FAIL"
    assert "discriminating_assertion" in inverted["review_errors"]
    forged = {**spec, "request": {**spec["request"], "context": "different requirement"}}
    assert _run(forged, json.dumps(answer))["reason"] == "boundary_oracle_source_mismatch"


def test_wrong_agent_or_worker_receipt_fails_closed():
    spec = challenge("role:normal", agent_id="a01")
    assert _run(spec, "text", reply_changes={"job": {"id": JOB_ID, "agent": "a26"}})["state"] == "REJECTED"
    assert _run(spec, "text", row_changes={"provider": None})["reason"] == "worker_evidence_missing"
    assert _run(spec, "text", row_changes={"attempts": 0})["reason"] == "worker_evidence_missing"
    assert _run(spec, "text", reply_changes={"job": {"id": "bad", "agent": "a01"}})["reason"] == "job_id_missing"


def test_forged_or_unbounded_challenge_cannot_borrow_numeric_oracle():
    spec = challenge("role:normal", agent_id="a01")
    forged = {**spec, "request": {**spec["request"], "context": "altered synthetic facts"}}
    assert _run(forged, json.dumps(CORRECT))["reason"] == "numeric_oracle_source_mismatch"
    with pytest.raises(ValueError, match="bounded registered route"):
        observe_cert_case({**spec, "request": {**spec["request"], "max_cost_usd": 1}},
                          dispatch=lambda request: {}, get_job=lambda job_id: {})
