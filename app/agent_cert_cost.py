"""Exact, non-certifying review of A21's synthetic fixed/variable cost case."""
from __future__ import annotations

import json
from fractions import Fraction


_SOURCE_FIELDS = frozenset({"fixed_cost", "variable_cost_per_unit", "volume"})
_ANSWER_FIELDS = _SOURCE_FIELDS | frozenset({
    "total_variable_cost", "total_cost", "average_cost_per_unit",
    "cost_at_next_unit", "incremental_cost_next_unit",
    "revenue_known", "profit_known",
})


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def cost_facts(source: dict) -> dict:
    """Derive bounded costs from source inputs, not the agent's answer."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact cost source required")
    if any(type(value) is not int or not 0 <= value <= 1_000_000
           for value in source.values()) or source["volume"] == 0:
        raise ValueError("bounded integer costs and positive volume required")
    fixed = source["fixed_cost"]
    variable = source["variable_cost_per_unit"]
    volume = source["volume"]
    total_variable = variable * volume
    total = fixed + total_variable
    average = Fraction(total, volume)
    return {
        **source,
        "total_variable_cost": total_variable,
        "total_cost": total,
        "average_cost_per_unit": f"{average.numerator}/{average.denominator}",
        "cost_at_next_unit": fixed + variable * (volume + 1),
        "incremental_cost_next_unit": variable,
        "revenue_known": False,
        "profit_known": False,
    }


def review_cost_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject incorrect arithmetic and unsupported claims; never award L7."""
    expected = cost_facts(source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _ANSWER_FIELDS:
        return False, ("field_contract_mismatch",)
    errors = tuple(key for key in sorted(_ANSWER_FIELDS)
                   if type(answer[key]) is not type(expected[key])
                   or answer[key] != expected[key])
    return not errors, errors
