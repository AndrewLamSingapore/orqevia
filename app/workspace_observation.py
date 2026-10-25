"""Read-only, content-free observations of work owned through Interface Node.

The caller passes an authenticated client and its *server-issued* policy. Neither
headers nor browser-local task caches choose account scope. Preserved account
bindings have the same meaning as ``interface_node.own_task``; this reader never
creates them. Canonical state comes from ``objective_api._get(read_only=True)``
for the selected page only. Stored ``submitted`` is never treated as RUNNING.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


_ACCOUNT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_TASK_STATES = frozenset(
    {
        "RUNNING",
        "WAITING FOR RESOURCE",
        "COMPLETED",
        "COMPLETED_WITH_FAILURES",
        "reconciliation_required",
    }
)
_JOB_STATES = frozenset(
    {
        "queued",
        "held",
        "running",
        "completed",
        "failed",
        "cancelled",
        "budget_blocked",
        "denied",
        "awaiting_approval",
        "awaiting_authority",
    }
)
_STATE_SOURCES = frozenset({"QUEUE", "OBJECTIVE_DISPATCH", "QUEUE_AND_OBJECTIVE_DISPATCH"})
_TIME_SOURCES = frozenset({"QUEUE", "OBJECTIVE_METADATA", "OBJECTIVE_METADATA_AND_QUEUE", "UNAVAILABLE"})
_SOURCE = "OBJECTIVE_CANONICAL_READ_ONLY"


class _Unavailable(Exception):
    pass


class _Unauthorized(Exception):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_only(path: Path, stack: ExitStack) -> sqlite3.Connection:
    if not path.is_file():
        raise _Unavailable()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    stack.callback(connection.close)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _account(value):
    if value is not None and (not isinstance(value, str) or not _ACCOUNT.fullmatch(value)):
        raise _Unauthorized()
    return value


def _policy_reader(root: Path, stack: ExitStack):
    """Reuse configured policy, reading PWA session metadata without its migrator."""
    from . import interface_node as node, open_access

    cached = {}
    session_db = None

    def read(client):
        nonlocal session_db
        if client in cached:
            return cached[client]
        if open_access.enabled() or not client.startswith("pwa:"):
            value = node.client_policy(client)
        else:
            from . import pwa_sessions

            if not re.fullmatch(r"pwa:[a-f0-9]{32}", client):
                cached[client] = {}
                return {}
            if session_db is None:
                session_db = _read_only(root / "pwa-sessions.db", stack)
            row = session_db.execute(
                "SELECT expires,revoked,owner_account_id,role FROM sessions WHERE client_id=?",
                (client,),
            ).fetchone()
            if not row or row[1] or row[0] <= time.time():
                value = {}
            else:
                if row[3] not in {"OWNER", "MEMBER"}:
                    raise _Unavailable()
                # These are the existing PWA policy checks, without database().
                classification = os.getenv("ORQEVIA_PWA_DATA_CLASSIFICATION", "LOCAL_ONLY")
                ceiling = float(os.getenv("ORQEVIA_PWA_MAX_COST_USD", "0"))
                if (
                    classification not in {"LOCAL_ONLY", "CLOUD_PERMITTED"}
                    or not math.isfinite(ceiling)
                    or not 0 <= ceiling <= 1
                ):
                    raise _Unavailable()
                value = {
                    "expires_at": row[0],
                    "role": row[3],
                    "capabilities": pwa_sessions.OWNER_SCOPES if row[3] == "OWNER" else pwa_sessions.SCOPES,
                    **({"owner_account_id": row[2]} if row[2] else {}),
                }
        if not isinstance(value, dict):
            raise _Unavailable()
        cached[client] = value
        return value

    return read


def _owns_read(policy: dict) -> bool:
    capabilities = policy.get("capabilities")
    if not isinstance(capabilities, list) or "task.read" not in capabilities:
        return False
    if "expires_at" in policy:
        from . import open_access

        expiry = policy["expires_at"]
        # Existing explicit open-access mode intentionally issues positive infinity.
        if (
            type(expiry) not in (int, float)
            or math.isnan(expiry)
            or expiry <= time.time()
            or not math.isfinite(expiry)
            and not open_access.enabled()
        ):
            return False
    return True


def _owned_clients(db, caller, account, read_policy):
    prior = db.execute("SELECT account FROM client_accounts WHERE client=?", (caller,)).fetchone()
    if account is not None and prior and prior[0] != account:
        raise _Unauthorized()
    if account is None:
        return [caller]
    clients = {caller}
    for owner, preserved in db.execute(
        "SELECT DISTINCT r.client,a.account FROM requests r LEFT JOIN client_accounts a ON a.client=r.client"
    ):
        current = _account(read_policy(owner).get("owner_account_id"))
        if current is not None and preserved is not None and current != preserved:
            if account in {current, preserved}:
                raise _Unauthorized()
            continue
        # own_task permits preserved ownership when the original session expires.
        if (current if current is not None else preserved) == account:
            clients.add(owner)
    return sorted(clients)


def _task_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Invalid canonical task identifier")
    return value


def _timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid canonical timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 2100:
        raise ValueError("Invalid canonical timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def _project(task_id, value):
    from .agent_registry import registered_agent_ids

    if not isinstance(value, dict) or _task_id(value.get("id")) != task_id:
        raise ValueError("Invalid canonical task binding")
    state = value.get("state")
    revision = value.get("revision")
    if state not in _TASK_STATES:
        raise ValueError("Invalid canonical state")
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError("Invalid canonical revision")
    metadata = value.get("execution_metadata")
    if metadata is None and state == "reconciliation_required":
        metadata = {}
    elif (
        not isinstance(metadata, dict)
        or metadata.get("schema_version") != "jarvis.authoritative-execution.v1"
        or metadata.get("authoritative") is not True
        or metadata.get("task_id") != task_id
        or metadata.get("state") != state
        or metadata.get("revision") != revision
        or revision is None
    ):
        raise ValueError("Invalid canonical metadata binding")
    jobs = metadata.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("Invalid canonical jobs")
    agents = set()
    counts = {}
    registered = registered_agent_ids()
    for job in jobs:
        if not isinstance(job, dict) or job.get("agent") not in registered or job.get("state") not in _JOB_STATES:
            raise ValueError("Invalid canonical job")
        _task_id(job.get("job_id"))
        agents.add(job["agent"])
        counts[job["state"]] = counts.get(job["state"], 0) + 1
    created = _timestamp(metadata.get("created_at"))
    updated = _timestamp(metadata.get("updated_at"))
    runtime = metadata.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ValueError("Invalid canonical runtime")
    source_revision = runtime.get("source_revision", "UNKNOWN")
    if source_revision != "UNKNOWN" and (
        not isinstance(source_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", source_revision)
    ):
        raise ValueError("Invalid canonical runtime revision")
    image = runtime.get("image_digest")
    if image is not None and (not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)):
        raise ValueError("Invalid canonical image digest")
    provenance = metadata.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("Invalid canonical provenance")
    fields = provenance.get("timestamp_fields", {})
    if not isinstance(fields, dict):
        raise ValueError("Invalid canonical timestamp provenance")
    return {
        "id": task_id,
        "state": state,
        "revision": revision,
        "agents": sorted(agents),
        "created_at": created,
        "updated_at": updated,
        "progress": None,
        "execution_evidence": {
            "source": _SOURCE,
            "state_provenance": provenance.get("state") if provenance.get("state") in _STATE_SOURCES else "UNAVAILABLE",
            "timestamp_fields": {
                key: fields.get(key) if fields.get(key) in _TIME_SOURCES else "UNAVAILABLE"
                for key in ("created_at", "started_at", "completed_at", "updated_at")
            },
            "runtime": {"source_revision": source_revision, "image_digest": image},
            "job_count": len(jobs) if metadata else None,
            "job_state_counts": counts,
            "verification": "UNVERIFIED",
            "model_content_is_evidence": False,
        },
    }


def owned_work_snapshot(client_id: str, policy: dict, *, limit: int = 50) -> dict:
    """Observe one page of existing owned objectives without content or mutations.

    ``policy`` must come from server authentication, never request JSON/headers.
    ``limit`` is a display-page size (1..50), not admission or request throttling.
    Missing, incompatible or conflicting sources never become a healthy empty list.
    """
    result = {
        "schema_version": "orqevia.owned-work.v1",
        "status": "UNAVAILABLE",
        "scope": "CLIENT",
        "observed_at": _utcnow(),
        "tasks": [],
        "activity": [],
        "has_more": False,
        "provenance": {
            "ownership": "INTERFACE_REQUESTS_AND_SERVER_POLICY",
            "state": _SOURCE,
            "read_only": True,
            "model_content_is_evidence": False,
            "activity_semantics": "CURRENT_STATE_OBSERVATIONS_NOT_HISTORICAL_STATE_CHANGE_EVENTS",
        },
    }
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or not isinstance(policy, dict)
        or not _owns_read(policy)
    ):
        return {**result, "status": "UNAUTHORIZED", "reason": "TASK_READ_UNAVAILABLE"}
    if type(limit) is not int or not 1 <= limit <= 50:
        return {**result, "reason": "INVALID_DISPLAY_PAGE"}
    root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
    objective_path = Path(os.getenv("PRIME_DATA_DIR", "/data")) / "objectives.db"
    try:
        with ExitStack() as stack:
            read_policy = _policy_reader(root, stack)
            current = read_policy(client_id)
            if (
                not _owns_read(current)
                or _account(policy.get("owner_account_id")) != _account(current.get("owner_account_id"))
                or policy.get("role") != current.get("role")
            ):
                raise _Unauthorized()
            account = _account(current.get("owner_account_id"))
            result["scope"] = "OWNER_ACCOUNT" if account is not None else "CLIENT"
            db = _read_only(root / "interface.db", stack)
            if not objective_path.is_file():
                raise _Unavailable()
            owners = _owned_clients(db, client_id, account, read_policy)
            db.execute("ATTACH DATABASE ? AS objective_history", (objective_path.resolve().as_uri() + "?mode=ro",))
            placeholders = ",".join("?" for _ in owners)
            rows = db.execute(
                "SELECT r.task,MAX(m.updated_at),MAX(r.rowid) FROM requests r "
                "JOIN objective_history.objectives o ON o.id=r.task "
                "LEFT JOIN objective_history.objective_metadata m ON m.task=r.task "
                f"WHERE r.client IN ({placeholders}) GROUP BY r.task "
                "ORDER BY MAX(m.updated_at) DESC,MAX(r.rowid) DESC,r.task LIMIT ?",
                (*owners, limit + 1),
            ).fetchall()
            from . import interface_node as node, objective_api

            # _get reads the queue through its existing SELECT-only getter. Check
            # existence first so sqlite cannot create a missing queue implicitly.
            if rows and not Path(objective_api.compute_queue_api.queue.db_path).is_file():
                raise _Unavailable()
            authorization = node.owner_transport() if rows else None
            tasks = [
                _project(_task_id(row[0]), objective_api._get(row[0], authorization, read_only=True))
                for row in rows[:limit]
            ]
            # Recheck the caller after reading: a concurrent policy/account change
            # must not publish a snapshot authorized under a stale account binding.
            refreshed_policy = _policy_reader(root, stack)
            if (
                refreshed_policy(client_id) != current
                or _owned_clients(db, client_id, account, refreshed_policy) != owners
            ):
                raise _Unauthorized()
            tasks.sort(key=lambda item: (item["updated_at"] or "", item["id"]), reverse=True)
            activity = [
                {
                    "event": "TASK_STATE_OBSERVATION",
                    "task_id": item["id"],
                    "state": item["state"],
                    "revision": item["revision"],
                    "timestamp": item["updated_at"],
                    "observed_at": result["observed_at"],
                    "source": _SOURCE,
                }
                for item in tasks
                if item["updated_at"] is not None
            ]
            return {**result, "status": "OBSERVED", "tasks": tasks, "activity": activity, "has_more": len(rows) > limit}
    except _Unauthorized:
        return {**result, "status": "UNAUTHORIZED", "reason": "OWNERSHIP_POLICY_CONFLICT"}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError, _Unavailable):
        return {**result, "reason": "CANONICAL_SOURCE_UNAVAILABLE"}
    except Exception as exc:
        # Only the established HTTP exception class is converted here; programming
        # errors still surface to callers/tests instead of masquerading as absence.
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            return {**result, "reason": "CANONICAL_SOURCE_UNAVAILABLE"}
        raise
