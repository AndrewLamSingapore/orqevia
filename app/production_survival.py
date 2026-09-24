"""Authenticated production adapter for PRIME Offline Survival.

The core state machine stays provider-agnostic.  This adapter exposes only
bounded, local control-plane operations and deliberately avoids executing any
remote side effect.  Reconciliation belongs to explicit, authority-aware
service adapters; merely coming back online must never publish queued work.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .offline_survival import OfflineSurvival, OperationRejected


class DeferredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=200)
    operation_type: str = Field(min_length=1, max_length=100)
    payload_ref: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)
    authorization_ref: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: float | None = None


_lock = Lock()
_runtime: OfflineSurvival | None = None
_runtime_path: Path | None = None


def _db_path() -> Path:
    root = Path(os.getenv("PRIME_DATA_DIR", "/data").strip() or "/data")
    return root / "offline-queue.db"


def runtime() -> OfflineSurvival:
    """Return the process singleton, replacing it if the configured data root changes."""
    global _runtime, _runtime_path
    path = _db_path()
    with _lock:
        if _runtime is None or _runtime_path != path:
            _runtime = OfflineSurvival(path)
            _runtime_path = path
        return _runtime


def _probe(url: str) -> bool | None:
    """Probe only an explicitly configured URL; absence means UNKNOWN, never success."""
    if not url:
        return None
    try:
        response = httpx.get(url, timeout=2.0, follow_redirects=False)
        # Reachable is not the same as ready: redirects, authentication failures,
        # rate limits and client errors must not be promoted to AVAILABLE.
        return 200 <= response.status_code < 300
    except (httpx.HTTPError, ValueError):
        return False


def capability_status() -> dict[str, Any]:
    survival = runtime()
    network = _probe(os.getenv("PRIME_SURVIVAL_NETWORK_PROBE_URL", "").strip())
    cloud = _probe(os.getenv("PRIME_SURVIVAL_CLOUD_PROBE_URL", "").strip())
    # The state machine needs booleans. Unknown probes are reported as unknown and
    # must not manufacture ONLINE; retain the last deliberate state instead.
    if network is not None and cloud is not None:
        survival.observe(network=network, provider=cloud)

    ollama = _probe(os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/") + "/api/tags")
    data = _db_path().parent
    memory_path = Path(os.getenv("PRIME_MEMORY_DB", str(data / "jarvis-memory.db")))
    memory_ready = False
    if memory_path.is_file():
        try:
            with sqlite3.connect(f"file:{memory_path}?mode=ro", uri=True, timeout=2) as db:
                db.execute("PRAGMA schema_version").fetchone()
            memory_ready = True
        except sqlite3.Error:
            memory_ready = False
    status = survival.offline_actions(
        local_model_ready=ollama is True,
        memory_ready=memory_ready,
        local_tools_ready=data.is_dir() and os.access(data, os.R_OK | os.W_OK),
    )
    # Preserve UNKNOWN independently of the state-machine's last observation.
    if network is None:
        status["internet"] = "UNKNOWN"
    if cloud is None:
        status["cloud_model"] = "UNKNOWN"
    if network is None or cloud is None:
        status["mode"] = "CAPABILITY_UNVERIFIED"
    status.update({
        "queue_path": str(_db_path()),
        "queue_durable": _db_path().is_file(),
        "pending_count": len(survival.pending()),
        "remote_execution": "DISABLED_UNTIL_AUTHORITY_AWARE_EXECUTOR_CONFIGURED",
    })
    return status


def _operation(operation) -> dict[str, Any]:
    value = asdict(operation)
    value["dependency"] = operation.dependency.value
    value["state"] = operation.state.value
    return value


def build_router(authorize) -> APIRouter:
    router = APIRouter(prefix="/control/api/survival", dependencies=[Depends(authorize)])

    @router.get("/status")
    def status():
        return capability_status()

    @router.get("/queue")
    def queue():
        return {"operations": [_operation(item) for item in runtime().all()]}

    @router.post("/queue", status_code=202)
    def defer(body: DeferredRequest):
        try:
            item = runtime().enqueue(**body.model_dump())
        except OperationRejected as exc:
            raise HTTPException(422, str(exc)) from None
        return _operation(item)

    return router
