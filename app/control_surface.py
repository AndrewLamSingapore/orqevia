"""Read-only JARVIS Control Surface composed around PRIME's existing APIs."""
from pathlib import Path

from fastapi import APIRouter
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
