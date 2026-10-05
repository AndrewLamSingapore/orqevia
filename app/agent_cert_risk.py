"""Exact, non-certifying review of the synthetic A28 risk ranking."""
from __future__ import annotations

import json


_SOURCE_FIELDS = frozenset({"a_likelihood", "a_impact", "b_likelihood", "b_impact"})
_ANSWER_FIELDS = _SOURCE_FIELDS | frozenset({
    "a_score", "b_score", "priority", "calibrated_probability_known",
    "residual_risk_known",
})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def risk_facts(source: dict) -> dict:
    """Rank two ordinal-scale risks; do not infer likelihood probabilities."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact risk-source fields required")
    for key, value in source.items():
        if type(value) is not int or not 1 <= value <= 5:
            raise ValueError(f"{key} must be an ordinal integer from 1 to 5")
    a_score = source["a_likelihood"] * source["a_impact"]
    b_score = source["b_likelihood"] * source["b_impact"]
    return {**source, "a_score": a_score, "b_score": b_score,
            "priority": "A" if a_score > b_score else "B" if b_score > a_score else "TIE",
            "calibrated_probability_known": False, "residual_risk_known": False}


def review_risk_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject incorrect rankings and unsupported quantitative claims."""
    expected = risk_facts(source)
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
