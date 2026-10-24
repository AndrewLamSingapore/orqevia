"""Guarded API surface for the ORQEVIA Stable Spine."""
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
    decision: str
    note: str | None = None
    modifications: dict[str, Any] = Field(default_factory=dict)


def require_token(authorization: str | None) -> None:
    expected = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ORQEVIA Stable Spine authentication is not configured")
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
    try:
        row = spine.store.decide_approval(idempotency_key, request.decision, request.note, request.modifications)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    event_envelope = {
        "correlation_id": row["correlation_id"],
        "idempotency_key": row["idempotency_key"],
    }
    if row.get("decision_recorded"):
        spine.store.emit(event_envelope, f"approval.{request.decision}", {"status": row["status"], "note": request.note, "modifications": request.modifications})
    return {"ok": True, "approval": row}


@router.get("/approvals")
def approvals(limit: int = 100, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"approvals": spine.store.list_approvals(limit)}


@router.get("/audit-explorer")
def audit_explorer(limit: int = 100, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"traces": spine.store.audit_explorer(limit)}


@router.get("/events")
def events(limit: int = 50, authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {"events": spine.store.list_events(limit)}
