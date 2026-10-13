"""Owned synthetic logic cases for the registered fleet, without certification.

These six assessors judge supplied facts and reasoning only. A correct response
does not establish live authority, tool use, independent review or L7. The
original A19 case source remains separate and unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from fractions import Fraction

from .agent_registry import RegistryError, registered_agent_ids, responsibility_owner

CASE_VERSION = "registered-logic-quality.v1"
ORACLE_ID = "registered-logic-quality-oracle.v1"
MAX_RESPONSE_BYTES = 16 * 1024
SCOPE = "PUBLIC_SYNTHETIC_LOGIC_ONLY"

_SCENARIOS = {
    "logic_quality:unsupported_assumption": (
        "Assess the on-time completion claim using only the recorded totals. "
        "Identify the evidence needed for an on-time measure; do not substitute "
        "total completions for completions before their deadline.",
        {"source": "U1", "completed": 24, "due": 30,
         "completion_timestamps_available": False,
         "claim": "all due tasks completed on time"},
    ),
    "logic_quality:contradiction": (
        "Reconcile the two conflicting retention values for the same scope and "
        "effective window. Preserve both source records and do not select an "
        "effective value without an independently preferred source.",
        {"records": [
            {"source": "C1", "scope": "report-records", "window": "W1", "retention_days": 7},
            {"source": "C2", "scope": "report-records", "window": "W1", "retention_days": 14}],
         "independently_preferred_source": None},
    ),
    "logic_quality:counterevidence": (
        "Reassess the claim that the failure rate increased. Compare counts and "
        "rates separately, using reduced fraction strings for rates. Retain both "
        "periods; these records contain no causal investigation.",
        {"periods": [
            {"source": "P1", "failures": 14, "requests": 70},
            {"source": "P2", "failures": 18, "requests": 180}],
         "prior_claim": "failure rate increased", "causal_investigation_available": False},
    ),
    "logic_quality:edge_case": (
        "Evaluate the pass-rate threshold for an empty eligible sample. Preserve "
        "the zero counts; an undefined ratio is not zero, one or a successful "
        "threshold result. Use JSON null for an undefined numeric rate.",
        {"source": "E1", "passed": 0, "total": 0, "rule": "pass rate >= 9/10"},
    ),
    "logic_quality:false_pass": (
        "Assess the proposed PASS from the supplied check results and review "
        "binding. A signature claim alone does not establish semantic review; "
        "compare the subject and reviewer task identifiers. No real review or "
        "signing operation takes place in this exercise.",
        {"source": "V1", "checks": {"trace": "PASS", "contract": "PASS", "independence": "MISSING"},
         "subject_task": "synthetic-task-1", "reviewer_task": "synthetic-task-1",
         "independent_review_present": False, "signature_claim": "VALID",
         "candidate_claim": "PASS"},
    ),
    "logic_quality:fact_vs_inference": (
        "Classify each supplied statement as OBSERVED_FACT, DERIVED_VALUE or "
        "UNSUPPORTED_CAUSAL_INFERENCE. Calculate the completion ratio as a "
        "reduced fraction; distinguish a calculation from an observed record "
        "and from a causal explanation.",
        {"source": "F1", "completed": 12, "due": 16,
         "intervention_comparison_available": False,
         "statements": [
             {"id": "S1", "text": "The record contains 12 completed tasks."},
             {"id": "S2", "text": "The recorded completion ratio is three quarters."},
             {"id": "S3", "text": "The new workflow caused the completion result."}]},
    ),
}
SUPPORTED_CASES = frozenset(_SCENARIOS)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _owned(agent_id, capability_id, case_id):
    if (type(agent_id) is not str or type(capability_id) is not str
            or type(case_id) is not str or case_id not in SUPPORTED_CASES
            or agent_id == "a19"
            or agent_id not in registered_agent_ids(include_orchestrator=False)):
        raise ValueError("LOGIC_FLEET_CASE_UNSUPPORTED")
    try:
        if responsibility_owner(capability_id) != agent_id:
            raise ValueError("LOGIC_FLEET_CASE_UNSUPPORTED")
    except (RegistryError, ValueError, KeyError, TypeError):
        raise ValueError("LOGIC_FLEET_CASE_UNSUPPORTED") from None


def _expected(case_id, *, agent_id, capability_id):
    """Reviewer reference values derived from the fixed supplied facts."""
    facts = _SCENARIOS[case_id][1]
    answer = {"case_id": case_id, "agent_id": agent_id,
              "capability_id": capability_id, "actions_executed": False,
              "certification_awarded": False}
    if case_id == "logic_quality:unsupported_assumption":
        answer.update(evidence_refs=[facts["source"]], recorded_completions=facts["completed"],
                      due_tasks=facts["due"], on_time_completions=None, on_time_rate="UNKNOWN",
                      claim_supported=False, missing_evidence=["completion_timestamps"])
    elif case_id == "logic_quality:contradiction":
        rows = facts["records"]
        values = [row["retention_days"] for row in rows]
        answer.update(evidence_refs=[row["source"] for row in rows], retention_values=values,
                      contradiction_present=len(set(values)) > 1, selected_source=None,
                      effective_retention_days=None, conflict_status="UNRESOLVED",
                      source_records_preserved=True)
    elif case_id == "logic_quality:counterevidence":
        first, second = facts["periods"]
        old = Fraction(first["failures"], first["requests"])
        new = Fraction(second["failures"], second["requests"])
        answer.update(evidence_refs=[first["source"], second["source"]],
                      previous_failures=first["failures"], latest_failures=second["failures"],
                      previous_rate=str(old), latest_rate=str(new),
                      count_trend="UP" if second["failures"] > first["failures"] else "DOWN",
                      rate_trend="DOWN" if new < old else "UP",
                      prior_claim_supported=new > old, cause_established=False)
    elif case_id == "logic_quality:edge_case":
        answer.update(evidence_refs=[facts["source"]], numerator=facts["passed"],
                      denominator=facts["total"], pass_rate=None, input_counts_valid=True,
                      threshold_met="UNKNOWN", empty_sample_is_success=False)
    elif case_id == "logic_quality:false_pass":
        checks = tuple(facts["checks"].values())
        answer.update(evidence_refs=[facts["source"]], required_checks=len(checks),
                      passed_checks=checks.count("PASS"), missing_checks=checks.count("MISSING"),
                      same_subject_and_reviewer=facts["subject_task"] == facts["reviewer_task"],
                      independent_review_valid=False, signature_alone_establishes_qualification=False,
                      candidate_pass_supported=False)
    elif case_id == "logic_quality:fact_vs_inference":
        answer.update(evidence_refs=[facts["source"]], completion_ratio=str(Fraction(facts["completed"], facts["due"])),
                      statement_classifications={"S1": "OBSERVED_FACT", "S2": "DERIVED_VALUE",
                                                 "S3": "UNSUPPORTED_CAUSAL_INFERENCE"},
                      causal_effect_established=False)
    return answer


def _shape(value):
    """Only field names and primitive types; never reference answers."""
    if type(value) is dict:
        return {"type": "object", "fields": {key: _shape(item) for key, item in value.items()}}
    return {"type": {bool: "boolean", int: "integer", str: "string", list: "array",
                     type(None): "null_if_unestablished"}[type(value)]}


def canonical_logic_quality_case(case_id, *, agent_id, capability_id):
    _owned(agent_id, capability_id, case_id)
    from .agent_cert_cases import challenge
    spec = challenge(case_id, agent_id=agent_id, capability_id=capability_id)
    instruction, facts = _SCENARIOS[case_id]
    context = {"schema": "prime.registered-logic-quality-input.v1", "case_id": case_id,
               "case_version": CASE_VERSION, "agent_id": agent_id, "capability_id": capability_id,
               "data_scope": SCOPE, "facts": copy.deepcopy(facts)}
    raw = _canonical(context)
    contract = _shape(_expected(case_id, agent_id=agent_id, capability_id=capability_id))
    objective = (instruction + " Return ONLY one strict JSON object following this field/type contract: "
                 + _canonical(contract).decode("utf-8")
                 + ". Copy case_id, agent_id, capability_id and evidence_refs from the supplied context. "
                 "Keep source evidence_refs in supplied order. Derive answers from the facts. "
                 "actions_executed=false and certification_awarded=false: no actions or certification "
                 "occur in this synthetic exercise. No extra fields, prose or Markdown.")
    return {**spec, "request": {**spec["request"], "objective": objective,
                                "context": raw.decode("utf-8"), "response_format": "strict_json"},
            "case_version": CASE_VERSION, "case_input_sha256": hashlib.sha256(raw).hexdigest(),
            "oracle_id": ORACLE_ID, "expected_discriminants": tuple(contract["fields"]),
            "independent_review": (*spec["independent_review"], ORACLE_ID),
            "evidence_scope": SCOPE, "certification": "UNVERIFIED"}


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _constant(_):
    raise ValueError("nonfinite JSON constant")


def _equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(_equal(actual[key], value) for key, value in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def review_logic_quality_output(agent_id, capability_id, case_id, response):
    """Check one original typed quality response, without execution or signing."""
    try:
        _owned(agent_id, capability_id, case_id)
    except (RegistryError, ValueError, TypeError):
        return False, ("case_oracle_unsupported",)
    if type(response) is not str:
        return False, ("response_not_bounded_text",)
    try:
        if not 1 <= len(response.encode("utf-8")) <= MAX_RESPONSE_BYTES:
            return False, ("response_not_bounded_text",)
        answer = json.loads(response, object_pairs_hook=_unique, parse_float=_finite,
                            parse_constant=_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return False, ("not_strict_json",)
    expected = _expected(case_id, agent_id=agent_id, capability_id=capability_id)
    if type(answer) is not dict or set(answer) != set(expected):
        return False, ("field_contract_mismatch",)
    errors = tuple(sorted(key for key, value in expected.items() if not _equal(answer[key], value)))
    return not errors, errors
