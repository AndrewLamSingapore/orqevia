"""Six distinct source-bound role oracles; no test grants certification."""
import json

import pytest

from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_role_g1 import SOURCES, review_role_json, role_facts


JOB_ID = "11111111-1111-4111-8111-111111111111"


def _run(spec: dict, result: str) -> dict:
    agent = spec["agent_id"]
    return observe_cert_case(
        spec,
        dispatch=lambda request: {"capability": spec["capability_id"],
                                  "job": {"id": JOB_ID, "agent": agent}},
        get_job=lambda job_id: {
            "id": JOB_ID, "agent": agent, "status": "completed", "result": result,
            "provider": "fixture-model", "attempts": 1,
            "started_at": "2026-10-05T00:00:00+00:00",
            "completed_at": "2026-10-05T00:00:01+00:00", "error": None,
        },
        timeout_seconds=1,
    )


@pytest.mark.parametrize("agent", sorted(SOURCES))
def test_registered_role_case_is_bounded_and_oracle_reviewed(agent):
    spec = challenge("role:normal", agent_id=agent)
    answer = role_facts(agent, SOURCES[agent])
    assert spec["request"]["response_format"] == "strict_json"
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["max_cost_usd"] == 0
    assert "exact_role_g1_oracle" in spec["independent_review"]
    observed = _run(spec, json.dumps(answer))
    assert observed["state"] == "EXECUTED"
    assert observed["case_review"] == "ROLE_G1_CHECK_PASS"
    assert observed["certification"] == "UNVERIFIED"
    assert "result" not in observed


@pytest.mark.parametrize("agent", sorted(SOURCES))
def test_wrong_but_plausible_answer_fails(agent):
    answer = role_facts(agent, SOURCES[agent])
    field = next(k for k, value in answer.items() if type(value) is bool)
    answer[field] = not answer[field]
    observed = _run(challenge("role:normal", agent_id=agent), json.dumps(answer))
    assert observed["case_review"] == "ROLE_G1_CHECK_FAIL"
    assert field in observed["review_errors"]
    assert observed["certification"] == "UNVERIFIED"


@pytest.mark.parametrize("agent", sorted(SOURCES))
def test_duplicate_key_and_forged_case_rejected(agent):
    spec = challenge("role:normal", agent_id=agent)
    answer = role_facts(agent, SOURCES[agent])
    key = next(iter(answer))
    duplicate = json.dumps(answer)[:-1] + f',{json.dumps(key)}:null}}'
    assert _run(spec, duplicate)["review_errors"] == ("not_strict_json",)
    forged_context = {**spec, "request": {**spec["request"], "context": "fabricated source"}}
    assert _run(forged_context, json.dumps(answer))["reason"] == "role_g1_oracle_source_mismatch"
    forged_metadata = {**spec, "independent_review": (*spec["independent_review"], "fake_signer")}
    assert _run(forged_metadata, json.dumps(answer))["reason"] == "role_g1_oracle_source_mismatch"
    missing_oracle = {**spec, "independent_review": tuple(x for x in spec["independent_review"]
                                                        if x != "exact_role_g1_oracle")}
    assert _run(missing_oracle, json.dumps(answer))["reason"] == "role_g1_oracle_source_mismatch"


@pytest.mark.parametrize("agent", sorted(SOURCES))
def test_field_shape_and_type_are_strict(agent):
    answer = role_facts(agent, SOURCES[agent])
    assert review_role_json(agent, SOURCES[agent], json.dumps({**answer, "approved": True})) == (
        False, ("field_contract_mismatch",))
    field = next(k for k, value in answer.items() if type(value) is bool)
    answer[field] = 1
    assert field in review_role_json(agent, SOURCES[agent], json.dumps(answer))[1]


def test_domain_specific_counterexamples():
    a02 = role_facts("a02", SOURCES["a02"])
    assert a02["tasks"] == ["validate_logs_and_service_map", "synthesize_report", "independent_review"]
    assert not a02["alerting_authorized"] and not a02["configuration_change_authorized"]
    assert not role_facts("a06", SOURCES["a06"])["causal_effect_established"]
    assert role_facts("a07", SOURCES["a07"])["s1_positive"] == 7
    assert not role_facts("a07", SOURCES["a07"])["population_claim_proven"]
    assert role_facts("a09", SOURCES["a09"])["current_applicability"] == "UNKNOWN"
    assert role_facts("a10", SOURCES["a10"])["combined_comparable_total"] is None
    assert role_facts("a13", SOURCES["a13"])["next_period_estimate"] == 16
    assert not role_facts("a13", SOURCES["a13"])["calibrated_confidence_bound_known"]


def test_invalid_source_cannot_be_grading_input():
    with pytest.raises(ValueError):
        role_facts("a07", {**SOURCES["a07"], "survey_positive": 11})
    with pytest.raises(ValueError):
        role_facts("a13", {**SOURCES["a13"], "weekly_units": [10, 12, 15]})
    with pytest.raises(ValueError):
        role_facts("a10", {**SOURCES["a10"], "team_a_reported_requests": True})
