"""Authenticated optional operations board; request data never defines authority."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import pwa_sessions
from .collective_contracts import CollectiveCommand
from .collective_intelligence import CollectiveError, CollectivePrincipal

PROTOCOL = "orqevia.collective.v1"
OWNER_OPERATIONS = {
    "evidence.record",
    "claim.contribute",
    "claim.correct",
    "knowledge.link",
    "challenge.open",
    "challenge.transition",
    "challenge.resolve",
    "challenge.reopen",
    "gap.detect",
    "gap.transition",
    "gap.plan",
    "gap.reopen",
    "puzzle.create",
    "puzzle.reopen",
    "lesson.record",
}


def _principal(request: Request) -> CollectivePrincipal:
    # This new surface always authenticates, including on a legacy open-access
    # runtime. A lookup entry or a legacy mode flag cannot expand its authority.
    expected = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    configured = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    supplied = request.headers.getlist("authorization")
    if len(expected) < 16 or not configured:
        raise HTTPException(503, "Collective service authority unavailable")
    if len(supplied) != 1 or not hmac.compare_digest(supplied[0], "Bearer " + expected):
        raise HTTPException(401, "Service authentication required")
    owner = hashlib.sha256(configured.encode()).hexdigest()
    values = request.headers.getlist("x-orqevia-owner")
    if len(values) != 1 or not hmac.compare_digest(values[0], owner):
        raise HTTPException(403, "Bound owner scope required")
    actor_values = request.headers.getlist("x-orqevia-actor")
    actor = actor_values[0] if len(actor_values) == 1 else ""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", actor):
        raise HTTPException(403, "Authenticated actor required")
    tenant = os.getenv("ORQEVIA_TENANT_ID", "personal")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", tenant):
        raise HTTPException(503, "Tenant scope unavailable")
    if os.getenv("ORQEVIA_COLLECTIVE_ENABLED") != "1":
        raise HTTPException(503, "Collective operations are not activated in this environment")
    return CollectivePrincipal(tenant, owner, actor, roles=frozenset({"OWNER"}))


def _response(request: Request, data):
    correlation = request.headers.get("x-request-id", "")
    if not re.fullmatch(r"[a-f0-9-]{36}", correlation):
        correlation = str(uuid.uuid4())
    return JSONResponse(
        {
            "protocol": PROTOCOL,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation,
            "data": data,
            "grants_execution_authority": False,
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Request-ID": correlation,
            "X-Content-Type-Options": "nosniff",
        },
    )


def _failure(error: Exception):
    if isinstance(error, CollectiveError):
        status = {"denied": 403, "not_found": 404, "conflict": 409, "rate_limited": 429}.get(error.code, 422)
        # No untrusted submitted text or backend exception detail is reflected.
        raise HTTPException(status, "Collective operation rejected: " + error.code) from None
    if isinstance(error, (OSError, sqlite3.Error, RuntimeError)):
        raise HTTPException(503, "Collective registry unavailable; execution permissions are unchanged") from None
    raise error


async def _body(request: Request, model):
    try:
        raw = await asyncio.wait_for(pwa_sessions.bounded_body(request, 48000), 3)
        return model.model_validate_json(raw)
    except (ValidationError, ValueError, UnicodeError):
        raise HTTPException(422, "Invalid collective contract") from None
    except TimeoutError:
        raise HTTPException(408, "Collective request timed out") from None


@asynccontextmanager
async def collective_lifespan(app):
    from .collective_runtime import reconcile_loop

    task = asyncio.create_task(reconcile_loop()) if os.getenv("ORQEVIA_COLLECTIVE_ENABLED") == "1" else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


router = APIRouter(prefix="/api/collective/v1", tags=["collective-operations"], lifespan=collective_lifespan)


@router.get("/status")
def status(request: Request):
    principal = _principal(request)
    from .collective_runtime import board_status

    try:
        return _response(request, board_status(principal))
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


@router.get("/lookup")
def lookup(
    request: Request,
    kind: str = Query(min_length=1, max_length=48),
    id: str | None = Query(default=None, max_length=160),
    state: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    principal = _principal(request)
    from .collective_runtime import get_store

    try:
        return _response(
            request, get_store().query(principal, kind, id, {"state": state, "limit": limit, "offset": offset})
        )
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


@router.get("/audit")
def audit(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    principal = _principal(request)
    from .collective_runtime import get_store

    try:
        return _response(request, get_store().audit(principal, limit=limit))
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


@router.post("/commands")
async def command(request: Request):
    principal = _principal(request)
    body = await _body(request, CollectiveCommand)
    if body.operation not in OWNER_OPERATIONS:
        raise HTTPException(403, "Trusted adapter or independent verifier required")
    from .collective_runtime import get_store

    try:
        data = await asyncio.to_thread(
            get_store().command, principal, body.operation, body.payload, body.idempotency_key
        )
        return _response(request, data)
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/reconcile")
async def reconcile(request: Request):
    principal = _principal(request)
    await _body(request, EmptyRequest)
    from .collective_runtime import reconcile_once

    try:
        return _response(request, await asyncio.to_thread(reconcile_once, principal))
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


@router.post("/jobs/{job_id}/publish")
async def publish(job_id: str, request: Request):
    principal = _principal(request)
    await _body(request, EmptyRequest)
    if not re.fullmatch(r"[a-f0-9-]{36}", job_id):
        raise HTTPException(422, "Invalid execution identifier")
    from .collective_runtime import publish_job

    try:
        return _response(request, await asyncio.to_thread(publish_job, job_id, principal))
    except KeyError:
        raise HTTPException(404, "Execution unavailable") from None
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: str = Field(pattern=r"^a[0-9]{2}$")
    target_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.post("/investigations", status_code=202)
async def investigation(request: Request):
    principal = _principal(request)
    body = await _body(request, InvestigationRequest)
    from .collective_runtime import start_investigation

    try:
        return _response(request, await asyncio.to_thread(start_investigation, principal, **body.model_dump()))
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gap_id: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)


@router.post("/repairs/notebook-index")
async def repair_notebook_index(request: Request):
    principal = _principal(request)
    body = await _body(request, RepairRequest)
    from .collective_runtime import repair_notebook_index

    try:
        return _response(request, await asyncio.to_thread(repair_notebook_index, principal, **body.model_dump()))
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)


class MLPInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rows: list[dict[str, float]] = Field(min_length=1, max_length=32)
    trace_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.get("/fabrics/mlp")
def mlp_status(request: Request):
    _principal(request)
    from .fabric_adapters import mlp_observation

    try:
        return _response(request, mlp_observation())
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(503, "Reviewed MLP reference unavailable") from None


@router.post("/fabrics/mlp/infer")
async def mlp_inference(request: Request):
    principal = _principal(request)
    body = await _body(request, MLPInferenceRequest)
    from .fabric_adapters import mlp_infer
    from .collective_runtime import _execution, get_store
    from .collective_intelligence import digest

    try:
        result = await asyncio.to_thread(mlp_infer, body.rows, body.trace_id)
        evidence = _execution(get_store(),adapter="owner_mlp_reference",scope={"model_id":result["model_id"]},
            execution_id="mlp:"+body.trace_id,source="authenticated-owner-reference-inference",
            content={"model_id":result["model_id"],"artifact_hash":result["artifact_hash"],
                     "input_sha256":digest(body.rows),"output_sha256":digest(result["output"]),
                     "owner_actor":principal.actor_id,"qualification_scope":"SYNTHETIC_QUADRATIC_REFERENCE_ONLY"})
        return _response(request,{**result,"evidence_id":evidence["id"]})
    except ValueError:
        raise HTTPException(422, "Invalid bounded reference input or artifact") from None
    except (CollectiveError, OSError, sqlite3.Error, RuntimeError) as error:
        _failure(error)
