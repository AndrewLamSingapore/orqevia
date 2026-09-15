"""Public-safe JARVIS agent runtime metadata.

Disabled by default. When PRIME is deliberately exposed through a trusted public
relay, PRIME_PUBLIC_AGENT_TRACE=1 enables a strictly sanitized read-only trace.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Response

from .runtime import authority
from .agent_registry import registered_agent_ids

router = APIRouter(prefix="/api/public/jarvis", tags=["public-agent-runtime"])


def _enabled() -> bool:
    return os.getenv("PRIME_PUBLIC_AGENT_TRACE", "0").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/agent-trace")
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
