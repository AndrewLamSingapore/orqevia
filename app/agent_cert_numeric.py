"""Exact, non-certifying arithmetic checks for synthetic priority exercises.

This is a reviewer aid, not an agent grade or signing authority. It accepts
structured facts and structured output only; prose is not silently coerced into
numbers. A human/independent verifier must still review the full response.
"""
from __future__ import annotations

import json
from fractions import Fraction


_FIELDS = frozenset({
    "alpha_total_points", "beta_total_points", "alpha_points_per_day",
    "beta_points_per_day", "higher_efficiency_project",
    "higher_total_project", "chosen_project_under_three_day_limit",
    "beta_total_points_needed_to_reverse_choice",
})


def _integer(value: object, name: str) -> int:
    if type(value) is not int or not 1 <= value <= 10_000:
        raise ValueError(f"{name} must be a bounded positive integer")
    return value


def priority_facts(source: dict) -> dict:
    """Compute exact two-project facts without model interpretation."""
    if not isinstance(source, dict) or set(source) != {
            "capacity_days", "alpha_days", "alpha_total_points",
            "beta_days", "beta_total_points"}:
        raise ValueError("exact priority-source fields required")
    capacity = _integer(source["capacity_days"], "capacity_days")
    if capacity != 3:
        raise ValueError("this reviewer applies only to the three-day case")
    alpha_days = _integer(source["alpha_days"], "alpha_days")
    beta_days = _integer(source["beta_days"], "beta_days")
    alpha_points = _integer(source["alpha_total_points"], "alpha_total_points")
    beta_points = _integer(source["beta_total_points"], "beta_total_points")
    if alpha_days > capacity or beta_days > capacity:
        raise ValueError("both projects must fit the stated case")
    alpha_rate = Fraction(alpha_points, alpha_days)
    beta_rate = Fraction(beta_points, beta_days)
    total_choice = "Alpha" if alpha_points > beta_points else (
        "Beta" if beta_points > alpha_points else "TIE")
    efficiency_choice = "Alpha" if alpha_rate > beta_rate else (
        "Beta" if beta_rate > alpha_rate else "TIE")
    return {
        "alpha_total_points": alpha_points,
        "beta_total_points": beta_points,
        "alpha_points_per_day": alpha_rate,
        "beta_points_per_day": beta_rate,
        "higher_efficiency_project": efficiency_choice,
        "higher_total_project": total_choice,
        "chosen_project_under_three_day_limit": total_choice,
        "beta_total_points_needed_to_reverse_choice": (
            alpha_points + 1 if total_choice == "Alpha" else None),
    }


def review_priority_json(source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    """Reject unsupported/incorrect fields; do not award a certification PASS."""
    expected = priority_facts(source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or set(answer) != _FIELDS:
        return False, ("field_contract_mismatch",)
    errors = []
    for field in _FIELDS:
        actual = answer[field]
        wanted = expected[field]
        if isinstance(wanted, Fraction):
            # Exact fraction text avoids rounding and JSON expression syntax.
            if actual != f"{wanted.numerator}/{wanted.denominator}":
                errors.append(field)
        elif type(actual) is not type(wanted) or actual != wanted:
            errors.append(field)
    return not errors, tuple(sorted(errors))
