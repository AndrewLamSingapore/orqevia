"""Discover existing capabilities without another executor or Docker socket.

Source installation, runtime observation, and functional qualification are
separate states. The catalog never treats a source file as a live health check.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import orqevia_bridge

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "capability_depot.json"
router = APIRouter()


def discover_capabilities(task_class: str | None = None) -> list[dict]:
    """Return a public-safe, fixed manifest; never import manifest-supplied code."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema") != "orqevia.capability-depot-manifest.v1":
        raise ValueError("Unsupported capability catalog")
    items = data["capabilities"]
    ids = set()
    output = []
    for item in items:
        if item["id"] in ids:
            raise ValueError("Duplicate capability identity")
        ids.add(item["id"])
        if task_class is not None and task_class not in item["task_classes"]:
            continue
        source = (ROOT / item["source"]).resolve()
        installed = source.is_relative_to(ROOT) and source.is_file()
        output.append(
            {
                **item,
                "status": "SOURCE_INSTALLED" if installed else "SOURCE_UNAVAILABLE",
                "available": None,
                "runtime_status": "NOT_PROBED",
                "evidence": {"source": item["source"], "scope": "SOURCE_NOT_RUNTIME_QUALIFICATION"},
            }
        )
    return output


def _queue_state(root: Path) -> dict:
    path = root / "compute-queue.db"
    if not path.is_file():
        return {"status": "UNAVAILABLE", "counts": {}}
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            counts = dict(db.execute("SELECT status,count(*) FROM compute_jobs GROUP BY status"))
            row = db.execute("SELECT paused,generation FROM compute_background_admission WHERE id=1").fetchone()
        return {
            "status": "OBSERVED",
            "counts": counts,
            "admission": {"paused": bool(row[0]), "generation": row[1]} if row else {"status": "UNKNOWN"},
        }
    except sqlite3.Error:
        return {"status": "UNAVAILABLE", "counts": {}}


def runtime_resources(root: Path) -> dict:
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                memory[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    disk = None
    try:
        if root.is_dir():
            value = shutil.disk_usage(root)
            disk = {"total_bytes": value.total, "free_bytes": value.free, "scope": "data filesystem"}
    except OSError:
        pass
    return {
        "cpu_logical_count": os.cpu_count(),
        "memory_bytes": memory or None,
        "disk": disk,
        "gpu": {"status": "NOT_PROBED"},
        "queue": _queue_state(root),
        "scope": "CURRENT_PROCESS_HOST_NOT_PHYSICAL_PC_ATTESTATION",
    }


def depot_snapshot() -> dict:
    from .agent_registry import registered_agent_ids

    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
    return {
        "schema": "orqevia.capability-depot.v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "capabilities": discover_capabilities(),
        "agents": {"registered_count": len(registered_agent_ids(include_orchestrator=False))},
        "runtime": runtime_resources(root),
        "wallet": {
            "status": "NOT_FOUND",
            "audited_on": "2026-11-05",
            "spend_enabled": False,
            "signing_available": False,
            "balance": None,
            "scope": "No live wallet runtime found in the dated audit; paid compute usage is not a funded wallet.",
        },
        "service_management": {
            "executor": "EXISTING_HOST_DEPLOYMENT",
            "web_install_enabled": False,
            "docker_socket_exposed": False,
            "reason": "Install, update and rollback use the existing versioned host release pathway.",
        },
    }


@router.get("/api/orqevia/depot")
def depot(request: Request):
    orqevia_bridge.access(request, mutation=True)
    return JSONResponse(depot_snapshot(), headers={"Cache-Control": "private, no-store"})


@router.get("/api/orqevia/evolution/experiments")
def experiments(request: Request):
    orqevia_bridge.access(request, mutation=True)
    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "operations" / "evolution"
    records = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
        if path.stat().st_size > 2_000_000:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("schema") != "orqevia.evolution-experiment.v1":
                continue
            records.append(
                {
                    key: value.get(key)
                    for key in ("run_id", "experiment_id", "observed_at_utc", "selection", "evidence_scope")
                }
            )
        except (OSError, ValueError):
            continue
    return JSONResponse({"experiments": records, "read_only": True}, headers={"Cache-Control": "private, no-store"})


@router.post("/api/orqevia/evolution/experiment")
async def experiment(request: Request):
    orqevia_bridge.access(request, mutation=True)
    raw = await orqevia_bridge.pwa_sessions.bounded_body(request, 1024)
    try:
        body = json.loads(raw) if raw.strip() else {}
    except (ValueError, UnicodeError):
        raise HTTPException(422, "An empty experiment request is required") from None
    if type(body) is not dict or body:
        raise HTTPException(422, "The experiment accepts no code, criteria, paths or permission changes")
    from .evolution_experiments import run_experiment

    # Fixed, bounded local computation only; no caller code, shell or criteria.
    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "operations" / "evolution"
    result = run_experiment(root)
    result.pop("artifact_path", None)
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
