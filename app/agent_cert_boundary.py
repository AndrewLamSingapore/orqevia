"""Exact, non-certifying review of the synthetic a18 zero-boundary case."""
from __future__ import annotations

import json


_FIELDS = frozenset({
    "required_zero_result", "buggy_zero_result", "corrected_zero_result",
    "negative_one_result", "positive_one_result", "corrected_condition",
    "discriminating_assertion", "tests_executed",
})
_EXPECTED = {
    "required_zero_result": True,
    "buggy_zero_result": False,
    "corrected_zero_result": True,
    "negative_one_result": False,
    "positive_one_result": True,
    "corrected_condition": "n >= 0",
    "discriminating_assertion": "assert is_nonnegative(0) is True",
    "tests_executed": False,
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def review_zero_boundary_json(response: str) -> tuple[bool, tuple[str, ...]]:
    """Check the fixed source case; never award a certification PASS.

    The assertion must fail against ``n > 0`` and pass against ``n >= 0``.
    The source-binding check belongs to the caller and must precede this check.
    """
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _FIELDS:
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(field for field in _FIELDS
                          if type(answer[field]) is not type(_EXPECTED[field])
                          or answer[field] != _EXPECTED[field]))
    return not errors, errors
