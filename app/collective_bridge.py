"""Bound-owner, same-origin gateway to the optional collective operations board."""

import asyncio
import hashlib
import hmac
import os
import re
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import pwa_sessions
from .observability import trace_headers
from .sovereign_plane_bridge import _admit, _identity
from .workflow_bridge import _backend

router = APIRouter(prefix="/interface/v1/collective", tags=["collective-operations"])
PROTOCOL = "orqevia.collective.v1"
PATHS = {
    "status": {"GET"},
    "lookup": {"GET"},
    "audit": {"GET"},
    "commands": {"POST"},
    "reconcile": {"POST"},
    "investigations": {"POST"},
    "repairs/notebook-index": {"POST"},
    "fabrics/mlp": {"GET"},
    "fabrics/mlp/infer": {"POST"},
    "fabrics/events": {"GET"},
    "fabrics/registry": {"GET"},
    "intelligence/pif/status": {"GET"},
    "intelligence/pif/fit": {"POST"},
    "intelligence/pif/forecast": {"POST"},
    "intelligence/pif/transition": {"POST"},
    "intelligence/pif/risk": {"POST"},
    "intelligence/pif/scenario": {"POST"},
    "intelligence/pif/model": {"GET"},
    "intelligence/pif/hidden-state": {"POST"},
    "intelligence/pif/intervention": {"POST"},
    "intelligence/pif/rollback": {"POST"},
    "intelligence/mel/status": {"GET"},
    "intelligence/mel/inventory": {"GET"},
    "intelligence/mel/experiments": {"GET", "POST"},
    "intelligence/mel/recommendation": {"GET"},
}


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def collective_bridge(path: str, request: Request):
    methods = PATHS.get(path)
    if methods is None and re.fullmatch(r"intelligence/pif/evidence/[a-f0-9-]{36}", path):
        methods = {"GET"}
    if methods is None and re.fullmatch(r"jobs/[a-f0-9-]{36}/publish", path):
        methods = {"POST"}
    if methods is None and re.fullmatch(r"fabrics/f(?:0[1-9]|[12][0-9]|3[0-6])/execute", path):
        methods = {"POST"}
    if methods is None and re.fullmatch(r"fabrics/executions/[a-f0-9-]{36}", path):
        methods = {"GET"}
    if methods is None:
        raise HTTPException(404, "Unavailable operations-board route")
    if request.method not in methods:
        raise HTTPException(405, "Unavailable method")
    actor, owner = _identity(request)
    configured = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    if not configured or not hmac.compare_digest(owner, hashlib.sha256(configured.encode()).hexdigest()):
        raise HTTPException(403, "Bound owner identity required")
    _admit("collective:" + actor)
    token = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if len(token) < 16:
        raise HTTPException(503, "Service authority unavailable")
    correlation = str(uuid.uuid4())
    try:
        limit = 900000 if re.fullmatch(r"fabrics/f\d{2}/execute", path) else 64000
        body = await asyncio.wait_for(pwa_sessions.bounded_body(request, limit), 3) if request.method == "POST" else b""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(65 if limit == 900000 else 35, connect=2), trust_env=False, follow_redirects=False
        ) as client:
            async with client.stream(
                request.method,
                _backend() + "/api/collective/v1/" + path,
                params=request.query_params,
                content=body,
                headers=trace_headers(
                    {
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-ORQEVIA-Actor": actor,
                        "X-ORQEVIA-Owner": owner,
                        "X-Request-ID": correlation,
                    }
                ),
            ) as upstream:
                if not 200 <= upstream.status_code < 300:
                    return JSONResponse(
                        {
                            "protocol": PROTOCOL,
                            "error": {
                                "code": "COLLECTIVE_REQUEST_FAILED",
                                "message": "The operations board could not complete this request.",
                                "retryable": False,
                            },
                            "correlation_id": correlation,
                        },
                        status_code=upstream.status_code,
                        headers={"Cache-Control": "private, no-store", "X-Request-ID": correlation},
                    )
                chunks, size = [], 0
                async for chunk in upstream.aiter_bytes():
                    size += len(chunk)
                    if size > (2_000_000 if path.startswith("fabrics/") else 512000):
                        raise ValueError("Bounded response exceeded")
                    chunks.append(chunk)
                return Response(
                    b"".join(chunks),
                    status_code=upstream.status_code,
                    media_type="application/json",
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-Content-Type-Options": "nosniff",
                        "X-Request-ID": correlation,
                    },
                )
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        raise HTTPException(503, "Collective registry unavailable; execution permissions are unchanged") from None
