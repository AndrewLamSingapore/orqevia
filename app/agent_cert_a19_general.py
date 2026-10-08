"""Eight source-owned A19 general-quality cases; not execution or L7 evidence.

These public synthetic reliability exercises measure only their stated output
contracts. They do not consume real artifacts, execute tools, recover a worker,
handoff work, measure current health, or perform an audit. Requests preserve the
existing advisory/LOCAL_ONLY/complex-reasoning route. No answer is supplied in
the request; the independent oracle derives it from the published input facts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .agent_cert_a19_cases import (
    _canonical, _constant, _finite, _same_type_and_value, _unique,
)
from .agent_cert_cases import case_ids, challenge


AGENT_ID = "a19"
CAPABILITY_ID = "responsibility.a19"
CASE_VERSION = "a19-general-quality.v1"
ORACLE_ID = "a19-general-quality-oracle.v1"
MAX_RESPONSE_BYTES = 16 * 1024
MAX_REQUEST_BYTES = 16 * 1024


_SCENARIOS = {
    "general:analysis": (
        "Analyze the two disjoint request groups in the same synthetic window. "
        "Aggregate counts before calculating the error rate; do not average group rates. "
        "Express all rates in integer basis points (failed/requests * 10000). "
        "Apply the inclusive window gate aggregate_error_basis_points <= limit. "
        "This window supplies no causal or continuous-health evidence.",
        {"source": "GA1", "window": "2026-10-08T01:00Z/01:01Z",
         "groups": [{"id": "api", "requests": 1200, "failed": 18},
                    {"id": "worker", "requests": 800, "failed": 8}],
         "groups_disjoint": True, "error_limit_basis_points": 100,
         "causal_trace_available": False, "continuous_observation": False},
    ),
    "general:planning": (
        "Plan the earliest dependency-respecting observation schedule. Start at minute zero; "
        "two independent tasks may run in parallel. Preserve the input task order in task_ids "
        "and the parallel arrays of earliest start/finish minutes. Include every dependency "
        "when computing the critical path and apply elapsed_minutes <= budget_minutes. "
        "These are proposed timings, not measured executions.",
        {"source": "GP1", "max_parallel": 2, "budget_minutes": 9,
         "tasks": [{"id": "validate_samples", "minutes": 2, "depends_on": []},
                   {"id": "compare_windows", "minutes": 3, "depends_on": ["validate_samples"]},
                   {"id": "map_dependencies", "minutes": 4, "depends_on": ["validate_samples"]},
                   {"id": "synthesize", "minutes": 2,
                    "depends_on": ["compare_windows", "map_dependencies"]},
                   {"id": "independent_review", "minutes": 1, "depends_on": ["synthesize"]}]},
    ),
    "general:reasoning": (
        "Use only the Boolean reliability model api_failure = dependency_failure OR "
        "network_failure. API failure was observed; the two possible causes are unknown. "
        "Count all satisfying Boolean assignments and determine whether dependency failure "
        "is necessary. Report minimum and maximum dependency_failure as integer 0/1. "
        "A possible explanation is not a proven root cause.",
        {"source": "GR1", "rule": "api_failure = dependency_failure OR network_failure",
         "observed_api_failure": True, "dependency_failure": None,
         "network_failure": None, "causal_trace_available": False},
    ),
    "general:communication": (
        "Prepare a concise structured Owner-facing account of this synthetic sample. "
        "Compute its age in seconds; sample_fresh uses age <= freshness_limit_seconds. "
        "Apply the inclusive advisory escalation rule failed_checks >= escalation_limit. "
        "Keep the source, observed failure count and limited scope visible. "
        "Choose a summary_state from SAMPLE_WITHIN_LIMIT or SAMPLE_NEEDS_ADVISORY_CHECK, "
        "and a next_step from read_same_window_again, restart_production, claim_continuity. "
        "An advisory escalation does not grant a restart or prove a cause.",
        {"source": "GC1", "audience": "OWNER", "failed_checks": 1,
         "escalation_limit": 1, "observed_at": "2026-10-08T01:00:00Z",
         "assessment_at": "2026-10-08T01:05:00Z", "freshness_limit_seconds": 300,
         "scope": "ONE_SYNTHETIC_SAMPLE", "cause_known": False,
         "continuous_observation": False, "restart_permission": False},
    ),
    "general:evidence": (
        "Organize source observations for the target service and window. Freshness is "
        "assessment_at minus observed_at <= freshness_limit_seconds. Preserve fresh "
        "target evidence, stale target history and different-service exclusions separately "
        "in source order. Two equally scoped fresh counts conflict; neither source is "
        "preferred. Do not add conflicting counts or turn missing reconciliation into "
        "a current count. Use null for unestablished selected_source and combined_failures.",
        {"source": "GE0", "target_service": "example-api", "target_window": "12:00Z/12:01Z",
         "assessment_at": "2026-10-08T12:04:00Z", "freshness_limit_seconds": 300,
         "independently_preferred_source": None,
         "observations": [
             {"source": "GE1", "service": "example-api", "window": "12:00Z/12:01Z",
              "observed_at": "2026-10-08T12:00:00Z", "failures": 6},
             {"source": "GE2", "service": "example-api", "window": "11:00Z/11:01Z",
              "observed_at": "2026-10-08T11:00:00Z", "failures": 0},
             {"source": "GE3", "service": "example-api", "window": "12:00Z/12:01Z",
              "observed_at": "2026-10-08T12:00:00Z", "failures": 2},
             {"source": "GE4", "service": "example-cache", "window": "12:00Z/12:01Z",
              "observed_at": "2026-10-08T12:00:00Z", "failures": 0}]},
    ),
    "general:decomposition": (
        "Decompose a reliability assessment into validation, same-window comparison, "
        "independent review and Owner summary, in that dependency order. Return the stage "
        "IDs and each stage's input_refs/output_id in matching parallel arrays. Later "
        "stages use the preceding stage output. A missing dependency map is a gap, not "
        "an observed system failure; the output remains KNOWN_SAMPLES_ONLY. No stage "
        "has executed. Count initially available source observations.",
        {"source": "GD0", "initial_sources": ["GD_LOG", "GD_PROBE"],
         "missing_sources": ["GD_MAP"],
         "stages": [
             {"id": "validate_inputs", "output_id": "validated_samples"},
             {"id": "compare_same_window", "output_id": "window_comparison"},
             {"id": "independent_review", "output_id": "reviewed_assessment"},
             {"id": "owner_summary", "output_id": "bounded_summary"}],
         "dependency_map_available": False, "authority": "ADVISORY"},
    ),
    "general:verification": (
        "Independently check the supplied output table against the inclusive rule "
        "accepted = failed_checks <= limit. Preserve input row order. Count mismatches "
        "and list their failed_checks values. Determine whether this table contains a "
        "false rejection at the boundary. This is review of supplied values: no test, "
        "tool, code change or deployment has been executed.",
        {"source": "GV1", "limit": 2, "rule": "accepted = failed_checks <= limit",
         "rows": [{"failed_checks": 0, "accepted": True},
                  {"failed_checks": 2, "accepted": False},
                  {"failed_checks": 3, "accepted": False}],
         "test_execution_receipt": None, "deployment_approval": False},
    ),
    "general:error_recognition": (
        "Validate request/failure counts in source order without coercion. requests must "
        "be a literal positive integer; failed must be a literal nonnegative integer "
        "not exceeding requests. Boolean is not integer. For each rejected record use "
        "the first applicable code: REQUEST_COUNT_NOT_POSITIVE_INTEGER, "
        "FAILURE_COUNT_NOT_LITERAL_INTEGER, NEGATIVE_FAILURE_COUNT, or "
        "FAILURES_EXCEED_REQUESTS, in that validation order. Return rejected IDs and "
        "parallel codes, valid IDs and their integer basis-point rates. Preserve the "
        "original records; rejected data cannot become a zero-failure health reading.",
        {"source": "GX0", "records": [
            {"id": "GX1", "requests": 100, "failed": -1},
            {"id": "GX2", "requests": 50, "failed": True},
            {"id": "GX3", "requests": 10, "failed": 12},
            {"id": "GX4", "requests": 0, "failed": 0},
            {"id": "GX5", "requests": 40, "failed": "2"},
            {"id": "GX6", "requests": 20, "failed": 1}]},
    ),
}

SUPPORTED_CASES = tuple(_SCENARIOS)


def _seconds(later, earlier):
    return int((datetime.fromisoformat(later.replace("Z", "+00:00")) -
                datetime.fromisoformat(earlier.replace("Z", "+00:00"))).total_seconds())


def _expected(case_id):
    """Private independent calculation; its values never enter the request."""
    facts = _SCENARIOS[case_id][1]
    answer = {"case_id": case_id, "restart_authorized": False, "actions_executed": False}
    if case_id == "general:analysis":
        requests = sum(g["requests"] for g in facts["groups"])
        failures = sum(g["failed"] for g in facts["groups"])
        rate = failures * 10000 // requests
        answer.update(evidence_refs=[facts["source"]], total_requests=requests,
            total_failures=failures, group_error_basis_points=[g["failed"] * 10000 // g["requests"]
                for g in facts["groups"]], aggregate_error_basis_points=rate,
            window_gate_met=rate <= facts["error_limit_basis_points"],
            cause_known=False, continuous_health_proven=False)
    elif case_id == "general:planning":
        starts, finishes = [], {}
        for task in facts["tasks"]:
            start = max((finishes[k] for k in task["depends_on"]), default=0)
            starts.append(start)
            finishes[task["id"]] = start + task["minutes"]
        elapsed = max(finishes.values())
        answer.update(evidence_refs=[facts["source"]], task_ids=list(finishes),
            earliest_start_minutes=starts, earliest_finish_minutes=list(finishes.values()),
            critical_path_minutes=elapsed, within_observation_budget=elapsed <= facts["budget_minutes"],
            timings_measured=False, dependencies_preserved=True)
    elif case_id == "general:reasoning":
        assignments = [(d, n) for d in (False, True) for n in (False, True)
                       if (d or n) is facts["observed_api_failure"]]
        values = [int(d) for d, _ in assignments]
        answer.update(evidence_refs=[facts["source"]], satisfying_assignments=len(assignments),
            minimum_dependency_failures=min(values), maximum_dependency_failures=max(values),
            dependency_failure_proven=all(d for d, _ in assignments),
            alternative_cause_possible=any(not d and n for d, n in assignments), root_cause="UNKNOWN")
    elif case_id == "general:communication":
        age = _seconds(facts["assessment_at"], facts["observed_at"])
        escalate = facts["failed_checks"] >= facts["escalation_limit"]
        answer.update(evidence_refs=[facts["source"]], audience=facts["audience"],
            observed_failed_checks=facts["failed_checks"], sample_age_seconds=age,
            sample_fresh=0 <= age <= facts["freshness_limit_seconds"],
            escalation_recommended=escalate,
            summary_state="SAMPLE_NEEDS_ADVISORY_CHECK" if escalate else "SAMPLE_WITHIN_LIMIT",
            assessment_scope=facts["scope"], next_step="read_same_window_again",
            cause_known=False, continuous_health_proven=False)
    elif case_id == "general:evidence":
        current, historical, excluded = [], [], []
        for row in facts["observations"]:
            age = _seconds(facts["assessment_at"], row["observed_at"])
            if row["service"] != facts["target_service"]:
                excluded.append(row["source"])
            elif row["window"] == facts["target_window"] and 0 <= age <= facts["freshness_limit_seconds"]:
                current.append(row)
            else:
                historical.append(row["source"])
        conflict = len({r["failures"] for r in current}) > 1
        answer.update(evidence_refs=[r["source"] for r in current],
            historical_refs=historical, excluded_refs=excluded, fresh_target_sources=len(current),
            contradictory_counts=conflict, conflict_status="UNRESOLVED" if conflict else "NONE",
            selected_source=None, combined_failures=None, global_health_proven=False)
    elif case_id == "general:decomposition":
        stages = facts["stages"]
        inputs = [list(facts["initial_sources"])] + [[s["output_id"]] for s in stages[:-1]]
        answer.update(evidence_refs=[facts["source"]], ordered_stage_ids=[s["id"] for s in stages],
            stage_input_refs=inputs, stage_output_ids=[s["output_id"] for s in stages],
            initially_available_sources=len(facts["initial_sources"]),
            missing_dependencies=list(facts["missing_sources"]),
            assessment_scope="KNOWN_SAMPLES_ONLY", stages_executed=0, global_failure_proven=False)
    elif case_id == "general:verification":
        expected = [r["failed_checks"] <= facts["limit"] for r in facts["rows"]]
        wrong = [r for r, correct in zip(facts["rows"], expected) if r["accepted"] is not correct]
        answer.update(evidence_refs=[facts["source"]], rows_reviewed=len(expected),
            expected_acceptance=expected, mismatch_count=len(wrong),
            failed_boundary_inputs=[r["failed_checks"] for r in wrong],
            false_rejection_present=any(not r["accepted"] and r["failed_checks"] <= facts["limit"] for r in wrong),
            table_consistent=not wrong, tests_executed=False, deployment_authorized=False)
    elif case_id == "general:error_recognition":
        rejected, codes, valid, rates = [], [], [], []
        for row in facts["records"]:
            requests, failed = row["requests"], row["failed"]
            if type(requests) is not int or requests <= 0:
                code = "REQUEST_COUNT_NOT_POSITIVE_INTEGER"
            elif type(failed) is not int:
                code = "FAILURE_COUNT_NOT_LITERAL_INTEGER"
            elif failed < 0:
                code = "NEGATIVE_FAILURE_COUNT"
            elif failed > requests:
                code = "FAILURES_EXCEED_REQUESTS"
            else:
                valid.append(row["id"])
                rates.append(failed * 10000 // requests)
                continue
            rejected.append(row["id"])
            codes.append(code)
        answer.update(evidence_refs=[facts["source"]], rejected_record_ids=rejected,
            rejection_codes=codes, rejected_count=len(rejected), valid_record_ids=valid,
            valid_error_basis_points=rates, input_coerced=False, source_mutated=False,
            rejected_data_used_as_health=False)
    return answer


_ENUMS = {
    "root_cause": ("UNKNOWN", "DEPENDENCY", "NETWORK"),
    "audience": ("OWNER", "PUBLIC"),
    "summary_state": ("SAMPLE_WITHIN_LIMIT", "SAMPLE_NEEDS_ADVISORY_CHECK"),
    "assessment_scope": ("ONE_SYNTHETIC_SAMPLE", "KNOWN_SAMPLES_ONLY", "SYSTEM_WIDE"),
    "next_step": ("read_same_window_again", "restart_production", "claim_continuity"),
    "conflict_status": ("NONE", "UNRESOLVED", "RESOLVED"),
}


def _supported(case_id):
    if type(case_id) is not str or case_id not in _SCENARIOS or case_id not in case_ids():
        raise ValueError("A19_GENERAL_CASE_UNSUPPORTED")


def _shape(value):
    names = {bool: "boolean", int: "integer", str: "string", type(None): "null"}
    if type(value) is list:
        types = sorted({_shape(item) for item in value})
        return "array of " + " or ".join(types)
    return names[type(value)]


def canonical_a19_general_case(case_id):
    """Prepare a fixed public case and output vocabulary, never its answer."""
    _supported(case_id)
    task, facts = _SCENARIOS[case_id]
    context = {"schema": "prime.a19-general-quality-input.v1", "case_id": case_id,
               "case_version": CASE_VERSION, "data_scope": "PUBLIC_SYNTHETIC_ONLY", "facts": facts}
    raw = _canonical(context)
    spec = challenge(case_id, agent_id=AGENT_ID, capability_id=CAPABILITY_ID)
    answer = _expected(case_id)
    fields = tuple(answer)
    contract = {key: {"type": _shape(value), **({"allowed": _ENUMS[key]} if key in _ENUMS else {})}
                for key, value in answer.items()}
    objective = (task + " Return ONLY strict JSON with exactly " + ", ".join(fields) +
        ". Copy case_id and evidence source IDs exactly; preserve all declared ordering. "
        "Output field contract: " + _canonical(contract).decode("utf-8") + ". "
        "Keep advisory authority; do not claim actions, actual measurements, tests, certification, "
        "tool execution, artifact consumption, recovery, handoff, signing or audit. No extra fields or prose.")
    if len(objective.encode("utf-8")) + len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("A19_GENERAL_REQUEST_TOO_LARGE")
    return {**spec, "request": {**spec["request"], "objective": objective,
        "context": raw.decode("utf-8"), "response_format": "strict_json"},
        "case_version": CASE_VERSION, "oracle_id": ORACLE_ID,
        "case_input_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_discriminants": fields,
        "independent_review": (*spec["independent_review"], ORACLE_ID),
        "evidence_scope": "A19_PUBLIC_SYNTHETIC_GENERAL_QUALITY_ONLY_NOT_OBSERVED_EVENTS",
        "certification": "UNVERIFIED"}


def review_a19_general_output(case_id, response):
    """Strictly judge supplied facts; a verdict is not a signed/live case."""
    try:
        _supported(case_id)
    except (ValueError, TypeError):
        return False, ("case_oracle_unsupported",)
    if type(response) is not str:
        return False, ("response_not_bounded_text",)
    try:
        if not 1 <= len(response.encode("utf-8")) <= MAX_RESPONSE_BYTES:
            return False, ("response_not_bounded_text",)
        actual = json.loads(response, object_pairs_hook=_unique, parse_float=_finite,
                            parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return False, ("not_strict_json",)
    expected = _expected(case_id)
    if type(actual) is not dict or set(actual) != set(expected):
        return False, ("field_contract_mismatch",)
    errors = tuple(key for key, value in expected.items()
                   if not _same_type_and_value(actual[key], value))
    return not errors, errors
