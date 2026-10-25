"""Sanitized read-only adapter for the existing compute event ledger.

This module never instantiates JobQueue (which would initialize/migrate it),
reads no prompt/result text, and never locks the queue for scheduling/deployment.
The ledger lacks trusted workload-origin labels, so its evidence kind remains
observational_unclassified regardless of apparently real-looking job text.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .core import History, Observation, digest, identifier, timestamp


QUEUE_STATES = ("queued", "held", "awaiting_approval", "running", "completed", "failed", "cancelled", "budget_blocked")
QUEUE_ABSORBING = ("completed", "failed", "cancelled", "budget_blocked")
QUEUE_EDGES = tuple(
    sorted(
        [(s, s) for s in QUEUE_ABSORBING]
        + [("queued", s) for s in ("running", "failed", "cancelled", "budget_blocked")]
        + [("held", s) for s in ("running", "cancelled", "failed")]
        + [("running", s) for s in ("queued", "completed", "failed", "cancelled", "budget_blocked")]
        + [("awaiting_approval", s) for s in ("queued", "cancelled")]
    )
)
FIXED_EVENTS = {
    "cloud_reserved": "held",
    "claimed": "running",
    "registry_denied": "failed",
    "aborted_deadline": "failed",
    "reservation_expired": "cancelled",
    "orphaned_worker_requeued": "queued",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "budget_blocked": "budget_blocked",
    "queued": "queued",
}
METADATA_EVENTS = frozenset(
    {"registry_migrated", "terminal_cloud_execution_settled", "collective_publication_unavailable"}
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate event detail key")
        result[key] = value
    return result


def _state(event_type: str, details: Any) -> str | None:
    if not isinstance(details, dict):
        raise ValueError("invalid event details")
    if event_type == "submitted":
        state = details.get("status")
        if state not in {"queued", "awaiting_approval"}:
            raise ValueError("unknown initial state")
        return state
    if event_type == "lease_expired":
        state = details.get("next_status")
        if state not in {"queued", "failed"}:
            raise ValueError("unknown lease transition")
        return state
    if event_type == "approval_decision":
        if details.get("decision") not in {"approved", "rejected"}:
            raise ValueError("unknown approval outcome")
        return "queued" if details["decision"] == "approved" else "cancelled"
    if event_type in FIXED_EVENTS:
        return FIXED_EVENTS[event_type]
    if event_type in METADATA_EVENTS:
        return None
    raise ValueError("unrecognized event semantics")


def read_compute_history(
    path: str | Path, *, agent: str | None = None, since: str | None = None, until: str | None = None
) -> tuple[tuple[History, ...], dict[str, Any]]:
    """Read complete histories for jobs CREATED in a requested time window.

    Read all selected events from a consistent read transaction and order ties
    by SQLite insertion rowid, never UUID. Malformed, incomplete, unknown-event,
    mismatched or impossible histories are excluded with aggregate diagnostics.
    IDs in returned histories are local observations; reports disclose hashes
    and counts, never private prompts, results, errors or event-details text.
    """
    if agent is not None:
        identifier(agent)
    lower = timestamp(since) if since else None
    upper = timestamp(until) if until else None
    if lower and upper and lower > upper:
        raise ValueError("invalid observation window")
    source = Path(path).resolve()
    if not source.is_file():
        return (), {"status": "UNAVAILABLE", "reason": "COMPUTE_EVENT_LEDGER_NOT_FOUND"}
    diagnostics: Counter[str] = Counter()
    histories = []
    try:
        db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return (), {"status": "UNAVAILABLE", "reason": "COMPUTE_EVENT_LEDGER_UNAVAILABLE_OR_UNSUPPORTED"}
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # Read snapshot only, never a queue write/admission lock.
        columns = {row[1] for row in db.execute("PRAGMA table_info(compute_jobs)")}
        required = {"id", "agent", "status", "created_at", "updated_at"}
        if not required <= columns:
            return (), {"status": "UNAVAILABLE", "reason": "COMPUTE_EVENT_SCHEMA_UNSUPPORTED"}
        where, params = ("WHERE j.agent=?", (agent,)) if agent is not None else ("", ())
        jobs = db.execute("SELECT j.id,j.agent,j.status,j.created_at,j.updated_at FROM compute_jobs j " + where, params)
        # The existing event table has no job_id index. One event scan avoids
        # an O(jobs * events) rescan without modifying the operational ledger.
        events_by_job: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for event in db.execute(
            "SELECT e.id,e.job_id,e.event_type,e.details_json,e.created_at,e.rowid FROM compute_events e "
            "JOIN compute_jobs j ON j.id=e.job_id " + where + " ORDER BY e.rowid",
            params,
        ):
            events_by_job[event["job_id"]].append(event)
        for job in jobs:
            diagnostics["jobs_considered"] += 1
            try:
                created = timestamp(job["created_at"])
                identifier(job["id"])
                if lower and created < lower or upper and created > upper:
                    diagnostics["jobs_outside_window"] += 1
                    continue
                events = events_by_job.get(job["id"], [])
                if not events or events[0]["event_type"] not in {"submitted", "cloud_reserved"}:
                    diagnostics["missing_initial_event"] += 1
                    continue
                observations = []
                previous_time = None
                future_seen = False
                for event in events:
                    observed = timestamp(event["created_at"])
                    if observed < created or previous_time is not None and observed < previous_time:
                        raise ValueError("inconsistent event chronology")
                    previous_time = observed
                    if upper and observed > upper:
                        future_seen = True
                        continue
                    details = json.loads(
                        event["details_json"],
                        object_pairs_hook=_unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                    )
                    state = _state(event["event_type"], details)
                    if state is None:
                        diagnostics["metadata_events_ignored"] += 1
                        continue
                    if observations and (observations[-1].state, state) not in QUEUE_EDGES:
                        raise ValueError("invalid state-transition history")
                    if observations and observations[-1].state in QUEUE_ABSORBING:
                        raise ValueError("transition after terminal state")
                    observations.append(Observation(state, observed, event["id"]))
                if not observations:
                    diagnostics["no_observations_in_window"] += 1
                    continue
                if not future_seen and observations[-1].state != job["status"]:
                    diagnostics["current_state_mismatch"] += 1
                    continue
                histories.append(History(job["id"], tuple(observations), "observational_unclassified"))
                diagnostics["jobs_retained"] += 1
            except (ValueError, TypeError, KeyError, IndexError):
                diagnostics["invalid_histories_excluded"] += 1
    except sqlite3.Error:
        return (), {"status": "UNAVAILABLE", "reason": "COMPUTE_EVENT_LEDGER_UNAVAILABLE_OR_UNSUPPORTED"}
    finally:
        db.close()
    histories.sort(key=lambda h: (h.observations[0].timestamp, h.entity_id))
    return tuple(histories), {
        "status": "OBSERVED",
        "evidence_kind": "observational_unclassified",
        "origin_label_available": False,
        "reason": "WORKLOAD_REPRESENTATIVENESS_NOT_ESTABLISHED",
        "diagnostics": dict(diagnostics),
        "history_sha256": digest([h.as_dict() for h in histories]),
        "agent_filter": agent,
        "window": [lower, upper],
        "transition_count": sum(len(h.observations) - 1 for h in histories),
        "grants_execution_authority": False,
    }
