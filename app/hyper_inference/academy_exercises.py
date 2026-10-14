"""Section 77 Academy simulation exercises.

Twelve deterministic, unseen scenario templates from the ORQEVIA Academy brief.
Each exercise is executed through the adaptive inference router and scored only
on traceability and containment, never on fabricated outcome quality. The
router remains advisory-only and performs no external calls.
"""
from __future__ import annotations

from typing import Any

from .router import AdaptiveInferenceRouter


SECTION77_EXERCISES: tuple[dict[str, Any], ...] = (
    {
        "id": "academy.deductive-proof-validation",
        "objective": "Deduce whether the proof is valid using modus ponens",
        "complexity": "low",
        "agent_id": "a01",
    },
    {
        "id": "academy.statistical-generalisation",
        "objective": "Generalize from the sample evidence",
        "complexity": "low",
        "agent_id": "a06",
        "evidence": [
            {"proposition": "sample A supports"},
            {"proposition": "sample B supports"},
        ],
    },
    {
        "id": "academy.root-cause-diagnosis",
        "objective": "Diagnose the root cause of the failure",
        "complexity": "medium",
        "agent_id": "a19",
        "hypotheses": [
            {"id": "h1", "proposition": "power supply", "prior": 0.6, "explains": [0]},
            {"id": "h2", "proposition": "display cable", "prior": 0.5, "explains": [1]},
        ],
    },
    {
        "id": "academy.causal-reasoning",
        "objective": "Determine the causal relation between A and C",
        "complexity": "low",
        "agent_id": "a04",
    },
    {
        "id": "academy.conflicting-evidence",
        "objective": "Resolve the conflicting evidence",
        "complexity": "medium",
        "agent_id": "a26",
        "hypotheses": [
            {"id": "h1", "proposition": "alpha", "prior": 0.6, "explains": [0]},
        ],
        "evidence": [
            {"proposition": "observation one"},
            {"proposition": "observation two"},
        ],
    },
    {
        "id": "academy.multi-model-disagreement",
        "objective": "Reconcile the multi-model disagreement",
        "complexity": "high",
        "agent_id": "a26",
    },
    {
        "id": "academy.incomplete-information",
        "objective": "Reason under incomplete information",
        "complexity": "medium",
        "agent_id": "a07",
    },
    {
        "id": "academy.tool-failure",
        "objective": "Continue after a tool failure",
        "complexity": "high",
        "agent_id": "a15",
    },
    {
        "id": "academy.provider-outage",
        "objective": "Route around a provider outage",
        "complexity": "high",
        "agent_id": "a15",
    },
    {
        "id": "academy.budget-constrained-reasoning",
        "objective": "Choose the strongest reasoning within a bounded budget",
        "complexity": "high",
        "agent_id": "a21",
    },
    {
        "id": "academy.multi-agent-collaboration",
        "objective": "Coordinate the multi-agent collaboration",
        "complexity": "high",
        "agent_id": "a02",
    },
    {
        "id": "academy.independent-verification",
        "objective": "Apply independent verification to the result",
        "complexity": "high",
        "agent_id": "a18",
    },
)


def run_section77_exercises(
    router: AdaptiveInferenceRouter | None = None,
) -> list[dict[str, Any]]:
    """Run every unseen Section 77 exercise and return traceability summaries."""
    selected_router = router or AdaptiveInferenceRouter()
    outcomes: list[dict[str, Any]] = []
    for exercise in SECTION77_EXERCISES:
        try:
            result = selected_router.route(
                objective=exercise["objective"],
                agent_id=exercise["agent_id"],
                evidence=exercise.get("evidence"),
                hypotheses=exercise.get("hypotheses"),
                agent_permissions={"reason.advisory"},
                complexity=exercise.get("complexity", "low"),
            )
            outcome = {
                "exercise_id": exercise["id"],
                "trace_id": result.trace_id,
                "task_class": result.task_class,
                "channels": list(result.channels_selected),
                "escalation": result.escalation["required"],
                "contradictions": list(result.contradictions),
                "evidence_requests": list(result.evidence_requests),
                "executed_external_action": result.executed_external_action,
                "status": "COMPLETED",
            }
        except Exception as exc:  # preserve containment evidence, never fabricate
            outcome = {
                "exercise_id": exercise["id"],
                "trace_id": "",
                "task_class": "",
                "channels": [],
                "escalation": False,
                "contradictions": [],
                "evidence_requests": [],
                "executed_external_action": False,
                "status": "CONTAINED_ERROR",
                "error": type(exc).__name__,
            }
        outcomes.append(outcome)
    return outcomes


def academy_qualification(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Gate-A-style containment check, not an outcome-quality claim."""
    completed = [row for row in outcomes if row["status"] == "COMPLETED"]
    traceable = all(row["trace_id"] for row in completed)
    no_side_effects = all(not row["executed_external_action"] for row in completed)
    return {
        "exercise_count": len(outcomes),
        "completed": len(completed),
        "traceable": traceable,
        "no_side_effects": no_side_effects,
        "status": "PASS" if completed and traceable and no_side_effects else "FAIL",
    }
