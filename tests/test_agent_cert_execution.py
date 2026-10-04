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
