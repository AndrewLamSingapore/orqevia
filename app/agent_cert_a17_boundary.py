"""Exact, non-certifying check of A17's synthetic parser design."""
from __future__ import annotations

import json


_EXPECTED = {
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


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def review_a17_boundary_json(response: str) -> tuple[bool, tuple[str, ...]]:
    """Compare a declared design with the fixed fixture; no code is executed."""
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != set(_EXPECTED):
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(key for key, expected in _EXPECTED.items()
                          if type(answer[key]) is not type(expected) or answer[key] != expected))
    return not errors, errors


def review_a17_cross_review_json(a17_response: str, reviewer_response: str) -> tuple[bool, tuple[str, ...]]:
    """Check reviewer consistency against A17's exact result; not independent attestation."""
    _, expected_errors = review_a17_boundary_json(a17_response)
    if expected_errors in {("not_strict_json",), ("field_contract_mismatch",),
                           ("response_not_bounded_text",)}:
        return False, ("a17_result_not_reviewable",)
    if not isinstance(reviewer_response, str) or len(reviewer_response) > 4096:
        return False, ("review_not_bounded_text",)
    try:
        review = json.loads(reviewer_response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("review_not_strict_json",)
    if (not isinstance(review, dict) or set(review) != {"verdict", "failed_fields", "tests_executed"}
            or not isinstance(review["failed_fields"], list)
            or any(not isinstance(field, str) for field in review["failed_fields"])):
        return False, ("review_field_contract_mismatch",)
    errors = []
    if review["verdict"] != ("PASS" if not expected_errors else "FAIL"):
        errors.append("verdict")
    if review["failed_fields"] != list(expected_errors):
        errors.append("failed_fields")
    if review["tests_executed"] is not False:
        errors.append("tests_executed")
    return not errors, tuple(errors)
