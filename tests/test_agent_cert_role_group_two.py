"""Source-level role cases only: fixture dispatch is not a live agent proof."""
import json

import pytest

from app.agent_cert_role_group_two import (
    _CASES, observe_role_case, review_role_json, role_case,
)


JOB_ID = "11111111-1111-4111-8111-111111111111"


def _run(spec: dict, result: str):
    def dispatch(request):
        assert request == spec["request"]
        return {"capability": spec["capability_id"],
                "job": {"id": JOB_ID, "agent": spec["agent_id"]}}

    def get_job(job_id):
        assert job_id == JOB_ID
        return {"id": JOB_ID, "agent": spec["agent_id"],
                "status": "completed", "result": result,
                "provider": "fixture-model", "attempts": 1,
                "started_at": "2026-10-05T00:00:00+00:00",
                "completed_at": "2026-10-05T00:00:01+00:00", "error": None}

    return observe_role_case(spec, dispatch=dispatch, get_job=get_job,
                             timeout_seconds=1)


@pytest.mark.parametrize("agent", sorted(_CASES))
def test_distinct_registered_bounded_case_and_exact_answer(agent):
    spec = role_case(agent)
    assert spec["agent_id"] == agent
    assert spec["capability_id"] == f"responsibility.{agent}"
    assert spec["request"]["classification"] == "R0"
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["max_cost_usd"] == 0
    assert spec["request"]["response_format"] == "strict_json"
    assert spec["certification"] == "UNVERIFIED"
    observed = _run(spec, json.dumps(_CASES[agent][2]))
    assert observed["state"] == "EXECUTED"
    assert observed["case_review"] == "ROLE_CHECK_PASS"
    assert observed["certification"] == "UNVERIFIED"
    assert len(observed["case_spec_sha256"]) == 64
    assert observed["oracle_id"] == "group_two_exact_role_oracle/v1"
    assert len(observed["result_sha256"]) == 64
    assert observed["job_id"] == JOB_ID
    assert "result" not in observed


@pytest.mark.parametrize("agent,bad_field,bad_value", [
    ("a15", "reviewer", "Builder"),
    ("a15", "deployment_authorized", True),
    ("a16", "cache_fresh", True),
    ("a16", "current_answer_known", True),
    ("a16", "write_authorized", True),
    ("a19", "continuous_health_proven", True),
    ("a19", "restart_authorized", True),
    ("a19", "latest_check_time", "10:00Z"),
    ("a20", "contribution_margin_percent", 800),
    ("a20", "net_profit_known", True),
    ("a20", "optimal_price_proven", True),
    ("a26", "observed_success_percent", 100),
    ("a26", "candidate_claim_supported", True),
    ("a26", "certification_awarded", True),
])
def test_false_claims_fail_exact_field(agent, bad_field, bad_value):
    spec = role_case(agent)
    answer = {**_CASES[agent][2], bad_field: bad_value}
    observed = _run(spec, json.dumps(answer))
    assert observed["state"] == "EXECUTED"
    assert observed["case_review"] == "ROLE_CHECK_FAIL"
    assert bad_field in observed["review_errors"]
    assert observed["certification"] == "UNVERIFIED"


@pytest.mark.parametrize("agent", sorted(_CASES))
def test_duplicate_decoded_key_is_not_last_write_wins(agent):
    expected = _CASES[agent][2]
    first = next(iter(expected))
    duplicate = json.dumps(expected)[:-1] + f',{json.dumps(first)}:null}}'
    observed = _run(role_case(agent), duplicate)
    assert observed["case_review"] == "ROLE_CHECK_FAIL"
    assert observed["review_errors"] == ("not_strict_json",)


@pytest.mark.parametrize("agent", sorted(_CASES))
def test_forged_context_and_review_metadata_reject_before_dispatch(agent):
    spec = role_case(agent)
    def should_not_dispatch(_request):
        raise AssertionError("forged case must not dispatch")
    for forged in (
        {**spec, "request": {**spec["request"], "context": "new facts"}},
        {**spec, "independent_review": (*spec["independent_review"], "fake_signer")},
    ):
        observed = observe_role_case(forged, dispatch=should_not_dispatch,
                                     get_job=should_not_dispatch)
        assert observed["state"] == "REJECTED"
        assert observed["reason"] == "role_oracle_source_mismatch"


def test_wrong_role_is_rejected():
    with pytest.raises(ValueError):
        role_case("a22")
    with pytest.raises(ValueError):
        review_role_json("a22", "{}")


def test_strict_json_rejects_missing_fields_extra_fields_and_boolean_as_integer():
    expected = _CASES["a26"][2]
    for answer in (
        {key: value for key, value in expected.items() if key != "failures"},
        {**expected, "signed_attestation": True},
        {**expected, "passes": True},
    ):
        valid, errors = review_role_json("a26", json.dumps(answer))
        assert valid is False
        assert errors


def test_missing_worker_evidence_cannot_pass_oracle():
    spec = role_case("a26")
    observed = observe_role_case(
        spec,
        dispatch=lambda _: {"capability": spec["capability_id"],
                            "job": {"id": JOB_ID, "agent": "a26"}},
        get_job=lambda _: {"id": JOB_ID, "agent": "a26", "status": "completed",
                           "result": json.dumps(_CASES["a26"][2]),
                           "provider": "fixture-model", "attempts": 1,
                           "started_at": None, "completed_at": None, "error": None},
        timeout_seconds=1,
    )
    assert observed["state"] == "REJECTED"
    assert observed["certification"] == "UNVERIFIED"
