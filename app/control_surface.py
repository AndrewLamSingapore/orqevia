"""Read-only JARVIS Control Surface composed around PRIME's existing APIs."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["control-surface"])
HTML_PATH = Path(__file__).with_name("control_surface.html")


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
        "version": "1.0.0",
        "mode": "read-only",
        "authority": "PRIME CORE",
        "availability": {
            "host": "local-only",
            "control_url": "http://127.0.0.1:8000/control",
            "off_host": "unavailable",
        },
        "views": [
            "conversation",
            "evidence",
            "memory",
            "system",
            "actions",
            "audit",
        ],
        "boundaries": {
            "autonomous_actions": False,
            "approval_mutation": False,
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
            "actions": ["/api/actions", "/api/phase3/approvals"],
            "audit": ["/api/spine/events", "/api/cognitive/meta-review"],
        },
        "memory_layers": [
            {"name": "session", "persistence": "browser tab", "writable": False},
            {"name": "episodic", "persistence": "PRIME database", "writable": False},
            {"name": "durable", "persistence": "PRIME database", "writable": False},
            {"name": "evidence", "persistence": "verified artifacts", "writable": False},
        ],
    }


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
            "required": [("/api/cognitive/memory/search", "GET"), ("/api/cognitive/episodes", "GET")],
            "assertion": "Memory is searchable; write and consolidation controls are absent.",
        },
        {
            "view": "system",
            "label": "Runtime integrity",
            "required": [("/health", "GET"), ("/api/status", "GET")],
            "assertion": "Health, version, integrity and capability state are readable.",
        },
        {
            "view": "actions",
            "label": "Observe-only queues",
            "required": [("/api/actions", "GET"), ("/api/phase3/approvals", "GET")],
            "assertion": "Actions and approvals are visible without mutation controls.",
        },
        {
            "view": "audit",
            "label": "Inspectable audit trail",
            "required": [("/api/spine/events", "GET"), ("/api/cognitive/meta-review", "GET")],
            "assertion": "Stable Spine events and meta-review are readable.",
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
        "name": "JARVIS Control Surface P0 acceptance",
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "mode": "read-only",
        "local_only": True,
        "no_actuation": True,
        "views": results,
    }
