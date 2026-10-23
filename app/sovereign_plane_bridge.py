"""Bound-owner OSIP adapter; fixed target, bounded bodies and no ambient authority."""

import asyncio
from collections import OrderedDict, deque
import hashlib
import hmac
import os
import re
import threading
import time
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, JSONResponse

from .local_knowledge_bridge import identity
from .observability import trace_headers
from .workflow_bridge import _backend
from .interface_contract import authorize
from . import pwa_sessions

router = APIRouter(prefix="/interface/v1/osip", tags=["osip-interface"])
PATHS = {"status": {"GET"}, "plans": {"POST"}, "approvals": {"GET"}}
_admissions = OrderedDict()
_admission_lock = threading.Lock()


def _admit(actor: str):
    now = time.monotonic()
    with _admission_lock:
        history = _admissions.pop(actor, deque())
        while history and now - history[0] >= 60:
            history.popleft()
        _admissions[actor] = history
        if len(history) >= 60:
            raise HTTPException(429, "Intelligence-plane request limit reached")
        history.append(now)
        while len(_admissions) > 1024:
            _admissions.popitem(last=False)


def _identity(request: Request):
    if pwa_sessions.COOKIE not in request.cookies:
        return identity(request)
    # PWASessionMiddleware rejects caller identity headers, then injects its
    # verified internal identity for /interface/v1. Validate that exact identity.
    actor, _ = authorize(request, "authority.owner.verify")
    current = pwa_sessions.require_session(request)
    account = current.get("ownerAccountId")
    if (
        actor != current["clientId"]
        or current.get("role") != "OWNER"
        or not isinstance(account, str)
        or not account
        or not pwa_sessions.origin_valid(request, request.method == "POST")
    ):
        raise HTTPException(403, "Bound owner identity required")
    return actor, hashlib.sha256(account.encode()).hexdigest()


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def bridge(path: str, request: Request):
    methods = PATHS.get(path)
    if methods is None and re.fullmatch(r"approvals/[A-Za-z0-9_.:-]{1,100}", path):
        methods = {"POST"}
    if methods is None:
        raise HTTPException(404, "Unavailable intelligence-plane route")
    if request.method not in methods:
        raise HTTPException(405, "Unavailable method")
    actor, owner = _identity(request)
    # The existing private-knowledge boundary enforces current OWNER role,
    # bound account, same-origin mutation and unambiguous session identity.
    configured = os.getenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "").strip()
    if not configured or not hmac.compare_digest(owner, hashlib.sha256(configured.encode()).hexdigest()):
        raise HTTPException(403, "Bound owner identity required")
    _admit(actor)
    token = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if len(token) < 16:
        raise HTTPException(503, "Service authority unavailable")
    correlation = str(uuid.uuid4())
    try:
        body = await asyncio.wait_for(pwa_sessions.bounded_body(request, 24000), 3) if request.method == "POST" else b""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=2), trust_env=False, follow_redirects=False
        ) as client:
            async with client.stream(
                request.method,
                _backend() + "/api/osip/v1/" + path,
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
            ) as response:
                if not 200 <= response.status_code < 300:
                    return JSONResponse(
                        {
                            "protocol": "orqevia.osip.v1",
                            "error": {
                                "code": "OSIP_REQUEST_FAILED",
                                "message": "The service could not complete this request.",
                                "retryable": False,
                            },
                            "correlation_id": correlation,
                        },
                        status_code=response.status_code,
                        headers={"Cache-Control": "private, no-store", "X-Request-ID": correlation},
                    )
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 512000:
                        raise ValueError()
                    chunks.append(chunk)
                return Response(
                    b"".join(chunks),
                    status_code=response.status_code,
                    media_type="application/json",
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-Content-Type-Options": "nosniff",
                        "X-Request-ID": correlation,
                    },
                )
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        raise HTTPException(503, "Intelligence plane unavailable; no execution was performed") from None
