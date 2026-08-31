"""Guarded cognitive endpoints for Personal JARVIS."""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .cognitive_orchestrator import CognitiveOrchestrator
from .compute_ledger import ComputeLedger
from .memory import MemoryStore
from .meta_review import MetaReviewer

router = APIRouter(prefix="/api/cognitive", tags=["cognitive"])
memory = MemoryStore()
ledger = ComputeLedger()
reviewer = MetaReviewer()
orchestrator = CognitiveOrchestrator(memory=memory)


class EpisodeRequest(BaseModel):
    event_type: str
    content: dict[str, Any]
    source: str
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    durable_kind: str | None = None
    durable_key: str | None = None


class PlanRequest(BaseModel):
    intent: str
    department: str = ""
    context: str = ""
    allow_frontier: bool = False


class ExecuteRequest(PlanRequest):
    deep: bool = False


def require_token(authorization: str | None) -> None:
    expected = os.getenv("PRIME_SPINE_TOKEN", "").strip()
    supplied = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not expected:
        raise HTTPException(status_code=503, detail="Cognitive authentication is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Cognitive authorization required")


@router.post("/episodes")
def record_episode(request: EpisodeRequest, authorization: str | None = Header(default=None)):
    require_token(authorization)
    try:
        return {"ok": True, "episode": memory.record_episode(**request.model_dump())}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/consolidate")
def consolidate(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"ok": True, **memory.consolidate()}


@router.get("/episodes")
def recent_episodes(limit: int = 50, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"episodes": memory.recent_episodes(limit)}


@router.get("/memory/search")
def search_memory(q: str, limit: int = 10, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"query": q, "results": orchestrator.hybrid_memory.search(q, limit=limit)}


@router.post("/plan")
def cognitive_plan(request: PlanRequest, authorization: str | None = Header(default=None)):
    require_token(authorization)
    try:
        return {"ok": True, "plan": orchestrator.plan(**request.model_dump()).as_dict()}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/reason")
def cognitive_reason(request: ExecuteRequest, authorization: str | None = Header(default=None)):
    require_token(authorization)
    try:
        return {"ok": True, **orchestrator.execute(**request.model_dump())}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/models")
def model_manifest(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return orchestrator.gateway.manifest()


@router.get("/compute")
def compute_events(limit: int = 100, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"events": ledger.recent(limit)}


@router.get("/meta-review")
def meta_review(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return reviewer.review()
