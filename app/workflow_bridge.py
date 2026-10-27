"""Owner-scoped PWA bridge for durable project workflows and agent notebooks."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import pwa_sessions
from . import open_access

router = APIRouter()


def _owner(request: Request, *, mutation: bool) -> str:
    if open_access.enabled() and pwa_sessions.COOKIE not in request.cookies:
        return open_access.OPEN_OWNER_ID
    if pwa_sessions.COOKIE not in request.cookies:
        raise HTTPException(401, "Trusted Owner session required")
    if any(key in request.headers for key in ("authorization", "x-client-id", "x-orqevia-client-id")):
        raise HTTPException(400, "Ambiguous client identity")
    if not pwa_sessions.origin_valid(request, mutation):
        raise HTTPException(403, "Same-origin access required")
    current = pwa_sessions.require_session(request)
    if current.get("role") != "OWNER":
        raise HTTPException(403, "Owner authority required")
    return current["clientId"]


def _admin_key() -> str:
    explicit = os.getenv("ORQEVIA_NOTEBOOK_ADMIN_TOKEN", "").strip()
    if explicit:
        return explicit
    spine = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if len(spine) < 16:
        raise HTTPException(503, "Notebook administration is not configured")
    return hmac.new(spine.encode(), b"orqevia-notebook-admin-v1", hashlib.sha256).hexdigest()


def _backend() -> str:
    base = os.getenv("ORQEVIA_BACKEND_BASE_URL", "http://backend:8000").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.netloc != "backend:8000" or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "Backend service target unavailable")
    return base


async def _forward(request: Request, path: str, *, mutation: bool, notebook: bool = False) -> Response:
    _owner(request, mutation=mutation)
    token = os.getenv("ORQEVIA_SPINE_TOKEN", "").strip()
    if len(token) < 16:
        raise HTTPException(503, "Backend authority unavailable")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": request.headers.get("accept", "application/json"),
    }
    if notebook:
        headers["X-ORQEVIA-Actor"] = "owner"
        headers["X-ORQEVIA-Role"] = "OWNER"
        headers["X-ORQEVIA-Notebook-Admin"] = _admin_key()
    body = b""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        body = await asyncio.wait_for(pwa_sessions.bounded_body(request, 64 * 1024), 3)
        headers["Content-Type"] = request.headers.get("content-type", "application/json")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=3),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            upstream = await client.request(
                request.method,
                _backend() + path,
                params=request.query_params,
                content=body,
                headers=headers,
            )
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise HTTPException(503, "Backend service unavailable") from None
    if len(upstream.content) > 4_000_000:
        raise HTTPException(502, "Backend response exceeds bound")
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Disposition": upstream.headers.get("content-disposition", "inline"),
        },
    )


@router.api_route(
    "/pwa/api/project-workflows{path:path}",
    methods=["GET", "POST"],
)
async def project_workflows(request: Request, path: str):
    if path and (not path.startswith("/") or ".." in path or "\\" in path or ":" in path):
        raise HTTPException(404, "Unavailable route")
    mutation = request.method != "GET"
    return await _forward(request, "/api/project-workflows" + path, mutation=mutation)


@router.api_route('/pwa/api/academy{path:path}', methods=['GET','POST'])
async def academy(request: Request, path: str):
    if not path.startswith('/') or any(part in path for part in ('..','\\',':','%')):
        raise HTTPException(404,'Unavailable route')
    return await _forward(request, '/api/academy'+path, mutation=request.method != 'GET')


@router.api_route(
    "/pwa/api/notebooks{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def notebooks(request: Request, path: str):
    if path and (not path.startswith("/") or ".." in path or "\\" in path):
        raise HTTPException(404, "Unavailable route")
    mutation = request.method != "GET"
    return await _forward(
        request,
        "/api/agent-notebooks" + path,
        mutation=mutation,
        notebook=True,
    )
