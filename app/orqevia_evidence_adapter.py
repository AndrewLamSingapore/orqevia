"""Thin candidate-only adapter from canonical ORQEVIA task metadata to v0.1 envelopes."""
from __future__ import annotations

from typing import Any

from app.evidence_product import SCHEMA


def adapt_task(task: dict[str, Any], *, claims: list[dict[str, Any]], observations: list[dict[str, Any]],
               effects: list[dict[str, Any]], artifacts: list[dict[str, Any]], verification: dict[str, Any]) -> dict[str, Any]:
    """Map server-owned fields; never infer missing authority or metadata from model content."""
    required=("task_id","objective","actor_id","actor_type","authority_scope","authority_source","created_at","status")
    missing=[key for key in required if not task.get(key)]
    if missing: raise ValueError("missing canonical ORQEVIA fields: "+",".join(missing))
    return {"schema_version":SCHEMA,"action_id":task["task_id"],"objective":task["objective"],
            "actor":{"type":task["actor_type"],"id":task["actor_id"]},
            "authority":{"scope":task["authority_scope"],"source":task["authority_source"]},
            "started_at":task["created_at"],"completed_at":task.get("completed_at"),
            "status":task["status"],"inputs":task.get("inputs",[]),"claims":claims,
            "observations":observations,"effects":effects,"artifacts":artifacts,
            "verification":verification,"provenance":{"record_owner":"ORQEVIA_TASK_SYSTEM",
            "runtime_identity":task.get("runtime_identity"),"model_content_authoritative":False},
            "relations":task.get("relations",[])}
