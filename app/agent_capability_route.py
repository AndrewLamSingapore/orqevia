"""Certification-aware eligibility for a canonical agent capability owner.

This pure policy consumes independently projected evidence and live readiness
signals. It does not grant authority, activate a worker, or enqueue work.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_registry import responsibility_owner


INVALID_TRUST = frozenset({"REVALIDATION-REQUIRED", "SUSPENDED", "FAILED", "L7-DEGRADED"})


@dataclass(frozen=True)
class AgentCapabilityRoute:
    state: str
    agent_id: str
    capability_id: str
    reason: str
    trust_level: str
    requires_independent_verification: bool
    grants_execution_authority: bool = False


def select_agent_capability_route(
    capability_id: str,
    certification: dict | None,
    *,
    authority_allowed: bool,
    runtime_healthy: bool,
    tools_available: bool,
    model_available: bool,
    capacity_available: bool = True,
    allow_demonstration: bool = False,
) -> AgentCapabilityRoute:
    """Select the unique owner only when independent safety signals permit it.

    An L0-L5 demonstration is never a certified route. Its caller must opt in
    and independently verify the result; stale, suspended, or failed evidence
    cannot be rescued by that opt-in. No route grants execution permission.
    """
    owner = responsibility_owner(capability_id)
    level = "L0"

    def result(state: str, reason: str, verify: bool = False) -> AgentCapabilityRoute:
        return AgentCapabilityRoute(state, owner, capability_id, reason, level, verify)

    if not authority_allowed:
        return result("HOLD", "Independent authority decision denied")
    if not runtime_healthy:
        return result("HOLD", "Owner runtime is not verified healthy")
    if not tools_available:
        return result("HOLD", "Required authorized tools are unavailable")
    if not model_available:
        return result("HOLD", "Required governed model is unavailable")
    if not isinstance(certification, dict):
        return result("HOLD", "Certification projection is unavailable")
    if certification.get("agent_id") != owner or certification.get("capability_id") != capability_id:
        return result("HOLD", "Certification does not bind the canonical capability owner")
    level = certification.get("level", "L0")
    trust = certification.get("trust_state")
    if level not in {f"L{n}" for n in range(8)} or trust in INVALID_TRUST:
        return result("HOLD", "Certification is invalid or requires revalidation")
    current = ((level == "L6" and trust == "CERTIFIED-HEALTHY") or
               (level == "L7" and trust == "L7-CURRENT"))
    if current and certification.get("health") == "HEALTHY":
        if not capacity_available:
            return result("QUEUED", "Certified owner has no available execution capacity")
        return result("READY", "Current healthy certification and live dependencies verified")
    if (level not in {"L0", "L1", "L2", "L3", "L4", "L5"} or
            not allow_demonstration or trust not in {"UNPROVEN", "CERTIFIED-DEGRADED"}):
        return result("HOLD", "Current trusted certification is not established")
    if not capacity_available:
        return result("QUEUED", "Demonstration owner has no available execution capacity", True)
    return result("DEMONSTRATION_ONLY", "Certification work requires independent result verification", True)
