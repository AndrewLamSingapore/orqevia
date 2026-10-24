"""Public-safe ORQEVIA agent runtime metadata.

Disabled by default. When ORQEVIA is deliberately exposed through a trusted public
relay, ORQEVIA_PUBLIC_AGENT_TRACE=1 enables a strictly sanitized read-only trace.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Response

from .runtime import authority
from .agent_registry import registered_agent_ids

router = APIRouter(prefix="/api/public/jarvis", tags=["public-agent-runtime"])
router_orqevia = APIRouter(prefix="/api/public/orqevia", tags=["public-agent-runtime"])


def _enabled() -> bool:
    return os.getenv("ORQEVIA_PUBLIC_AGENT_TRACE", "0").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/agent-trace")
@router_orqevia.get("/agent-trace")
def public_agent_trace(response: Response, limit: int = 100):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if not _enabled():
        return {
            "ok": True,
            "state": "disabled",
            "summary": {
                "registered_agents": len(registered_agent_ids(include_orchestrator=False)),
                "active_agents": 0,
                "executions_today": 0,
                "denied_handoffs_today": 0,
                "average_latency_ms": None,
                "active_window_seconds": 300,
            },
            "events": [],
            "boundary": "Public runtime trace is disabled. No synthetic events are substituted.",
        }
    return authority.public_snapshot(max(1, min(int(limit), 100)))

PUBLIC_MODELS = [
    {"id": "gemma3:12b", "role": "deep", "provider": "ollama-local", "note": "governed local deep model"},
    {"id": "gemma3:4b", "role": "fast", "provider": "ollama-local", "note": "governed local fast model"},
    {"id": "gemma3:1b", "role": "fast", "provider": "ollama-local", "note": "governed local fast model"},
    {"id": "embeddinggemma:300m-qat-q4_0", "role": "embedding", "provider": "ollama-local", "note": "governed local embedding model"},
    {"id": "mlp-fabric", "role": "reference", "provider": "local", "note": "synthetic numerical reference only"},
]

@router.get("/models")
@router_orqevia.get("/models")
def public_models(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "models": PUBLIC_MODELS,
            "boundary": "Public-safe model metadata only; no credentials, endpoints or topology."}
