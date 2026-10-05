"""Source/oracle checks only; these do not certify a live agent."""
import json

from app.agent_cert_boundary import review_zero_boundary_json
from app.agent_cert_cases import challenge


CORRECT = {
    "required_zero_result": True,
    "buggy_zero_result": False,
    "corrected_zero_result": True,
    "negative_one_result": False,
    "positive_one_result": True,
    "corrected_condition": "n >= 0",
    "discriminating_assertion": "assert is_nonnegative(0) is True",
    "tests_executed": False,
}


def test_exact_zero_boundary_case_is_prepared_but_unverified():
    spec = challenge("role:normal", agent_id="a18", capability_id="responsibility.a18")
    assert spec["certification"] == "UNVERIFIED"
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_zero_boundary_oracle" in spec["independent_review"]
    assert review_zero_boundary_json(json.dumps(CORRECT)) == (True, ())


def test_inverted_assertion_and_false_zero_are_rejected():
    inverted = {**CORRECT, "discriminating_assertion": "assert is_nonnegative(0) is False"}
    valid, errors = review_zero_boundary_json(json.dumps(inverted))
    assert not valid and "discriminating_assertion" in errors
    wrong_requirement = {**CORRECT, "required_zero_result": False}
    valid, errors = review_zero_boundary_json(json.dumps(wrong_requirement))
    assert not valid and "required_zero_result" in errors


def test_false_execution_claim_and_duplicate_json_key_are_rejected():
    asserted_run = {**CORRECT, "tests_executed": True}
    valid, errors = review_zero_boundary_json(json.dumps(asserted_run))
    assert not valid and "tests_executed" in errors
    duplicate = json.dumps(CORRECT)[:-1] + ', "required_zero_result": false}'
    assert review_zero_boundary_json(duplicate) == (False, ("not_strict_json",))


def test_unbounded_or_extra_field_rejected():
    assert review_zero_boundary_json("x" * 4097) == (False, ("response_not_bounded_text",))
    assert review_zero_boundary_json(json.dumps({**CORRECT, "status": "CERTIFIED"})) == (
        False, ("field_contract_mismatch",))
