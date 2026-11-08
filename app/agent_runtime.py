"""Owned capability handoffs and sanitized agent execution records.

This module is deliberately independent from model output. The LLM can propose
work; owned identities are checked before each handoff. Tool permissions remain
independent of collaboration and recorded without prompts, credentials, endpoints or result text.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent_registry import (
    RegistryError,
    canonical_agent_id,
    may_consult,
    may_delegate,
    orchestrator_id,
    registered_agent_ids,
    requires_owner_approval,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentAuthorityError(RuntimeError):
    pass


class AgentAuthorityRuntime:
    """Identity-checked handoffs backed by durable, non-authorizing execution records."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            data = Path(os.getenv("ORQEVIA_DATA_DIR", "/data").strip() or "/data")
            try:
                data.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                data = Path("/tmp/orqevia")
                data.mkdir(parents=True, exist_ok=True)
            db_path = data / "agent-authority.db"
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=20, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS agent_authority_events(
              event_id TEXT PRIMARY KEY,
              trace_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              source_agent TEXT,
              target_agent TEXT NOT NULL,
              relation TEXT NOT NULL,
              stage TEXT NOT NULL,
              status TEXT NOT NULL,
              allowed INTEGER NOT NULL,
              consequential INTEGER NOT NULL DEFAULT 0,
              approval_required INTEGER NOT NULL DEFAULT 0,
              owner_approved INTEGER NOT NULL DEFAULT 0,
              external_action INTEGER NOT NULL DEFAULT 0,
              latency_ms REAL,
              reason TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_trace_sequence
              ON agent_authority_events(trace_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_agent_runtime_time
              ON agent_authority_events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_runtime_target
              ON agent_authority_events(target_agent, timestamp DESC);
            """)

    def _next_sequence(self, db: sqlite3.Connection, trace_id: str) -> int:
        row = db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM agent_authority_events WHERE trace_id=?",
            (trace_id,),
        ).fetchone()
        return int(row[0])

    def _record(
        self,
        *,
        trace_id: str,
        source_agent: str | None,
        target_agent: str,
        relation: str,
        stage: str,
        status: str,
        allowed: bool,
        reason: str,
        consequential: bool = False,
        owner_approved: bool = False,
        external_action: bool = False,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        def identity(value):
            try:
                return canonical_agent_id(value)
            except RegistryError:
                if allowed:
                    raise
                return 'UNREGISTERED'

        target = identity(target_agent)
        source = identity(source_agent) if source_agent else None
        approval_required = requires_owner_approval(consequential=consequential)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence = self._next_sequence(db, trace_id)
            event_id = str(uuid.uuid4())
            timestamp = utcnow()
            db.execute(
                """INSERT INTO agent_authority_events
                (event_id,trace_id,timestamp,sequence,source_agent,target_agent,relation,stage,status,
                 allowed,consequential,approval_required,owner_approved,external_action,latency_ms,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, trace_id, timestamp, sequence, source, target, relation, stage, status,
                    int(allowed), int(consequential), int(approval_required), int(owner_approved),
                    int(external_action), latency_ms, reason[:500],
                ),
            )
        return {
            "event_id": event_id,
            "trace_id": trace_id,
            "timestamp": timestamp,
            "sequence": sequence,
            "source_agent": source,
            "target_agent": target,
            "stage": stage,
            "status": status,
            "allowed": allowed,
            "reason": reason,
        }

    def resolve_path(self, specialist: str, intent: str) -> list[str]:
        """Resolve the task's owned capability without a supervisor hop."""
        from .capability_selection import select_capability
        from .agent_registry import responsibility_owner, domain_lead

        try:
            domain_lead(specialist or 'strategy')  # Reject invented domain names.
            return [responsibility_owner(select_capability(intent or specialist or 'strategy'))]
        except RegistryError as exc:
            raise AgentAuthorityError(str(exc)) from None

    def authorize(
        self,
        *,
        source: str,
        target: str,
        relation: str,
        depth: int = 1,
        consequential: bool = False,
        owner_approved: bool = False,
        external_action: bool = False,
    ) -> tuple[bool, str]:
        try:
            source_id, target_id = canonical_agent_id(source), canonical_agent_id(target)
        except RegistryError:
            return False, "unregistered capability identity"
        if relation == "delegate":
            allowed = may_delegate(source_id, target_id, depth=depth)
            reason = "owned capability handoff allowed" if allowed else "unknown, identical or invalid capability handoff"
        elif relation == "consult":
            allowed = may_consult(source_id, target_id)
            reason = "owned capability consultation allowed" if allowed else "unknown or identical capability consultation"
        else:
            return False, f"unsupported agent relation: {relation}"
        if external_action and consequential and not owner_approved:
            return False, "consequential external action requires explicit owner approval"
        return allowed, reason

    def handoff(
        self,
        *,
        source: str,
        target: str,
        relation: str = "delegate",
        depth: int = 1,
        trace_id: str | None = None,
        consequential: bool = False,
        owner_approved: bool = False,
        external_action: bool = False,
    ) -> dict[str, Any]:
        trace = trace_id or str(uuid.uuid4())
        allowed, reason = self.authorize(
            source=source, target=target, relation=relation, depth=depth,
            consequential=consequential, owner_approved=owner_approved, external_action=external_action,
        )
        status = "allowed"
        if allowed and consequential and not owner_approved:
            status = "allowed_proposal_only"
        if not allowed:
            status = "denied"
        event = self._record(
            trace_id=trace, source_agent=canonical_agent_id(source) if allowed else source,
            target_agent=canonical_agent_id(target) if allowed else target, relation=relation,
            stage=f"handoff:{relation}", status=status, allowed=allowed, reason=reason,
            consequential=consequential, owner_approved=owner_approved, external_action=external_action,
        )
        if not allowed:
            raise AgentAuthorityError(reason)
        return event

    def begin_path(
        self,
        path: list[str],
        *,
        trace_id: str | None = None,
        consequential: bool = False,
    ) -> str:
        try:
            path = [canonical_agent_id(agent) for agent in path]
        except RegistryError as exc:
            raise AgentAuthorityError(str(exc)) from None
        if not path or len(path) != len(set(path)) or orchestrator_id() in path:
            raise AgentAuthorityError("agent path requires distinct owned capabilities")
        trace = trace_id or str(uuid.uuid4())
        source = orchestrator_id()
        for depth, target in enumerate(path, 1):
            self.handoff(source=source, target=target, relation="delegate", depth=depth,
                         trace_id=trace, consequential=consequential)
            source = target
        return trace

    def stage(
        self,
        *,
        trace_id: str,
        agent_id: str,
        stage: str,
        status: str,
        latency_ms: float | None = None,
        consequential: bool = False,
    ) -> dict[str, Any]:
        if status not in {"started", "completed", "failed", "withheld", "blocked"}:
            raise AgentAuthorityError(f"unsupported runtime status: {status}")
        return self._record(
            trace_id=trace_id, source_agent=None, target_agent=agent_id, relation="execute",
            stage=stage, status=status, allowed=status != "blocked", reason="runtime stage",
            consequential=consequential, latency_ms=latency_ms,
        )

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM agent_authority_events ORDER BY timestamp DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        recent_cutoff = (now - timedelta(minutes=5)).isoformat()
        with self.connect() as db:
            completed = db.execute(
                """SELECT COUNT(DISTINCT trace_id) FROM agent_authority_events
                   WHERE timestamp>=? AND relation='execute' AND status IN ('completed','withheld','failed')""",
                (start_day,),
            ).fetchone()[0]
            denied = db.execute(
                "SELECT COUNT(*) FROM agent_authority_events WHERE timestamp>=? AND status='denied'",
                (start_day,),
            ).fetchone()[0]
            latest = db.execute(
                """SELECT e.target_agent,e.status FROM agent_authority_events e
                   JOIN (SELECT target_agent,MAX(timestamp) ts FROM agent_authority_events
                         WHERE timestamp>=? GROUP BY target_agent) x
                   ON e.target_agent=x.target_agent AND e.timestamp=x.ts""",
                (recent_cutoff,),
            ).fetchall()
            active = len({row["target_agent"] for row in latest if row["status"] == "started"})
            latency = db.execute(
                "SELECT AVG(latency_ms) FROM agent_authority_events WHERE timestamp>=? AND latency_ms IS NOT NULL",
                (start_day,),
            ).fetchone()[0]
        return {
            "registered_agents": len(registered_agent_ids(include_orchestrator=False)),
            "active_agents": active,
            "executions_today": int(completed or 0),
            "denied_handoffs_today": int(denied or 0),
            "average_latency_ms": round(float(latency), 1) if latency is not None else None,
            "active_window_seconds": 300,
        }

    def public_snapshot(self, limit: int = 100) -> dict[str, Any]:
        """Return only fields approved for the public Authority Engine trace boundary."""
        rows = list(reversed(self.recent(limit)))
        events = [
            {
                "trace_id": row["trace_id"],
                "timestamp": row["timestamp"],
                "agent_id": row["target_agent"],
                "stage": row["stage"],
                "status": row["status"],
                "sequence": row["sequence"],
            }
            for row in rows
        ]
        return {
            "ok": True,
            "state": "verified_events" if events else "no_public_trace",
            "generated_at": utcnow(),
            "summary": self.summary(),
            "events": events,
            "boundary": "sanitized runtime authority metadata only; no prompts, results, credentials or endpoints",
        }
