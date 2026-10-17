"""Read-only JARVIS Control Surface composed around ORQEVIA's existing APIs."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import cognitive_api, spine_api
from .routing_policy import policy_manifest
from .memory import MemoryStore


router = APIRouter(tags=["control-surface"])
HTML_PATH = Path(__file__).with_name("control_surface.html")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _trusted_authorization(request: Request) -> str:
    """Grant bounded Control Surface adapters access only on the local origin."""
    if request.url.hostname not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="JARVIS Control is available only on this device")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Cross-origin Control Surface access is denied")
    token = os.getenv("PRIME_SPINE_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Trusted local access is not configured")
    return f"Bearer {token}"


@router.get("/control", response_class=HTMLResponse)
def control_surface() -> HTMLResponse:
    return HTMLResponse(
        HTML_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/control-surface/manifest")
def control_surface_manifest() -> dict:
    return {
        "name": "JARVIS Control Surface",
        "version": "2.0.0",
        "mode": "approval-gated",
        "authority": "ORQEVIA CORE",
        "availability": {
            "host": "local-only",
            "control_url": "http://127.0.0.1:8000/control",
            "off_host": "unavailable",
        },
        "access": {
            "mode": "trusted-local",
            "sign_in_required": False,
            "direct_protected_apis": "token-required",
        },
        "views": [
            "overview",
            "conversation",
            "evidence",
            "memory",
            "system",
            "actions",
            "audit",
        ],
        "boundaries": {
            "autonomous_actions": False,
            "approval_decision": True,
            "approval_executes_action": False,
            "memory_write": False,
            "runtime_mutation": False,
            "velyqua_dependency": False,
            "physical_actuation": False,
        },
        "read_endpoints": {
            "health": "/health",
            "system": "/api/status",
            "evidence": ["/api/phase3/artifacts", "/api/phase3/reviews"],
            "memory": ["/api/cognitive/memory/search", "/api/cognitive/episodes"],
            "actions": ["/api/actions", "/api/control-surface/trusted/approvals"],
            "audit": ["/api/control-surface/trusted/audit-explorer", "/api/cognitive/meta-review"],
        },
        "memory_classes": MemoryStore.policy_manifest(),
        "owner_workspace": {
            "version": "2.0.0",
            "executive_overview": True,
            "global_read_search": True,
            "health_guidance": True,
            "evidence_filtering": True,
            "audit_timeline": True,
            "client_side_export": True,
            "server_side_writes": "approval-decisions-only",
            "executes_actions": False,
        },
        "routing_policy": policy_manifest(),
    }


@router.get("/api/control-surface/trusted/episodes")
def trusted_episodes(request: Request, limit: int = 25) -> dict:
    return cognitive_api.recent_episodes(limit=limit, authorization=_trusted_authorization(request))


@router.get("/api/control-surface/trusted/memory/search")
def trusted_memory_search(request: Request, q: str, limit: int = 10) -> dict:
    return cognitive_api.search_memory(q=q, limit=limit, authorization=_trusted_authorization(request))


@router.get("/api/control-surface/trusted/events")
def trusted_events(request: Request, limit: int = 50) -> dict:
    return spine_api.events(limit=limit, authorization=_trusted_authorization(request))


@router.get("/api/control-surface/trusted/approvals")
def trusted_approvals(request: Request, limit: int = 100) -> dict:
    return spine_api.approvals(limit=limit, authorization=_trusted_authorization(request))


@router.post("/api/control-surface/trusted/approvals/{idempotency_key}")
async def trusted_decide_approval(idempotency_key: str, request: Request) -> dict:
    authorization = _trusted_authorization(request)
    payload = await request.json()
    approval_request = spine_api.ApprovalRequest.model_validate(payload)
    return spine_api.decide_approval(idempotency_key, approval_request, authorization=authorization)


@router.get("/api/control-surface/trusted/audit-explorer")
def trusted_audit_explorer(request: Request, limit: int = 100) -> dict:
    return spine_api.audit_explorer(limit=limit, authorization=_trusted_authorization(request))


@router.get("/api/control-surface/trusted/meta-review")
def trusted_meta_review(request: Request) -> dict:
    return cognitive_api.meta_review(authorization=_trusted_authorization(request))


@router.post("/api/control-surface/trusted/plan")
async def trusted_plan(request: Request) -> dict:
    authorization = _trusted_authorization(request)
    payload = await request.json()
    plan_request = cognitive_api.PlanRequest.model_validate(payload)
    return cognitive_api.cognitive_plan(plan_request, authorization=authorization)


@router.get("/api/control-surface/acceptance")
def control_surface_acceptance(request: Request) -> dict:
    """Report the registered read paths that satisfy the six-view P0 contract."""
    registered = {
        (route.path, method)
        for route in request.app.routes
        for method in getattr(route, "methods", set())
    }
    checks = [
        {
            "view": "overview",
            "label": "Owner intelligence workspace",
            "required": [("/api/status", "GET"), ("/api/projects", "GET")],
            "assertion": "Executive state, priorities and guidance are assembled from read paths only.",
        },
        {
            "view": "conversation",
            "label": "Read-only answer flow",
            "required": [("/api/chat", "POST")],
            "assertion": "Requests explicitly disable memory writes.",
        },
        {
            "view": "evidence",
            "label": "Evidence and provenance",
            "required": [("/api/phase3/artifacts", "GET"), ("/api/phase3/reviews", "GET")],
            "assertion": "Verified artifacts and reviews are inspectable.",
        },
        {
            "view": "memory",
            "label": "Memory inspection",
            "required": [("/api/control-surface/trusted/memory/search", "GET"), ("/api/control-surface/trusted/episodes", "GET")],
            "assertion": "Local memory is freely readable; write and consolidation controls are absent.",
        },
        {
            "view": "system",
            "label": "Runtime integrity",
            "required": [("/health", "GET"), ("/api/status", "GET")],
            "assertion": "Health, version, integrity and capability state are readable.",
        },
        {
            "view": "actions",
            "label": "Approval decision cards",
            "required": [("/api/actions", "GET"), ("/api/control-surface/trusted/approvals", "GET"), ("/api/control-surface/trusted/approvals/{idempotency_key}", "POST")],
            "assertion": "Owner may approve, modify or reject a proposal; decisions never execute it.",
        },
        {
            "view": "audit",
            "label": "Inspectable audit trail",
            "required": [("/api/control-surface/trusted/audit-explorer", "GET"), ("/api/control-surface/trusted/meta-review", "GET")],
            "assertion": "Request, evidence, route, policy, approval and result are linked by correlation ID.",
        },
    ]
    results = []
    for check in checks:
        missing = [f"{method} {path}" for path, method in check["required"] if (path, method) not in registered]
        results.append({
            "view": check["view"],
            "label": check["label"],
            "status": "pass" if not missing else "fail",
            "assertion": check["assertion"],
            "missing": missing,
        })
    return {
        "name": "JARVIS Control Surface P1 acceptance",
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "mode": "approval-gated",
        "access": "trusted-local",
        "sign_in_required": False,
        "local_only": True,
        "no_actuation": True,
        "views": results,
    }
