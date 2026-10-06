"""Read-only capability view over the owned registry and certification evidence.

Declared eligibility is intent, not execution. Only independently verified,
current case evidence from AgentCertificationRegistry enters ``proven``. This
projection stores nothing, grants no authority, and never infers runtime health.
"""
from __future__ import annotations

from datetime import datetime

from .agent_certification import AgentCertificationRegistry
from .agent_registry import load_agent_registry


def project_capability_observatory(
    certification: AgentCertificationRegistry, *, now: datetime | None = None
) -> list[dict]:
    """Return one source-bound capability row for each permanent agent."""
    agent_registry = load_agent_registry()  # Validates the exact 21-agent contract.
    agents = agent_registry["agents"]
    evidence_rows = certification.matrix(now=now)
    by_id = {row["agent_id"]: row for row in evidence_rows}
    if len(by_id) != len(agents) or set(by_id) != {agent["id"] for agent in agents}:
        raise ValueError("certification projection does not match permanent agents")

    result = []
    for agent in agents:
        observed = by_id[agent["id"]]
        capabilities = {row["capability_id"]: row for row in observed["capabilities"]}
        owned = set(agent["capability_requirements"])
        if set(capabilities) != owned:
            raise ValueError("certification projection does not match capability ownership")
        result.append({
            "agent_id": agent["id"],
            "role": agent["role"],
            "provenance": {
                "projection_version": "1.0",
                "source_revision": certification.source_revision,
                "registry_version": agent_registry["registry_version"],
                "intended_domain": "config/agent_registry.json",
                "proven_domain": f"agent-certification/{agent['id']}/certification.json",
            },
            "intended": {
                "capabilities": sorted(owned),
                "tool_eligibility": list(agent["tool_eligibility"]),
                "model_tier_eligibility": list(agent["model_tier_eligibility"]),
            },
            "proven": {
                "cases": {capability: row["valid_cases"] for capability, row in capabilities.items()},
                "complete_dimensions": {capability: row["current_dimensions"]
                                        for capability, row in capabilities.items()},
                "level": observed["level"],
                "trust_state": observed["trust_state"],
            },
            "missing_cases": {capability: row["missing_cases"]
                              for capability, row in capabilities.items()},
            "runtime_activation": "UNVERIFIED",
            "quality": "UNKNOWN",
            "autonomy": "UNKNOWN",
            "latency_ms": "UNKNOWN",
            "cost_usd": "UNKNOWN",
        })
    return result
