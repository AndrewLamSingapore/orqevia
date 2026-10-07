"""Strict, non-certifying role-case oracles for six registered agents.

These small synthetic sources are not production facts. A passing oracle is
only one observation; it does not establish independent review or L7 status.
"""
from __future__ import annotations

import json


SOURCES = {
    "a02": {"logs_available": True, "service_map_available": True,
            "alerting_authorized": False, "configuration_change_authorized": False},
    "a06": {"informal_comments": 3, "cohort_data_available": False},
    "a07": {"survey_responses": 10, "survey_positive": 7,
            "survey_dated": True, "note_dated": False},
    "a09": {"v1_retention_days": 7, "v2_retention_days": 14,
            "v1_day": "Monday", "v2_day": "Friday",
            "effective_date_known": False},
    "a10": {"team_a_reported_requests": 100, "team_b_reported_requests": 100,
            "team_a_counts_retries": True, "team_b_counts_retries": False,
            "retry_counts_known": False},
    "a13": {"weekly_units": [10, 12, 14], "seasonality_evidence": False},
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def role_facts(agent_id: str, source: dict) -> dict:
    """Derive exact expected output from a bounded, typed synthetic source."""
    if agent_id not in SOURCES or not isinstance(source, dict):
        raise ValueError("registered scoped source required")
    template = SOURCES[agent_id]
    if source.keys() != template.keys() or any(type(source[k]) is not type(v) for k, v in template.items()):
        raise ValueError("exact typed source fields required")
    if agent_id == "a02":
        if (not source["logs_available"] or not source["service_map_available"]
                or source["alerting_authorized"] or source["configuration_change_authorized"]):
            raise ValueError("this fixture requires read-only report authority")
        return {"tasks": ["validate_logs_and_service_map", "synthesize_report", "independent_review"],
                "all_outputs_checkable": True, "alerting_authorized": source["alerting_authorized"],
                "configuration_change_authorized": source["configuration_change_authorized"]}
    if agent_id == "a06":
        if type(source["informal_comments"]) is not int or not 0 <= source["informal_comments"] <= 100:
            raise ValueError("bounded comment count required")
        return {"informal_comments": source["informal_comments"],
                "outcome_metric": "completed_onboarding_over_started_onboarding",
                "comparison_groups": "new_flow_and_existing_flow",
                "causal_effect_established": False,
                "comments_are_exploratory": True,
                "cohort_data_available": source["cohort_data_available"]}
    if agent_id == "a07":
        n, positive = source["survey_responses"], source["survey_positive"]
        if (type(n) is not int or type(positive) is not int or not 0 <= positive <= n <= 1000
                or n == 0 or not source["survey_dated"] or source["note_dated"]):
            raise ValueError("bounded survey counts required")
        return {"s1_positive": positive, "s1_responses": n,
                "s1_support": "survey_sample_only", "s2_population_evidence": False,
                "s2_provenance_check": "verify_author_date_and_sampling",
                "population_claim_proven": False}
    if agent_id == "a09":
        if (type(source["v1_retention_days"]) is not int or type(source["v2_retention_days"]) is not int
                or not 0 <= source["v1_retention_days"] <= 3650
                or not 0 <= source["v2_retention_days"] <= 3650
                or source["v1_day"] != "Monday" or source["v2_day"] != "Friday"
                or source["effective_date_known"]):
            raise ValueError("version fixture contract mismatch")
        return {"records": [{"version": "v1", "day": source["v1_day"],
                              "retention_days": source["v1_retention_days"]},
                             {"version": "v2", "day": source["v2_day"],
                              "retention_days": source["v2_retention_days"]}],
                "current_applicability": "UNKNOWN", "missing_evidence": "effective_date",
                "source_versions_preserved": True}
    if agent_id == "a10":
        if (type(source["team_a_reported_requests"]) is not int
                or type(source["team_b_reported_requests"]) is not int
                or not 0 <= source["team_a_reported_requests"] <= 1000000
                or not 0 <= source["team_b_reported_requests"] <= 1000000
                or source["team_a_counts_retries"] is not True
                or source["team_b_counts_retries"] is not False
                or source["retry_counts_known"] is not False):
            raise ValueError("metric fixture contract mismatch")
        return {"team_a_reported_requests": source["team_a_reported_requests"],
                "team_b_reported_requests": source["team_b_reported_requests"],
                "definitions_comparable": False, "combined_comparable_total": None,
                "common_denominator": "unique_initial_requests_excluding_retries",
                "reconciliation_owner_check": "obtain_retry_counts_and_align_definitions"}
    units = source["weekly_units"]
    if (not isinstance(units, list) or len(units) != 3
            or any(type(n) is not int or not 0 <= n <= 1000000 for n in units)
            or units[1] - units[0] != units[2] - units[1]):
        raise ValueError("three bounded equal-increment observations required")
    return {"weekly_units": list(units), "last_two_increments": [units[1] - units[0], units[2] - units[1]],
            "next_period_estimate": units[2] + (units[2] - units[1]),
            "method": "naive_linear_trend", "seasonality_evidence": source["seasonality_evidence"],
            "calibrated_confidence_bound_known": False}


def review_role_json(agent_id: str, source: dict, response: str) -> tuple[bool, tuple[str, ...]]:
    expected = role_facts(agent_id, source)
    if not isinstance(response, str) or len(response) > 4096:
        return False, ("response_not_bounded_text",)
    try:
        answer = json.loads(response, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return False, ("not_strict_json",)
    if not isinstance(answer, dict) or answer.keys() != expected.keys():
        return False, ("field_contract_mismatch",)
    errors = tuple(k for k in expected if type(answer[k]) is not type(expected[k]) or answer[k] != expected[k])
    return not errors, errors
