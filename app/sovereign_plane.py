"""OSIP: bounded coordination over the existing registry, queue and Stable Spine.

Planning grants no authority. Execution stays on the owned objective contract.
Observation opens existing stores read-only and never initializes absent stores.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .agent_registry import load_agent_registry
from .client_auth import authenticate_owner
from .compute_catalog import load_catalog, task_tier
from .interface_telemetry import agent_activity, model_runtime_readiness
from .objective_api import select_capabilities

router = APIRouter(prefix="/api/osip/v1", tags=["sovereign-intelligence-plane"])
PROTOCOL = "orqevia.osip.v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanRequest(Contract):
    objective: str = Field(min_length=1, max_length=20000)
    task_class: Literal["auto", "planning", "research", "coding", "architecture", "complex_reasoning"] = "auto"


class PlanStep(Contract):
    id: str
    purpose: str
    depends_on: list[str]
    capabilities: list[str]


class Plan(Contract):
    protocol: Literal["orqevia.osip.v1"] = PROTOCOL
    correlation_id: str
    created_at: str
    reasoning_tier: str
    steps: list[PlanStep]
    execution_performed: Literal[False] = False
    grants_execution_authority: Literal[False] = False
    execution_contract: Literal["/interface/v1/objectives"] = "/interface/v1/objectives"
    disclosure: str


class ApprovalDecision(Contract):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=1000)


def _authorize(authorization: str | None):
    authenticate_owner(authorization)


def _correlation(request: Request) -> str:
    value = request.headers.get("x-request-id", "")
    return value if re.fullmatch(r"[a-f0-9-]{36}", value) else str(uuid.uuid4())


def _read_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError()
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def _store_observation(path: Path, table: str) -> dict:
    # Table names are fixed at the call sites, never supplied by a request.
    try:
        db = _read_db(path)
        try:
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        finally:
            db.close()
        return {"status": "OBSERVED", "read_only_probe": True}
    except (OSError, sqlite3.Error):
        return {"status": "UNAVAILABLE", "read_only_probe": True}


def _spine_path() -> Path:
    return Path(os.getenv("ORQEVIA_SPINE_DB", "/tmp/orqevia-spine.db"))


def snapshot() -> dict:
    registry = load_agent_registry()
    activity = agent_activity()
    readiness = model_runtime_readiness(timeout=2)
    model_probe = {key: value for key, value in readiness.items() if key != "endpoint"}
    try:
        catalog = load_catalog()
        models = [
            {
                key: entry.get(key)
                for key in ("id", "model", "tier", "location", "enabled", "capabilities", "qualification_status")
            }
            for entry in catalog
        ]
        catalog_status = "OBSERVED" if models else "UNAVAILABLE"
    except (OSError, ValueError, KeyError, TypeError):
        models, catalog_status = [], "UNAVAILABLE"
    agents = []
    for agent in registry["agents"]:
        record = activity.get(agent["id"]) if activity is not None else None
        agents.append(
            {
                "agent_id": agent["id"],
                "name": agent["name"],
                "registration": "REGISTERED",
                "last_observed_state": record.get("status") if record else None,
                "observed_at": record.get("observed_at") if record else None,
                "availability": "OBSERVATION_RECORDED" if record else "NOT_OBSERVED",
                "capabilities": agent["capability_requirements"],
            }
        )
    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
    memory = {
        "task_state": _store_observation(root / "objectives.db", "objectives"),
        "session_continuity": _store_observation(root / "pwa-sessions.db", "sessions"),
        "semantic_retrieval": {
            "status": "SEPARATE_SERVICE",
            "contract": "/api/orqevia/knowledge/health",
            "disclosure": "Query the existing owner-scoped knowledge service; task persistence is not semantic memory.",
        },
    }
    return {
        "protocol": PROTOCOL,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "models": {"status": catalog_status, "entries": models, "runtime": model_probe},
        "agents": agents,
        "memory": memory,
        "governance": {
            "approval_store": _store_observation(_spine_path(), "approvals"),
            "execution_contract": "/interface/v1/objectives",
            "approval_grants_execution": False,
        },
        "verification": {
            "certification": "NOT_ESTABLISHED_BY_THIS_OBSERVATION",
            "provider_configuration_is_live_inference": False,
            "registered_agent_is_active_agent": False,
        },
        "boundaries": {
            "gods_eye_read_only": True,
            "new_executor": False,
            "model_weight_updates": False,
            "cross_product_dependency": False,
        },
    }


@router.get("/status")
def status(request: Request, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return {**snapshot(), "correlation_id": _correlation(request)}


@router.post("/plans", response_model=Plan)
def plan(body: PlanRequest, request: Request, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if not body.objective.strip():
        raise HTTPException(422, "An objective is required")
    capabilities = select_capabilities(body.objective)
    registered = {cap for agent in load_agent_registry()["agents"] for cap in agent["capability_requirements"]}
    if not capabilities or any(cap not in registered for cap in capabilities):
        raise HTTPException(503, "Canonical capability route unavailable")
    return Plan(
        correlation_id=_correlation(request),
        created_at=datetime.now(timezone.utc).isoformat(),
        reasoning_tier=task_tier(body.objective, body.task_class).name,
        steps=[
            PlanStep(
                id="scope",
                purpose="Validate the objective against the current server-issued ownership, locality and resource policy.",
                depends_on=[],
                capabilities=[],
            ),
            PlanStep(
                id="reason",
                purpose="Dispatch through the existing canonical capability route and governed compute queue.",
                depends_on=["scope"],
                capabilities=capabilities,
            ),
            PlanStep(
                id="verify",
                purpose="Inspect the persisted task, actual provider attempts and original evidence before accepting the result.",
                depends_on=["reason"],
                capabilities=[],
            ),
        ],
        disclosure="Deterministic preparation, not model reasoning or execution. Use this objective in the existing authenticated task flow. Server policy selects providers and enforces authority and cost limits.",
    )


def approval_rows(limit: int = 50) -> list[dict]:
    try:
        db = _read_db(_spine_path())
        try:
            rows = db.execute(
                "SELECT idempotency_key,correlation_id,action_type,status,created_at,decided_at FROM approvals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            db.close()
        return [dict(row) for row in rows]
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Existing approval service is unavailable") from None


@router.get("/approvals")
def approvals(
    request: Request, limit: int = Query(default=50, ge=1, le=50), authorization: str | None = Header(default=None)
):
    _authorize(authorization)
    return {
        "protocol": PROTOCOL,
        "correlation_id": _correlation(request),
        "approvals": approval_rows(limit),
        "scope": "BOUND_OWNER_STABLE_SPINE",
        "execution_performed": False,
    }


@router.post("/approvals/{key}")
def decide(key: str, body: ApprovalDecision, request: Request, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", key) or not body.note.strip():
        raise HTTPException(422, "A valid approval reference and decision note are required")
    # Verify the existing store before constructing the original writer. Observation
    # never creates a new approval authority or an empty replacement database.
    approval_rows(1)
    from .spine import SpineStore

    store = SpineStore(str(_spine_path()))
    row = store.decide_approval(key, body.decision, body.note)
    if row is None:
        raise HTTPException(404, "Approval not found")
    if row.get("decision_recorded"):
        store.emit(
            {"correlation_id": row["correlation_id"], "idempotency_key": key},
            "approval." + body.decision,
            {"status": row["status"], "note": body.note, "source": PROTOCOL},
        )
    return {
        "protocol": PROTOCOL,
        "correlation_id": row["correlation_id"],
        "idempotency_key": key,
        "status": row["status"],
        "decision_recorded": bool(row.get("decision_recorded")),
        "execution_performed": False,
        "disclosure": "Decision recorded in the existing Stable Spine. The originating executor must re-evaluate its original action; this interface never executes it.",
    }
