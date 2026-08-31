"""Frozen PRIME reasoning-routing policy.

This module decides which reasoning stage may run next.  It does not call a
model, execute an action, or grant authority.  Keeping the decision pure makes
the safety boundary testable and prevents callers from silently skipping the
confidence gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


POLICY_VERSION = "1.0.0"
ROUTING_SEQUENCE = ("deterministic", "local_ai", "confidence_gate", "frontier_ai")
PASSING_LOCAL_CONFIDENCE = frozenset({"strong"})
KNOWN_CONFIDENCE = frozenset({"strong", "partial", "limited"})


@dataclass(frozen=True)
class RoutingDecision:
    policy_version: str
    sequence: tuple[str, ...]
    selected_stage: str
    local_confidence: str
    confidence_gate: str
    frontier_allowed: bool
    frontier_available: bool
    approval_required: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["sequence"] = list(self.sequence)
        return result


class RoutingPolicy:
    """Apply the immutable deterministic → local → gate → frontier order."""

    def decide(
        self,
        *,
        deterministic_satisfied: bool = False,
        local_confidence: str | None = None,
        frontier_allowed: bool = False,
        frontier_available: bool = False,
        consequential: bool = False,
    ) -> RoutingDecision:
        confidence = (local_confidence or "unknown").strip().lower()
        if confidence not in KNOWN_CONFIDENCE:
            confidence = "unknown"

        common = {
            "policy_version": POLICY_VERSION,
            "sequence": ROUTING_SEQUENCE,
            "local_confidence": confidence,
            "frontier_allowed": bool(frontier_allowed),
            "frontier_available": bool(frontier_available),
            "approval_required": bool(consequential),
        }

        if deterministic_satisfied:
            return RoutingDecision(
                selected_stage="deterministic",
                confidence_gate="not_required",
                reason="A verified deterministic result satisfied the request; no model escalation is permitted.",
                **common,
            )

        if confidence == "unknown":
            return RoutingDecision(
                selected_stage="local_ai",
                confidence_gate="pending",
                reason="No deterministic result is available; run the private local model before evaluating confidence.",
                **common,
            )

        if confidence in PASSING_LOCAL_CONFIDENCE:
            return RoutingDecision(
                selected_stage="local_ai",
                confidence_gate="pass",
                reason="The local result passed the frozen confidence gate; frontier escalation is unnecessary.",
                **common,
            )

        if frontier_allowed and frontier_available:
            return RoutingDecision(
                selected_stage="frontier_ai",
                confidence_gate="escalate",
                reason="Local confidence did not pass; the explicitly allowed and available frontier resource may be used.",
                **common,
            )

        unavailable = "unavailable" if frontier_allowed else "not authorized"
        return RoutingDecision(
            selected_stage="confidence_hold",
            confidence_gate="hold",
            reason=f"Local confidence did not pass and frontier escalation is {unavailable}; return gaps instead of a weak final answer.",
            **common,
        )


def policy_manifest() -> dict[str, Any]:
    """Return the public, read-only contract exposed by PRIME."""
    return {
        "version": POLICY_VERSION,
        "sequence": list(ROUTING_SEQUENCE),
        "local_confidence_pass": sorted(PASSING_LOCAL_CONFIDENCE),
        "low_confidence_behavior": "frontier-if-authorized-and-available-otherwise-hold",
        "consequential_behavior": "proposal-requires-explicit-approval",
        "executes_models": False,
        "executes_actions": False,
    }
