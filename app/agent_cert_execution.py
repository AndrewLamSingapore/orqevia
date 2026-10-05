"""Bounded live case observation without grading or certification authority.

The caller injects authenticated dispatch and job-read functions from the
existing runtime. Raw model output stays within this process and is never
returned by this observer. Case-specific oracles may reject an output, but
cannot sign evidence or grant L1-L7 status.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime

from .agent_cert_numeric import review_priority_json
from .agent_cert_rates import review_rate_json
from .agent_cert_weighted import review_weighted_json
from .agent_cert_boundary import review_zero_boundary_json
from .agent_cert_a17_boundary import review_a17_boundary_json
from .agent_cert_data_quality import review_data_quality_json
from .agent_cert_portfolio import review_portfolio_json
from .agent_cert_cost import review_cost_json
from .agent_cert_risk import review_risk_json
from .agent_cert_cases import challenge
from .agent_registry import agent_record, responsibility_owner


_PROVIDER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_TERMINAL = frozenset({"completed", "failed", "cancelled", "budget_blocked"})
_A01_SOURCE = {
    "capacity_days": 3, "alpha_days": 3, "alpha_total_points": 8,
    "beta_days": 2, "beta_total_points": 6,
}
_A12_SOURCE = {"week1_failures": 10, "week1_requests": 100,
               "week2_failures": 15, "week2_requests": 300}
_A04_SOURCE = {"reliability_weight": 2, "speed_weight": 1,
               "a_reliability": 4, "a_speed": 1,
               "b_reliability": 2, "b_speed": 5}
_A14_SOURCE = [{"id": 1, "amount": 5}, {"id": 1, "amount": 5},
               {"id": 2, "amount": -3}]
_A05_SOURCE = {"available_slots": 1, "p_slots": 1, "q_slots": 1,
               "p_expected_value": 8, "q_expected_value": 5}
_A21_SOURCE = {"fixed_cost": 100, "variable_cost_per_unit": 3, "volume": 20}
_A28_SOURCE = {"a_likelihood": 2, "a_impact": 5,
               "b_likelihood": 4, "b_impact": 2}


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def observe_cert_case(spec: dict, *, dispatch: Callable[[dict], dict],
                      get_job: Callable[[str], dict], timeout_seconds: float = 60,
                      monotonic: Callable[[], float] = time.monotonic,
                      pause: Callable[[float], None] = time.sleep) -> dict:
    """Observe one prepared case through the existing authenticated queue.

    Execution evidence and a local numeric verdict are deliberately distinct
    from authenticated independent review and a signed certification record.
    """
    if not isinstance(spec, dict) or spec.get("certification") != "UNVERIFIED":
        raise ValueError("prepared unverified challenge required")
    agent = spec.get("agent_id")
    capability = spec.get("capability_id")
    request = spec.get("request")
    if (not isinstance(agent, str) or not isinstance(capability, str)
            or not isinstance(request, dict) or request.get("capability") != capability
            or responsibility_owner(capability) != agent
            or capability not in agent_record(agent)["capability_requirements"]
            or request.get("data_classification") != "LOCAL_ONLY"
            or request.get("max_cost_usd") != 0
            or request.get("priority") != "low"
            or not isinstance(request.get("objective"), str)
            or not isinstance(request.get("context"), str)):
        raise ValueError("case violates bounded registered route")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 120:
        raise ValueError("timeout must be bounded to 120 seconds")
    base = {"agent_id": agent, "capability_id": capability, "case": spec.get("case"),
            "certification": "UNVERIFIED"}
    started = monotonic()
    try:
        reply = dispatch(request)
        job = reply.get("job") if isinstance(reply, dict) else None
        if (not isinstance(job, dict) or reply.get("capability") != capability
                or job.get("agent") != agent):
            return {**base, "state": "REJECTED", "reason": "dispatch_identity_mismatch"}
        job_id = job.get("id")
        try:
            valid_job_id = isinstance(job_id, str) and str(uuid.UUID(job_id)) == job_id
        except ValueError:
            valid_job_id = False
        if not valid_job_id:
            return {**base, "state": "REJECTED", "reason": "job_id_missing"}
        while monotonic() - started < timeout_seconds:
            row = get_job(job_id)
            if (not isinstance(row, dict) or row.get("id") != job_id
                    or row.get("agent") != agent):
                return {**base, "job_id": job_id, "state": "REJECTED",
                        "reason": "job_identity_mismatch"}
            status = row.get("status")
            if status == "completed":
                result = row.get("result")
                began = _time(row.get("started_at"))
                ended = _time(row.get("completed_at"))
                provider = row.get("provider")
                if (not isinstance(result, str) or not result.strip() or len(result) > 200_000
                        or began is None or ended is None or began > ended
                        or not isinstance(provider, str) or not _PROVIDER.fullmatch(provider)
                        or type(row.get("attempts")) is not int or row["attempts"] < 1
                        or row.get("error")):
                    return {**base, "job_id": job_id, "state": "REJECTED",
                            "reason": "worker_evidence_missing"}
                review = "UNREVIEWED"
                review_errors: tuple[str, ...] = ()
                if "exact_numeric_oracle" in spec.get("independent_review", ()):
                    if agent != "a01" or capability != "responsibility.a01" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "numeric_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a01",
                                            capability_id="responsibility.a01")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "numeric_oracle_source_mismatch"}
                    valid, review_errors = review_priority_json(_A01_SOURCE, result)
                    review = "NUMERIC_CHECK_PASS" if valid else "NUMERIC_CHECK_FAIL"
                if "exact_rate_oracle" in spec.get("independent_review", ()):
                    if agent != "a12" or capability != "responsibility.a12" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "rate_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a12",
                                            capability_id="responsibility.a12")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "rate_oracle_source_mismatch"}
                    valid, review_errors = review_rate_json(_A12_SOURCE, result)
                    review = "RATE_CHECK_PASS" if valid else "RATE_CHECK_FAIL"
                if "exact_weighted_oracle" in spec.get("independent_review", ()):
                    if agent != "a04" or capability != "responsibility.a04" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "weighted_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a04",
                                            capability_id="responsibility.a04")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "weighted_oracle_source_mismatch"}
                    valid, review_errors = review_weighted_json(_A04_SOURCE, result)
                    review = "WEIGHTED_CHECK_PASS" if valid else "WEIGHTED_CHECK_FAIL"
                if "exact_zero_boundary_oracle" in spec.get("independent_review", ()):
                    if agent != "a18" or capability != "responsibility.a18" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "boundary_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a18",
                                            capability_id="responsibility.a18")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "boundary_oracle_source_mismatch"}
                    valid, review_errors = review_zero_boundary_json(result)
                    review = "BOUNDARY_CHECK_PASS" if valid else "BOUNDARY_CHECK_FAIL"
                if "exact_a17_boundary_oracle" in spec.get("independent_review", ()):
                    if agent != "a17" or capability != "responsibility.a17" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "a17_boundary_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a17",
                                            capability_id="responsibility.a17")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "a17_boundary_oracle_source_mismatch"}
                    valid, review_errors = review_a17_boundary_json(result)
                    review = "A17_BOUNDARY_CHECK_PASS" if valid else "A17_BOUNDARY_CHECK_FAIL"
                if "exact_data_quality_oracle" in spec.get("independent_review", ()):
                    if agent != "a14" or capability != "responsibility.a14" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "data_quality_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a14",
                                            capability_id="responsibility.a14")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "data_quality_oracle_source_mismatch"}
                    valid, review_errors = review_data_quality_json(_A14_SOURCE, result)
                    review = "DATA_QUALITY_CHECK_PASS" if valid else "DATA_QUALITY_CHECK_FAIL"
                if "exact_portfolio_oracle" in spec.get("independent_review", ()):
                    if agent != "a05" or capability != "responsibility.a05" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "portfolio_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a05",
                                            capability_id="responsibility.a05")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "portfolio_oracle_source_mismatch"}
                    valid, review_errors = review_portfolio_json(_A05_SOURCE, result)
                    review = "PORTFOLIO_CHECK_PASS" if valid else "PORTFOLIO_CHECK_FAIL"
                if "exact_cost_oracle" in spec.get("independent_review", ()):
                    if agent != "a21" or capability != "responsibility.a21" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "cost_oracle_scope_mismatch"}
                    if spec != challenge("role:normal", agent_id="a21",
                                         capability_id="responsibility.a21"):
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "cost_oracle_source_mismatch"}
                    valid, review_errors = review_cost_json(_A21_SOURCE, result)
                    review = "COST_CHECK_PASS" if valid else "COST_CHECK_FAIL"
                if "exact_risk_oracle" in spec.get("independent_review", ()):
                    if agent != "a28" or capability != "responsibility.a28" or spec.get("case") != "role:normal":
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "risk_oracle_scope_mismatch"}
                    if request != challenge("role:normal", agent_id="a28",
                                            capability_id="responsibility.a28")["request"]:
                        return {**base, "job_id": job_id, "state": "REJECTED",
                                "reason": "risk_oracle_source_mismatch"}
                    valid, review_errors = review_risk_json(_A28_SOURCE, result)
                    review = "RISK_CHECK_PASS" if valid else "RISK_CHECK_FAIL"
                return {**base, "job_id": job_id, "state": "EXECUTED",
                        "provider": provider, "attempts": row["attempts"],
                        "started_at": began.isoformat(), "completed_at": ended.isoformat(),
                        "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
                        "case_review": review, "review_errors": review_errors}
            if status in _TERMINAL:
                return {**base, "job_id": job_id, "state": "FAILED",
                        "reason": "terminal_job_failure"}
            if status not in {"queued", "running", "approval_required"}:
                return {**base, "job_id": job_id, "state": "REJECTED",
                        "reason": "unknown_job_state"}
            pause(min(0.25, max(0.0, timeout_seconds - (monotonic() - started))))
        return {**base, "job_id": job_id, "state": "INCOMPLETE",
                "reason": "bounded_timeout"}
    except Exception:
        # Dependency exceptions may embed bearer credentials or model text.
        return {**base, "state": "INCOMPLETE", "reason": "dependency_failed"}
