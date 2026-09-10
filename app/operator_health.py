"""Read-only runtime evidence and plain-language interpretation.

Health is not authority or production qualification. Probes never create or
repair a ledger, invoke inference, consume a lease, or change a service.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_last_success = None


def authority_configuration():
    """Observe the pilot's existing configuration checks without creating it."""
    token = os.getenv("PRIME_SPINE_TOKEN", "").strip()
    explicit = os.getenv("PRIME_HARNESS_SIGNING_SECRET", "").strip()
    return {
        "configured": bool(token) and (not explicit or len(explicit.encode()) >= 32),
        "pilot_enabled": os.getenv("PRIME_HARNESS_PILOT_ENABLED", "1").strip().lower()
        in {"1", "true", "yes", "on"},
    }


def read_store(path, queries):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=.15)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                return {"ok": False, "error": "integrity_check_failed"}
            values = {key: [dict(r) for r in db.execute(sql)] for key, sql in queries.items()}
            return {"ok": True, **values}
    except (OSError, sqlite3.Error):
        return {"ok": False, "error": "store_unavailable"}


def interpret(evidence):
    """Unknown authority evidence never produces a healthy summary."""
    authority = evidence.get("authority", {})
    worker = evidence.get("worker", {})
    stores = evidence.get("stores", {})
    counts = evidence.get("work", {})
    safe = (authority.get("configured") is True and authority.get("pilot_enabled") is True
            and worker.get("configured_ceiling") == 1
            and all(stores.get(k, {}).get("ok") is True for k in ("spine", "harness", "queue"))
            and not evidence.get("uncertain_executions", 0))
    items = []
    if not safe:
        state = "SAFE_STOP"
        items.append({"what_happened": "PRIME cannot verify that new work is safe to run.",
                      "handled": "No safety check has been bypassed by this status view.",
                      "affected": "New work needs to remain paused until the safety checks pass.",
                      "action": "Ask for a safety review. Do not repeatedly restart or resubmit work."})
    elif worker.get("attention_required"):
        state = "ACTION_REQUIRED"
        items.append({"what_happened": "Work processing could not recover after repeated attempts.",
                      "handled": "PRIME stopped retrying the failed worker.",
                      "affected": "Some work may be waiting.",
                      "action": "Ask for a recovery review; completed work must not be repeated."})
    elif stores.get("compute", {}).get("ok") is not True:
        state = "DEGRADED"
        items.append({"what_happened": "PRIME could not verify its compute records.",
                      "handled": "Unknown usage is not reported as zero.",
                      "affected": "Exact computation and reasoning require the compute ledger.",
                      "action": "Read-only status remains available while the record store is checked."})
    elif worker.get("running_workers", 0) != 1 or worker.get("stopping"):
        state = "DEGRADED"
        items.append({"what_happened": "Work processing is not currently running.",
                      "handled": "Status and safe read-only checks remain available.",
                      "affected": "New reasoning work will wait.",
                      "action": "No new work should be submitted until processing is ready."})
    elif evidence.get("local_ready") is not True:
        state = "DEGRADED"
        items.append({"what_happened": "Local reasoning is unavailable or still preparing.",
                      "handled": "Exact computations and read-only status do not need a model.",
                      "affected": "Reasoning work cannot finish yet.",
                      "action": "No authority or cloud access has been expanded."})
    elif counts.get("awaiting_approval", 0):
        state = "ACTION_REQUIRED"
        items.append({"what_happened": "A decision is waiting for you.",
                      "handled": "The work is waiting safely.", "affected": "Only the waiting work is affected.",
                      "action": "Review the request in Actions. Approval does not itself execute it."})
    else:
        state = "HEALTHY"
        items.append({"what_happened": "The checked runtime components are ready.",
                      "handled": "No runtime fault was found in this check.",
                      "affected": "No affected work was identified.", "action": "No action is required for these checks."})
    return {"state": state, "attention": items, "ready_for_local_work": safe and state == "HEALTHY",
            "production_ready": False, "production_status": "Qualification is still pending.",
            "scope": "runtime_checks_only", "authority_granted": False,
            "priority_order": ["Work", "Web3", "VELYQUA"],
            "operating_state": {"exact_computation": "available" if stores.get("compute", {}).get("ok") is True else "not verified", "local_reasoning": "ready" if evidence.get("local_ready") else "unavailable",
                                "cloud": "disabled_by_pilot_policy"},
            "work": counts, "work_available": stores.get("queue", {}).get("ok") is True,
            "recent_completed": evidence.get("recent_completed", []),
            "accounting": evidence.get("accounting", {"available": False})}


def snapshot():
    global _last_success
    from . import compute_queue_api, spine_api
    from .settings import SETTINGS
    data = Path(os.getenv("PRIME_DATA_DIR", "/data"))
    stores = {
        "spine": read_store(spine_api.spine.store.path, {"decisions": "SELECT count(*) AS count FROM audit_trail"}),
        "harness": read_store(os.getenv("PRIME_HARNESS_DB", str(data / "action-harness.db")),
                              {"uncertain": "SELECT count(*) AS count FROM harness_jobs WHERE state='uncertain'"}),
        "queue": read_store(compute_queue_api.queue.db_path,
                            {"counts": "SELECT status,count(*) AS count FROM compute_jobs GROUP BY status",
                             "completed": "SELECT id,completed_at FROM compute_jobs WHERE status='completed' ORDER BY completed_at DESC LIMIT 5"}),
        "compute": read_store(os.getenv("PRIME_COMPUTE_DB", str(data / "compute-ledger.db")),
                              {"usage": "SELECT count(*) AS recorded_events,sum(input_units) AS input_tokens,sum(output_units) AS output_tokens,count(input_units) AS input_samples,count(output_units) AS output_samples,sum(estimated_cost_usd) AS estimated_cost_usd,count(estimated_cost_usd) AS cost_samples FROM compute_events"}),
    }
    evidence = {"stores": stores,
                "authority": authority_configuration(),
                "worker": compute_queue_api.pool.health(),
                "local_ready": SETTINGS.ollama_readiness(timeout=2).get("ready") is True,
                "work": {row["status"]: row["count"] for row in stores["queue"].get("counts", [])},
                "uncertain_executions": next((r["count"] for r in stores["harness"].get("uncertain", [])), 0),
                "recent_completed": stores["queue"].get("completed", []),
                "accounting": {"available": stores["compute"]["ok"], **next(iter(stores["compute"].get("usage", [])), {})}}
    result = interpret(evidence)
    observed = datetime.now(timezone.utc).isoformat()
    with _lock:
        if result["state"] == "HEALTHY":
            _last_success = observed
        result.update(observed_at=observed, last_successful_check=_last_success,
                      last_successful_check_scope="current_service_process")
    result["diagnostics"] = evidence
    return result
