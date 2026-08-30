"""Guarded API surface for the Personal JARVIS Stable Spine."""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .spine import StableSpine

router = APIRouter(prefix="/api/spine", tags=["stable-spine"])
spine = StableSpine()


class EvaluateRequest(BaseModel):
    action_envelope: dict[str, Any]
    decision_record: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    approved: bool
    note: str | None = None


def require_token(authorization: str | None) -> None:
    expected = os.getenv("PRIME_SPINE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="PRIME Stable Spine authentication is not configured")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Stable Spine authorization required")


@router.post("/evaluate")
def evaluate(request: EvaluateRequest, authorization: str | None = Header(default=None)):
    require_token(authorization)
    result = spine.evaluate(request.action_envelope, request.decision_record)
    if not result.get("ok"):
        raise HTTPException(status_code=int(result.get("status", 422)), detail=result.get("error", "Invalid action envelope"))
    return result


@router.post("/approvals/{idempotency_key}")
def decide_approval(idempotency_key: str, request: ApprovalRequest, authorization: str | None = Header(default=None)):
    require_token(authorization)
    row = spine.store.decide_approval(idempotency_key, request.approved, request.note)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    event_envelope = {
        "correlation_id": row["correlation_id"],
        "idempotency_key": row["idempotency_key"],
    }
    spine.store.emit(event_envelope, "approval.approved" if request.approved else "approval.rejected", {"status": row["status"], "note": request.note})
    return {"ok": True, "approval": row}


@router.get("/events")
def events(limit: int = 50, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"events": spine.store.list_events(limit)}
