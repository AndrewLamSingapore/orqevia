"""Exact, non-certifying review of synthetic failure-count and rate claims."""
from __future__ import annotations

import json
from fractions import Fraction


_SOURCE_FIELDS = frozenset({"week1_failures", "week1_requests", "week2_failures", "week2_requests"})
_ANSWER_FIELDS = _SOURCE_FIELDS | frozenset({
    "week1_rate", "week2_rate", "failure_count_change", "failure_rate_change", "cause",
})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def rate_facts(source: dict) -> dict:
    """Compute only facts supported by two bounded source periods."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact rate-source fields required")
    for key in _SOURCE_FIELDS:
        value = source[key]
        if type(value) is not int or not 0 <= value <= 100_000:
            raise ValueError(f"{key} must be a bounded nonnegative integer")
    if source["week1_requests"] == 0 or source["week2_requests"] == 0:
        raise ValueError("request counts must be positive")
    if (source["week1_failures"] > source["week1_requests"]
            or source["week2_failures"] > source["week2_requests"]):
        raise ValueError("failures cannot exceed requests")
    first = Fraction(source["week1_failures"], source["week1_requests"])
    second = Fraction(source["week2_failures"], source["week2_requests"])

    def direction(left: object, right: object) -> str:
        return "UP" if right > left else "DOWN" if right < left else "UNCHANGED"

    return {
        **source,
        "week1_rate": f"{first.numerator}/{first.denominator}",
        "week2_rate": f"{second.numerator}/{second.denominator}",
        "failure_count_change": direction(source["week1_failures"], source["week2_failures"]),
        "failure_rate_change": direction(first, second),
        "cause": "UNKNOWN",
    }


def review_rate_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Fail closed on unsupported claims; never award certification."""
    expected = rate_facts(source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _ANSWER_FIELDS:
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(key for key in _ANSWER_FIELDS
                          if type(answer[key]) is not type(expected[key]) or answer[key] != expected[key]))
    return not errors, errors
