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
        "version": "0.1.0",
        "mode": "read-only",
        "authority": "PRIME CORE",
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
            "velyqua_dependency": False,
            "physical_actuation": False,
        },
    }
