"""Bounded, non-certifying observation of a registered agent's queue execution.

The caller supplies authenticated dispatch/job readers. This module never owns
credentials, opens a network connection, writes evidence, or grants authority.
An observed queue completion is useful raw evidence, not an L1-L7 certificate:
an independent verifier still has to authenticate and evaluate the case.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .agent_registry import agent_record, load_agent_registry, responsibility_owner


TERMINAL = frozenset({"completed", "failed", "cancelled", "budget_blocked"})
SAFE_PROVIDER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
    except ValueError:
        return None
    return parsed


def baseline_plan() -> list[dict[str, str]]:
    """One bounded identity-path probe per specialist, not 21 certifications."""
    return [
        {"agent_id": agent["id"], "capability_id": agent["capability_requirements"][0],
         "case": "baseline:identity"}
        for agent in load_agent_registry()["agents"]
    ]


def observe_baseline_execution(
    agent_id: str,
    capability_id: str,
    *,
    dispatch: Callable[[dict[str, Any]], dict[str, Any]],
    get_job: Callable[[str], dict[str, Any]],
    timeout_seconds: float = 30,
    monotonic: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Submit and observe one synthetic, local-only, zero-cloud-cost request.

    The injected functions must authenticate independently. Do not persist their
    raw responses: queue rows can contain prompts, output text, and errors.
    A claimed completion without matching worker timestamps/provider/attempts is
    not an execution observation. No result from this function is certifying.
    """
    owner = responsibility_owner(capability_id)
    if owner != agent_id or capability_id not in agent_record(agent_id)["capability_requirements"]:
        raise ValueError("agent does not own capability")
    if not 0 < timeout_seconds <= 120:
        raise ValueError("probe timeout must be bounded to 120 seconds")

    challenge = secrets.token_hex(12)
    request = {
        "capability": capability_id,
        "objective": f"For a capability-path canary, reply with this exact marker only: {challenge}",
        "context": "",
        "classification": "R0",
        "data_classification": "LOCAL_ONLY",
        "task_class": "classification",
        "minimum_tier": "NANO",
        "priority": "low",
        "max_cost_usd": 0,
    }
    started = monotonic()
    base = {"agent_id": agent_id, "capability_id": capability_id,
            "case": "baseline:identity", "certification": "UNVERIFIED",
            "challenge_sha256": hashlib.sha256(challenge.encode()).hexdigest()}
    try:
        reply = dispatch(request)
        if not isinstance(reply, dict) or reply.get("capability") != capability_id:
            return {**base, "state": "REJECTED", "reason": "dispatch_contract_mismatch"}
        queued = reply.get("job")
        if not isinstance(queued, dict) or queued.get("agent") != agent_id:
            return {**base, "state": "REJECTED", "reason": "wrong_agent_or_no_job"}
        job_id = queued.get("id")
        try:
            valid_id = isinstance(job_id, str) and str(uuid.UUID(job_id)) == job_id
        except (ValueError, AttributeError):
            valid_id = False
        if not valid_id:
            return {**base, "state": "REJECTED", "reason": "job_id_missing"}
        while monotonic() - started < timeout_seconds:
            row = get_job(job_id)
            if not isinstance(row, dict) or row.get("id") != job_id or row.get("agent") != agent_id:
                return {**base, "state": "REJECTED", "reason": "job_identity_mismatch"}
            if not isinstance(row.get("prompt"), str) or challenge not in row["prompt"]:
                return {**base, "state": "REJECTED", "reason": "job_prompt_mismatch"}
            status = row.get("status")
            if status == "completed":
                result = row.get("result")
                provider = row.get("provider")
                started_at = _timestamp(row.get("started_at"))
                completed_at = _timestamp(row.get("completed_at"))
                executed = (isinstance(result, str) and bool(result.strip())
                            and started_at is not None and completed_at is not None
                            and started_at <= completed_at
                            and isinstance(provider, str) and SAFE_PROVIDER.fullmatch(provider)
                            and isinstance(row.get("attempts"), int) and row["attempts"] >= 1
                            and not row.get("error"))
                return {**base, "job_id": job_id, "state": "EXECUTED" if executed else "REJECTED",
                        "reason": "worker_observed" if executed else "worker_evidence_missing",
                        "challenge_returned": bool(executed and result.strip() == challenge),
                        "result_sha256": hashlib.sha256(result.encode()).hexdigest() if executed else None,
                        "provider": provider if executed else None,
                        "started_at": started_at.isoformat() if executed else None,
                        "completed_at": completed_at.isoformat() if executed else None}
            if status in TERMINAL:
                return {**base, "job_id": job_id, "state": "FAILED", "reason": "terminal_job_failure"}
            if status not in {"queued", "running", "approval_required"}:
                return {**base, "job_id": job_id, "state": "REJECTED", "reason": "unknown_job_state"}
            pause(min(0.25, max(0.0, timeout_seconds - (monotonic() - started))))
        return {**base, "job_id": job_id, "state": "INCOMPLETE", "reason": "bounded_timeout"}
    except Exception:
        # Do not echo exception strings; transport failures can include tokens,
        # URLs, prompts, or model output.
        return {**base, "state": "INCOMPLETE", "reason": "probe_dependency_failed"}
