"""A17 boundary checks are exact but never confer certification."""
import json

from app.agent_cert_a17_boundary import review_a17_boundary_json, review_a17_cross_review_json
from app.agent_cert_cases import challenge


CORRECT = {
    "type_guard": "type(n) is int",
    "accepted_range": "0 <= n <= 9",
    "zero_result": 0,
    "nine_result": 9,
    "negative_one_error": True,
    "ten_error": True,
    "string_error": True,
    "float_error": True,
    "tests_executed": False,
}


def test_source_bound_case_is_prepared_not_certified():
    spec = challenge("role:normal", agent_id="a17", capability_id="responsibility.a17")
    assert spec["certification"] == "UNVERIFIED"
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_a17_boundary_oracle" in spec["independent_review"]


def test_exact_oracle_accepts_correct_synthetic_response_without_certifying():
    assert review_a17_boundary_json(json.dumps(CORRECT)) == (True, ())


def test_missing_type_guard_null_errors_and_wrong_boundaries_fail():
    for key, wrong in (("type_guard", "none"), ("accepted_range", "0 < n < 9"),
                       ("zero_result", None), ("nine_result", 10),
                       ("negative_one_error", False), ("ten_error", False),
                       ("string_error", None), ("float_error", False),
                       ("tests_executed", True)):
        valid, errors = review_a17_boundary_json(json.dumps({**CORRECT, key: wrong}))
        assert not valid and key in errors


def test_duplicate_extra_and_unbounded_output_fail():
    duplicate = json.dumps(CORRECT)[:-1] + ', "type_guard": "none"}'
    assert review_a17_boundary_json(duplicate) == (False, ("not_strict_json",))
    assert review_a17_boundary_json(json.dumps({**CORRECT, "certified": True})) == (
        False, ("field_contract_mismatch",))
    assert review_a17_boundary_json("x" * 4097) == (False, ("response_not_bounded_text",))


def test_cross_review_must_match_exact_failed_fields_and_verdict():
    flawed = {**CORRECT, "string_error": None}
    reviewed = json.dumps({"verdict": "FAIL", "failed_fields": ["string_error"],
                           "tests_executed": False})
    assert review_a17_cross_review_json(json.dumps(flawed), reviewed) == (True, ())
    contradictory = json.dumps({"verdict": "FAIL", "failed_fields": [],
                                 "tests_executed": False})
    assert review_a17_cross_review_json(json.dumps(flawed), contradictory) == (
        False, ("failed_fields",))
    false_pass = json.dumps({"verdict": "PASS", "failed_fields": ["string_error"],
                             "tests_executed": False})
    assert review_a17_cross_review_json(json.dumps(flawed), false_pass) == (
        False, ("verdict",))
    assert review_a17_cross_review_json(json.dumps(CORRECT), reviewed) == (
        False, ("verdict", "failed_fields"))
    assert review_a17_cross_review_json("not json", reviewed) == (
        False, ("a17_result_not_reviewable",))
