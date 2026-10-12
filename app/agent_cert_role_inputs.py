"""Source-bound typed rendering of RAW source inputs for the 21 normal role cases.

Source context inspected: 18ec93990eeccdbde60b85b32f5f5e0f0cb7849d.
Selected only by the explicit role:normal_structured task contract.

Every fact below is supplied by the canonical request.context, not calculated
from an oracle or copied from a model response. Counts, units, observations,
requirements, claims, and stated absence of evidence are input facts. No
comparison, score, rate, forecast, feasibility decision, corrected program,
role acceptance, current runtime verdict, or certification is derived here.

The original context is retained exactly and must match before these typed
inputs are offered. Changing the source text requires explicit review of the
rendering; matching a role ID alone is insufficient. These are source-specific
normal-case inputs, not generic role knowledge or production telemetry.

The raw service samples in a19 and underlying counts in a26 are SYNTHETIC
source observations. They are not verdicts about this model run or live service.
A typed source rendering is a task-input clarification, never an agent output.
Pin this new task/source revision and rerun; do not regrade or
replace existing failures, receipts, or oracle criteria.
"""

from __future__ import annotations

from copy import deepcopy
import json


INPUT_VERSION = "normal-role-raw-input-facts.v1"
CANONICAL_SOURCE = "18ec93990eeccdbde60b85b32f5f5e0f0cb7849d"

_SOURCE_CONTEXTS = {
    "a01": "SYNTHETIC: Alpha needs 3 engineer-days and yields 8 TOTAL estimated points; Beta needs 2 engineer-days and yields 6 TOTAL estimated points; only 3 days are available; no third project exists.",
    "a02": "SYNTHETIC: deliver a read-only weekly incident report; inputs are logs and service map; no alerting or configuration change approved.",
    "a04": "SYNTHETIC: reliability weight 2, speed weight 1; option A scores 4 reliability and 1 speed; B scores 2 reliability and 5 speed.",
    "a05": "SYNTHETIC: P needs one slot, expected value 8; Q needs one slot, expected value 5; both are independent; one slot available.",
    "a06": "SYNTHETIC: claim is that a new onboarding flow reduces drop-off; only three informal comments exist; no cohort data.",
    "a07": "SYNTHETIC: source S1 is a dated 10-user survey with 7 positives; S2 is an undated note saying everyone likes it.",
    "a09": "SYNTHETIC: policy v1 dated Monday says 7-day retention; policy v2 dated Friday says 14-day retention; applicability date is unknown.",
    "a10": "SYNTHETIC: team A counts retries as requests; team B excludes retries; both report 100 requests; retry counts are unavailable.",
    "a12": "SYNTHETIC: week 1 has 10 failures in 100 requests; week 2 has 15 failures in 300 requests.",
    "a13": "SYNTHETIC: weekly units are 10, 12, 14; use the last two increments as a naive linear trend; no seasonality evidence.",
    "a14": "SYNTHETIC: rows (id=1, amount=5), (id=1, amount=5), (id=2, amount=-3); IDs must be unique; amounts nonnegative.",
    "a15": "SYNTHETIC: parser contract accepted=true; implementer=Builder; reviewer=Verifier; both are distinct; deployment approval=false.",
    "a16": "SYNTHETIC: report query is read-only; source API timed out; cached answer age=24 hours; freshness limit=2 hours; no write path authorized.",
    "a17": "SYNTHETIC: accept integer 0 through 9 inclusive; reject negatives, 10, and non-integers; return normalized integer or error.",
    "a18": "SYNTHETIC requirement: is_nonnegative(n) returns True for n >= 0. Proposed Python implementation: def is_nonnegative(n): return n > 0. No test results are supplied.",
    "a19": "SYNTHETIC: example-api check at 10:00Z failed; retry at 10:01Z passed; no later samples or dependency map; agent authority is advisory.",
    "a20": "SYNTHETIC: 100 units sold at USD 20 each; variable cost USD 12 per unit; fixed costs unknown; no market demand data.",
    "a21": "SYNTHETIC: fixed cost 100, variable cost 3 per unit, volume 20; revenue is not supplied.",
    "a26": "SYNTHETIC: candidate claims 100% success and marks ready; underlying record has 19 passes and 1 failure among 20 required checks; no signed attestation exists.",
    "a28": "SYNTHETIC: risk A likelihood 2, impact 5; risk B likelihood 4, impact 2; score is product; each scale is an ordinal estimate from 1 through 5; no controls or calibrated frequencies are supplied.",
    "a29": "SYNTHETIC: source_revision=abc123; source_tests_pass=true; historical_deployment_revision=def456; current_runtime_receipt_present=false. No current runtime identity or independent promotion approval is supplied.",
}


_RAW_INPUT_FACTS = {
    "a01": {
        "available_engineer_days": 3,
        "projects": [
            {
                "name": "Alpha",
                "required_engineer_days": 3,
                "estimated_points": {"value": 8, "basis": "TOTAL"},
            },
            {
                "name": "Beta",
                "required_engineer_days": 2,
                "estimated_points": {"value": 6, "basis": "TOTAL"},
            },
        ],
        "third_project_exists": False,
    },
    "a02": {
        "requested_deliverable": "weekly incident report",
        "read_only": True,
        "supplied_inputs": ["logs", "service map"],
        "alerting_approved": False,
        "configuration_change_approved": False,
    },
    "a04": {
        "criterion_weights": {"reliability": 2, "speed": 1},
        "option_criterion_scores": [
            {"option": "A", "reliability": 4, "speed": 1},
            {"option": "B", "reliability": 2, "speed": 5},
        ],
    },
    "a05": {
        "available_slots": 1,
        "projects_are_independent": True,
        "projects": [
            {"name": "P", "required_slots": 1, "expected_value": 8},
            {"name": "Q", "required_slots": 1, "expected_value": 5},
        ],
    },
    "a06": {
        "supplied_claim": "a new onboarding flow reduces drop-off",
        "informal_comment_count": 3,
        "cohort_data_supplied": False,
    },
    "a07": {
        "sources": [
            {
                "identifier": "S1",
                "kind": "survey",
                "dated": True,
                "respondents": 10,
                "positive_responses": 7,
            },
            {
                "identifier": "S2",
                "kind": "note",
                "dated": False,
                "supplied_text": "everyone likes it",
            },
        ],
    },
    "a09": {
        "policy_records": [
            {"version": "v1", "stated_day": "Monday", "retention_days": 7},
            {"version": "v2", "stated_day": "Friday", "retention_days": 14},
        ],
        "applicability_date_known": False,
    },
    "a10": {
        "reported_metrics": [
            {"team": "A", "reported_request_count": 100, "includes_retries": True},
            {"team": "B", "reported_request_count": 100, "includes_retries": False},
        ],
        "retry_counts_available": False,
    },
    "a12": {
        "observed_period_counts": [
            {"period": "week 1", "failures": 10, "requests": 100},
            {"period": "week 2", "failures": 15, "requests": 300},
        ],
    },
    "a13": {
        "observed_weekly_units": [10, 12, 14],
        "requested_extrapolation_method": "use the last two increments as a naive linear trend",
        "seasonality_evidence_supplied": False,
    },
    "a14": {
        "source_rows": [
            {"id": 1, "amount": 5},
            {"id": 1, "amount": 5},
            {"id": 2, "amount": -3},
        ],
        "supplied_validation_rules": {
            "ids_must_be_unique": True,
            "amounts_must_be_nonnegative": True,
        },
    },
    "a15": {
        "parser_contract_accepted": True,
        "supplied_implementer": "Builder",
        "supplied_reviewer": "Verifier",
        "roles_are_distinct_as_stated": True,
        "deployment_approval": False,
    },
    "a16": {
        "report_query_is_read_only": True,
        "source_api_timed_out": True,
        "cached_answer_age_hours": 24,
        "supplied_freshness_limit_hours": 2,
        "write_path_authorized": False,
    },
    "a17": {
        "supplied_parser_requirement": {
            "accepted_type": "integer",
            "inclusive_lower_bound": 0,
            "inclusive_upper_bound": 9,
            "reject_negatives": True,
            "explicit_rejected_integer": 10,
            "reject_nonintegers": True,
            "output_requirement": "normalized integer or error",
        },
    },
    "a18": {
        "supplied_requirement": "is_nonnegative(n) returns True for n >= 0",
        "proposed_python_implementation": "def is_nonnegative(n): return n > 0",
        "test_results_supplied": False,
    },
    "a19": {
        "service_identifier": "example-api",
        "supplied_check_samples": [
            {"timestamp_token": "10:00Z", "source_observation": "failed"},
            {"timestamp_token": "10:01Z", "source_observation": "passed", "sample_kind": "retry"},
        ],
        "later_samples_supplied": False,
        "dependency_map_supplied": False,
        "stated_agent_authority": "advisory",
    },
    "a20": {
        "units_sold": 100,
        "unit_price_usd": 20,
        "unit_variable_cost_usd": 12,
        "fixed_costs_known": False,
        "market_demand_data_supplied": False,
    },
    "a21": {
        "fixed_cost": 100,
        "variable_cost_per_unit": 3,
        "volume": 20,
        "revenue_supplied": False,
    },
    "a26": {
        "supplied_candidate_claim": {"success_percent": 100, "marks_ready": True},
        "supplied_underlying_record": {
            "required_checks": 20,
            "pass_count": 19,
            "failure_count": 1,
        },
        "signed_attestation_exists": False,
    },
    "a28": {
        "supplied_risks": [
            {"identifier": "A", "likelihood": 2, "impact": 5},
            {"identifier": "B", "likelihood": 4, "impact": 2},
        ],
        "supplied_scoring_rule": "score is product",
        "supplied_scale": {"kind": "ordinal estimate", "lower_bound": 1, "upper_bound": 5},
        "controls_supplied": False,
        "calibrated_frequencies_supplied": False,
    },
    "a29": {
        "source_revision": "abc123",
        "source_tests_pass": True,
        "historical_deployment_revision": "def456",
        "current_runtime_receipt_present": False,
        "current_runtime_identity_supplied": False,
        "independent_promotion_approval_supplied": False,
    },
}


def normal_role_raw_input_facts(agent_id: str, original_context: str) -> dict:
    """Return source-bound inputs, preserving the original context exactly.

    This is not parsing arbitrary production text. These reviewed renderings
    apply only to the exact existing canonical normal-case source contexts.
    Unknown roles or changed text fail rather than silently using stale facts.
    """
    if agent_id not in _RAW_INPUT_FACTS:
        raise ValueError("No reviewed source-fact rendering for this role")
    if type(original_context) is not str or original_context != _SOURCE_CONTEXTS[agent_id]:
        raise ValueError("Original source context differs from the reviewed input facts")
    return {
        "original_source_context": original_context,
        "raw_source_facts": deepcopy(_RAW_INPUT_FACTS[agent_id]),
    }


def normal_role_raw_input_context(agent_id: str, original_context: str) -> str:
    """Offer one data-only rendering without any model output or acceptance.

    Original source text remains present verbatim as a JSON string value. This
    is proposed future task input, not a mutation of the active run's context.
    """
    return json.dumps(
        normal_role_raw_input_facts(agent_id, original_context),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def reviewed_input_role_ids() -> tuple[str, ...]:
    """Return source-specific coverage, not an agent readiness claim."""
    return tuple(_RAW_INPUT_FACTS)
