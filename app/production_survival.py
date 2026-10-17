"""Authenticated production adapter for ORQEVIA Offline Survival.

The core state machine stays provider-agnostic.  This adapter exposes only
bounded, local control-plane operations and deliberately avoids executing any
remote side effect.  Reconciliation belongs to explicit, authority-aware
service adapters; merely coming back online must never publish queued work.
"""
from __future__ import annotations

import os
import sqlite3
import hashlib
import time
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Any
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .offline_survival import OfflineSurvival, OperationRejected
from .offline_survival import DependencyClass
from .memory import MemoryStore


class DeferredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=200)
    operation_type: str = Field(min_length=1, max_length=100)
    payload_ref: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)
    authorization_ref: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: float | None = None


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_class: Literal["semantic", "procedural", "protected"]
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


_lock = Lock()
_runtime: OfflineSurvival | None = None
_runtime_path: Path | None = None
_memory: MemoryStore | None = None
_memory_path: Path | None = None


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


def memory() -> MemoryStore:
    """Return governed memory on the same durable external data volume."""
    global _memory, _memory_path
    path = Path(os.getenv("PRIME_MEMORY_DB", str(_db_path().parent / "jarvis-memory.db")))
    with _lock:
        if _memory is None or _memory_path != path:
            _memory = MemoryStore(str(path))
            _memory_path = path
        return _memory


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


def _allowlist() -> set[str]:
    return {item.strip() for item in os.getenv("PRIME_SURVIVAL_FETCH_ALLOWLIST", "").split(",") if item.strip()}


def _fetch_receipt(operation) -> dict[str, Any]:
    """Perform one bounded, allowlisted read and return a machine-verifiable receipt."""
    if operation.operation_type != "web.research" or operation.payload_ref not in _allowlist():
        return {"accepted": False, "detail": "network target is not explicitly allowlisted"}
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.stream("GET", operation.payload_ref, timeout=10.0, follow_redirects=False) as response:
            if not 200 <= response.status_code < 300:
                return {"accepted": False, "detail": f"remote status {response.status_code}"}
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1_048_576:
                    return {"accepted": False, "detail": "remote response exceeded 1 MiB limit"}
                digest.update(chunk)
            return {
                "accepted": True,
                "status_code": response.status_code,
                "content_sha256": digest.hexdigest(),
                "content_bytes": size,
                "etag": response.headers.get("etag", "")[:200],
            }
    except httpx.HTTPError as exc:
        raise RuntimeError(f"network fetch failed: {type(exc).__name__}") from None


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
        for operation, dependency in survival.classification.items():
            if dependency is not DependencyClass.LOCAL_AVAILABLE:
                status["actions"][operation] = "UNVERIFIED"
    status.update({
        "queue_path": str(_db_path()),
        "queue_durable": _db_path().is_file(),
        "pending_count": len(survival.pending()),
        "remote_execution": "ALLOWLISTED_READ_ONLY" if _allowlist() else "DISABLED_UNTIL_AUTHORITY_AWARE_EXECUTOR_CONFIGURED",
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

    @router.post("/reconcile")
    def reconcile():
        survival = runtime()
        network = _probe(os.getenv("PRIME_SURVIVAL_NETWORK_PROBE_URL", "").strip())
        cloud = _probe(os.getenv("PRIME_SURVIVAL_CLOUD_PROBE_URL", "").strip())
        if network is None or cloud is None:
            raise HTTPException(503, "capability probes are not fully configured")
        survival.observe(network=network, provider=cloud)
        expected_authority = os.getenv(
            "PRIME_SURVIVAL_AUTHORITY_REF", "prime-epoch-20260919:owner"
        ).strip()
        results = survival.reconcile(
            executors={"web.research": _fetch_receipt},
            authority_valid=lambda operation: operation.authorization_ref == expected_authority,
            still_relevant=lambda operation: operation.expires_at is None or operation.expires_at > time.time(),
            dependency_available=lambda operation: network is True and operation.dependency is DependencyClass.NETWORK_REQUIRED,
        )
        if survival.state.value == "RECONNECTING" and not survival.pending():
            survival.confirm_online()
        return {
            "state": survival.state.value,
            "results": [
                {**asdict(item), "state": item.state.value}
                for item in results
            ],
            "pending_count": len(survival.pending()),
        }

    @router.post("/memory", status_code=201)
    def put_memory(body: MemoryWrite):
        try:
            return memory().put_governed(
                memory_class=body.memory_class,
                key=body.key,
                value=body.value,
                authority="owner",
                confidence=body.confidence,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/memory/{memory_class}/{key}")
    def get_memory(memory_class: str, key: str):
        found = memory().get(memory_class, key)
        if found is None:
            raise HTTPException(404, "memory record not found")
        return found

    @router.get("/memory")
    def search_memory(q: str = Query(min_length=1, max_length=300)):
        return {"records": memory().search(q)}

    return router
