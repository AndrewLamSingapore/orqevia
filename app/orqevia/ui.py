"""Standalone, read-only ORQEVIA unified interface surface.

This module serves the responsive ORQEVIA interface and an allow-listed,
read-only proxy into PRIME's existing public/read endpoints. It is deliberately
NOT mounted into the production ``app.main`` or ``app.interface_server`` apps.

Run it separately, for example:

    PRIME_BASE_URL=http://127.0.0.1:8000 uvicorn app.orqevia.ui:app --port 8100

Security properties
-------------------
* Only GET requests are forwarded.
* Only an explicit allow-list of read-only paths is forwarded.
* Authorization and cookie headers are never forwarded upstream.
* The surface never writes, executes, or mutates PRIME state.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urljoin

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).with_name("static")
UPSTREAM = os.getenv("PRIME_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = max(0.5, float(os.getenv("ORQEVIA_UPSTREAM_TIMEOUT", "3.0")))

# Only these read-only paths may be proxied. Mutating endpoints are absent on
# purpose: the interface never executes or writes to the sovereign platform.
READ_ONLY_PATHS = {
    "health",
    "api/status",
    "api/agents",
    "api/control-surface/manifest",
}

VIEWS = [
    "home",
    "intelligence",
    "ideas",
    "architecture",
    "build",
    "test",
    "deploy",
    "present",
    "evidence",
    "agents",
    "gods-eye",
    "settings",
]

app = FastAPI(title="ORQEVIA Unified Interface", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/orqevia/manifest")
def manifest() -> dict:
    """Static surface manifest plus explicit authority boundaries."""
    return {
        "name": "ORQEVIA · 奥启维亚",
        "tagline": "Unified Interface",
        "views": VIEWS,
        "upstream": {"base_url": UPSTREAM, "read_only": True},
        "boundaries": {
            "autonomous_actions": False,
            "runtime_mutation": False,
            "physical_actuation": False,
            "production_deploy": False,
            "live_pwa_change": False,
            "public_website_change": False,
            "sensitive_operations_require_human_approval": True,
        },
    }


def _gods_eye_unavailable(reason: str) -> JSONResponse:
    """Fail closed: the read-only surface never invents an observatory projection."""
    return JSONResponse(
        {
            "status": "UNAVAILABLE",
            "reason": reason,
            "source": "ORQEVIA_READ_ONLY_SURFACE",
            "currentness": "UNKNOWN",
            "disclosure": "GOD'S EYE is integrated as a view; live observatory data requires the formal owner-authorized projection.",
        },
        status_code=503,
    )


@app.get("/api/orqevia/gods-eye")
async def gods_eye_snapshot() -> JSONResponse:
    """Read-only GOD'S EYE projection endpoint.

    The formal projection (``app.gods_eye_api``) lives on the separate
    ``feat/prime-gods-eye-semantic-20261007`` branch and requires owner-bearer
    authorization plus the RDF/SHACL/OWL semantic stack. When that stack is not
    present, this endpoint fails closed to UNAVAILABLE rather than fabricating
    observatory data or zero-counts.
    """
    try:
        import app.gods_eye_api  # noqa: F401  (present only when formal stack is wired)
        formal_wired = True
    except Exception:
        formal_wired = False
    if not formal_wired:
        return _gods_eye_unavailable("GODS_EYE_FORMAL_STACK_NOT_WIRED")
    return _gods_eye_unavailable("GODS_EYE_OWNER_BEARER_REQUIRED")


@app.get("/api/orqevia/gods-eye/why")
async def gods_eye_why(agent_id: str) -> JSONResponse:
    return _gods_eye_unavailable("GODS_EYE_SEMANTIC_WHY_UNAVAILABLE")


@app.get("/api/orqevia/gods-eye/dependencies")
async def gods_eye_dependencies(subject: str) -> JSONResponse:
    return _gods_eye_unavailable("GODS_EYE_SEMANTIC_DEPENDENCIES_UNAVAILABLE")


@app.get("/api/orqevia/gods-eye/proof")
async def gods_eye_proof(task_id: str) -> JSONResponse:
    return _gods_eye_unavailable("GODS_EYE_EVIDENCE_PROOF_UNAVAILABLE")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/orqevia/proxy/{path:path}")
async def proxy(path: str) -> JSONResponse:
    """Forward one allow-listed read-only GET request to PRIME."""
    if path not in READ_ONLY_PATHS:
        raise HTTPException(status_code=403, detail="read-only path not allowed")
    url = urljoin(UPSTREAM + "/", path)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            # Deliberately forward no Authorization/Cookie headers.
            response = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"connected": False, "reason": "upstream_unreachable", "detail": type(exc).__name__},
            status_code=502,
        )
    if response.status_code >= 400:
        return JSONResponse(
            {"connected": False, "reason": "upstream_error", "status": response.status_code},
            status_code=502,
        )
    try:
        data = response.json()
    except ValueError:
        return JSONResponse({"connected": False, "reason": "invalid_json"}, status_code=502)
    return JSONResponse({"connected": True, "path": path, "data": data})


# Mounted last so the explicit routes above win.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="orqevia-static")
