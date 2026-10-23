"""OSIP: bounded coordination over the existing registry, queue and Stable Spine.

Planning grants no authority. Execution stays on the owned objective contract.
Observation opens existing stores read-only and never initializes absent stores.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field

from .agent_registry import load_agent_registry
from .client_auth import authenticate_owner
from .compute_catalog import load_catalog, task_tier
from .interface_telemetry import agent_activity, model_runtime_readiness
from .objective_api import select_capabilities
from .settings import PrimeSettings
from . import observation_integrations


@asynccontextmanager
async def optional_observations_lifespan(app):
    task = (
        asyncio.create_task(observation_integrations.poll())
        if os.getenv("ORQEVIA_OBSERVATION_POLLING") == "1"
        else None
    )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


router = APIRouter(
    prefix="/api/osip/v1", tags=["sovereign-intelligence-plane"], lifespan=optional_observations_lifespan
)
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
    envelope_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


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
    settings = PrimeSettings.from_env()
    for role, model in (
        ("fast", settings.fast_model),
        ("deep", settings.deep_model),
        ("evaluator", settings.evaluator_model),
        ("embedding", settings.embedding_model),
    ):
        models.append(
            {
                "id": "local-role-" + role,
                "model": model,
                "location": "local",
                "enabled": True,
                "role": role,
                "tier": "MINI" if role in {"deep", "evaluator"} else "NANO" if role == "fast" else None,
                "qualification_status": "CONFIGURED_ROLE_ONLY",
            }
        )
    catalog_status = "OBSERVED" if models else catalog_status
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


async def observed_integrations():
    result = observation_integrations.snapshot()
    owner = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    token = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    semantic = {"status": "UNAVAILABLE", "formal_proof": False}
    if owner and len(token) >= 16:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(2, connect=1), trust_env=False, follow_redirects=False
            ) as client:
                response = await client.get(
                    "http://host.docker.internal:8150/semantic/health",
                    headers={
                        "Authorization": "Bearer " + token,
                        "X-ORQEVIA-Owner": hashlib.sha256(owner.encode()).hexdigest(),
                    },
                )
                if response.status_code == 200 and len(response.content) <= 12000:
                    value = response.json()
                    if value.get("protocol") == "orqevia.semantic.v1":
                        semantic = {
                            key: value.get(key)
                            for key in (
                                "status",
                                "model",
                                "revision",
                                "model_sha256",
                                "runtime",
                                "scope",
                                "formal_proof",
                                "qualification",
                                "input_persistence",
                                "truth_or_source_authenticity_verified",
                            )
                        }
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            pass
    return {**result, "semantic_entailment": semantic}


@router.get("/observations")
async def observations(request: Request, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return {**(await observed_integrations()), "correlation_id": _correlation(request)}


@router.post("/observations/refresh")
async def refresh_observations(body: Contract, request: Request, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    collected = await observation_integrations.refresh()
    return {
        **(await observed_integrations()),
        "collection_status": collected["status"],
        "correlation_id": _correlation(request),
        "execution_authority_granted": False,
    }


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


def _review_value(value, depth=0):
    if depth > 5:
        return "[Depth omitted; consult originating action]"
    if isinstance(value, dict):
        return {
            str(key)[:100]: "[REDACTED]"
            if re.search(r"secret|password|api.?key|authorization|cookie|credential|private.?key|token", str(key), re.I)
            else _review_value(child, depth + 1)
            for key, child in list(value.items())[:30]
        }
    if isinstance(value, list):
        return [_review_value(child, depth + 1) for child in value[:30]]
    if isinstance(value, str):
        from .agent_notebooks import _redact

        return _redact(value[:1500])[0]
    return value


def _review_complete(value, depth=0):
    if depth > 5:
        return False
    if isinstance(value, dict):
        return len(value) <= 30 and all(len(str(k)) <= 100 and _review_complete(v, depth + 1) for k, v in value.items())
    if isinstance(value, list):
        return len(value) <= 30 and all(_review_complete(v, depth + 1) for v in value)
    return not isinstance(value, str) or len(value) <= 1500


def approval_rows(limit: int = 50, *, key: str | None = None) -> list[dict]:
    try:
        db = _read_db(_spine_path())
        try:
            query = "SELECT idempotency_key,correlation_id,action_type,status,created_at,decided_at,CASE WHEN length(envelope_json)<=48000 THEN envelope_json ELSE NULL END AS envelope_json FROM approvals"
            query += " WHERE idempotency_key=?" if key else ""
            rows = db.execute(query + " ORDER BY created_at DESC LIMIT ?", (key, limit) if key else (limit,)).fetchall()
        finally:
            db.close()
        output = []
        for row in rows:
            item = dict(row)
            raw = item.pop("envelope_json")
            if not isinstance(raw, str):
                continue
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or envelope.get("tenant_id") != "personal":
                continue
            context = envelope.get("context", {})
            if not isinstance(context, dict):
                context = {}
            review_source = {
                "title": context.get("title", item["action_type"]),
                "actor": envelope.get("actor_id"),
                "risk": context.get("risk", "Not supplied"),
                "parameters": envelope.get("parameters", {}),
                "expected_effect": context.get("expected_effect"),
                "reversibility": context.get("reversibility", "Not supplied"),
                "evidence": context.get("evidence", []),
            }
            review = _review_value(review_source)
            reviewable = _review_complete(review_source) and len(json.dumps(review)) <= 6000
            output.append(
                {
                    **item,
                    "review": review
                    if reviewable
                    else {"title": "Action too large for safe review; use its originating interface"},
                    "reviewable": reviewable,
                    "envelope_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
            )
        return output
    except (OSError, sqlite3.Error, ValueError, TypeError):
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
    existing = approval_rows(1, key=key)
    if not existing:
        raise HTTPException(404, "Approval not found in this owner scope")
    if existing[0]["envelope_sha256"] != body.envelope_sha256:
        raise HTTPException(409, "The original action changed; reload and review it again")
    if body.decision == "approve" and not existing[0]["reviewable"]:
        raise HTTPException(409, "Use the originating interface to review this action")
    from .spine import SpineStore

    store = SpineStore(str(_spine_path()))
    row = store.decide_approval(key, body.decision, body.note)
    if row is None:
        raise HTTPException(404, "Approval not found")
    if row.get("decision_recorded"):
        store.emit(
            {"correlation_id": row["correlation_id"], "idempotency_key": key},
            "approval." + body.decision,
            {
                "status": row["status"],
                "note": body.note,
                "source": PROTOCOL,
                "reviewed_envelope_sha256": body.envelope_sha256,
            },
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
