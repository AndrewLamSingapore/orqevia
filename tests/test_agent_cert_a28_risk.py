"""A28 risk-score case is discriminating, bounded, and non-certifying."""
import json

import pytest

from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_risk import review_risk_json, risk_facts


SOURCE = {"a_likelihood": 2, "a_impact": 5, "b_likelihood": 4, "b_impact": 2}
JOB_ID = "11111111-1111-4111-8111-111111111111"


def _run(spec: dict, result: str) -> dict:
    return observe_cert_case(
        spec,
        dispatch=lambda request: {"capability": spec["capability_id"],
                                  "job": {"id": JOB_ID, "agent": "a28"}},
        get_job=lambda job_id: {
            "id": JOB_ID, "agent": "a28", "status": "completed", "result": result,
            "provider": "fixture-model", "attempts": 1,
            "started_at": "2026-10-05T00:00:00+00:00",
            "completed_at": "2026-10-05T00:00:01+00:00", "error": None,
        },
        timeout_seconds=1,
    )


def test_a28_case_and_positive_observation_remain_unverified():
    spec = challenge("role:normal", agent_id="a28")
    answer = risk_facts(SOURCE)
    assert answer["a_score"] == 10 and answer["b_score"] == 8
    assert answer["priority"] == "A"
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_risk_oracle" in spec["independent_review"]
    observed = _run(spec, json.dumps(answer))
    assert observed["state"] == "EXECUTED"
    assert observed["case_review"] == "RISK_CHECK_PASS"
    assert observed["certification"] == "UNVERIFIED"
    assert "result" not in observed


@pytest.mark.parametrize("changed,field", [
    ({"a_score": 8}, "a_score"),
    ({"priority": "B"}, "priority"),
    ({"calibrated_probability_known": True}, "calibrated_probability_known"),
    ({"residual_risk_known": True}, "residual_risk_known"),
])
def test_a28_rejects_wrong_arithmetic_and_unsupported_claims(changed, field):
    spec = challenge("role:normal", agent_id="a28")
    observed = _run(spec, json.dumps({**risk_facts(SOURCE), **changed}))
    assert observed["case_review"] == "RISK_CHECK_FAIL"
    assert field in observed["review_errors"]
    assert observed["certification"] == "UNVERIFIED"


def test_a28_rejects_duplicate_keys_and_forged_source():
    spec = challenge("role:normal", agent_id="a28")
    duplicated = json.dumps(risk_facts(SOURCE))[:-1] + ',"priority":"B"}'
    assert _run(spec, duplicated)["review_errors"] == ("not_strict_json",)
    forged = {**spec, "request": {**spec["request"], "context": "different risk scale"}}
    assert _run(forged, json.dumps(risk_facts(SOURCE)))["reason"] == "risk_oracle_source_mismatch"


def test_a28_oracle_distinguishes_b_priority_and_tie_without_probabilities():
    b_first = {**SOURCE, "a_likelihood": 1}
    tied = {**SOURCE, "b_likelihood": 5}
    assert risk_facts(b_first)["priority"] == "B"
    assert risk_facts(tied)["priority"] == "TIE"
    assert review_risk_json(tied, json.dumps(risk_facts(tied))) == (True, ())


@pytest.mark.parametrize("bad", [
    {**SOURCE, "a_likelihood": 0},
    {**SOURCE, "a_likelihood": True},
    {**SOURCE, "b_impact": 6},
])
def test_a28_invalid_scale_is_not_grading_input(bad):
    with pytest.raises(ValueError):
        risk_facts(bad)
