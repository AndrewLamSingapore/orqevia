"""Exact, non-certifying review of A05's synthetic one-slot portfolio case."""
from __future__ import annotations

import json


_FIELDS = frozenset({"available_slots", "p_slots", "q_slots",
                     "p_expected_value", "q_expected_value", "selected_project",
                     "selected_slots", "selected_expected_value",
                     "values_are_estimates", "both_feasible_together"})
_SOURCE_FIELDS = frozenset({"available_slots", "p_slots", "q_slots",
                            "p_expected_value", "q_expected_value"})


def _unique(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def portfolio_facts(source: dict) -> dict:
    """Derive the decision from bounded source facts, never the worker answer."""
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("exact portfolio source required")
    if any(type(value) is not int or not 0 < value <= 1_000_000
           for value in source.values()):
        raise ValueError("positive bounded integer facts required")
    capacity = source["available_slots"]
    p_slots, q_slots = source["p_slots"], source["q_slots"]
    if (capacity, p_slots, q_slots) != (1, 1, 1):
        raise ValueError("source is not the bounded one-slot decision")
    if source["p_expected_value"] == source["q_expected_value"]:
        raise ValueError("tie requires a separate case")
    chosen = "P" if source["p_expected_value"] > source["q_expected_value"] else "Q"
    return {**source, "selected_project": chosen,
            "selected_slots": source[chosen.lower() + "_slots"],
            "selected_expected_value": source[chosen.lower() + "_expected_value"],
            "values_are_estimates": True, "both_feasible_together": False}


def review_portfolio_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject false capacity/value claims; never award certification."""
    expected = portfolio_facts(source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _FIELDS:
        return False, ("field_contract_mismatch",)
    errors = tuple(key for key in sorted(_FIELDS)
                   if type(answer[key]) is not type(expected[key])
                   or answer[key] != expected[key])
    return not errors, errors
