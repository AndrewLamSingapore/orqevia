"""Exact, non-certifying review of the synthetic a04 weighted decision."""
from __future__ import annotations

import json


_SOURCE_FIELDS = frozenset({"reliability_weight", "speed_weight", "a_reliability",
                            "a_speed", "b_reliability", "b_speed"})
_ANSWER_FIELDS = _SOURCE_FIELDS | frozenset({"a_score", "b_score", "decision",
                                            "missing_tie_breaker"})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def weighted_facts(source: dict) -> dict:
    """Calculate the exact decision from bounded, fully specified weights and scores."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact weighted-source fields required")
    for key, value in source.items():
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError(f"{key} must be a bounded nonnegative integer")
    if source["reliability_weight"] + source["speed_weight"] == 0:
        raise ValueError("at least one weight is required")
    a_score = (source["reliability_weight"] * source["a_reliability"]
               + source["speed_weight"] * source["a_speed"])
    b_score = (source["reliability_weight"] * source["b_reliability"]
               + source["speed_weight"] * source["b_speed"])
    decision = "A" if a_score > b_score else "B" if b_score > a_score else "TIE"
    return {**source, "a_score": a_score, "b_score": b_score, "decision": decision,
            "missing_tie_breaker": decision == "TIE"}


def review_weighted_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject false arithmetic or an invented winner without granting certification."""
    expected = weighted_facts(source)
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
