"""Personal JARVIS Stable Spine v1.

This module is deliberately deterministic. Reasoners may propose actions but
cannot authorize themselves. Memory, events and audit remain separate stores.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .generated.portfolio_contracts import validate_action_envelope

POLICY_STATES = {"AUTO", "BOUNDED_AUTO", "GATED", "PROHIBITED"}
VERIFY_STATES = {"PENDING", "VERIFIED", "FAILED", "NOT_OBSERVABLE", "OBSERVED"}

PLATFORM_POLICY: dict[str, str] = {
    "agent.infer": "AUTO",
    "web.search": "AUTO",
    "calendar.read": "AUTO",
    "sensor.read": "AUTO",
    "portal.query": "AUTO",
    "memory.read": "AUTO",
    "memory.propose": "BOUNDED_AUTO",
    "email.draft": "BOUNDED_AUTO",
    "calendar.create": "GATED",
    "email.send": "GATED",
    "public.publish": "GATED",
    "spend.money": "GATED",
    "iot.actuate": "GATED",
    "trust.change": "PROHIBITED",
}

REQUIRED_ENVELOPE_FIELDS = {
    "tenant_id", "actor_id", "actor_type", "action", "parameters", "context",
    "correlation_id", "idempotency_key", "schema_version", "timestamp",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_envelope(value: Any) -> str | None:
    result = validate_action_envelope(value)
    if not result["valid"]:
        return "; ".join(f"{item['path'] or '/'} {item['message']}" for item in result["errors"])
    if value.get("tenant_id") != "personal":
        return "personal JARVIS tenant_id must be 'personal'"
    return None


def classify_action(envelope: Mapping[str, Any], trust: Mapping[str, Any] | None = None) -> dict[str, Any]:
    action = str(envelope["action"])
    platform = PLATFORM_POLICY.get(action, "GATED")
    if platform == "PROHIBITED":
        return {"state": "PROHIBITED", "reason": "platform hard rule", "action": action}

    state = platform
    if trust and trust.get("policy_state") in POLICY_STATES:
        proposed = str(trust["policy_state"])
        # Trust may tighten a rule, but never loosen GATED/PROHIBITED platform policy.
        if platform in {"AUTO", "BOUNDED_AUTO"}:
            state = proposed
        elif platform == "GATED" and proposed == "PROHIBITED":
            state = "PROHIBITED"

    if state == "BOUNDED_AUTO":
        limits = envelope.get("context", {}).get("policy_limits", {})
        if not isinstance(limits, Mapping):
            return {"state": "GATED", "reason": "bounded action lacks valid policy limits", "action": action}

    return {"state": state, "reason": "deterministic platform/trust policy", "action": action}


@dataclass
class Verification:
    command: str = "PENDING"
    execution: str = "PENDING"
    outcome: str = "PENDING"

    def as_dict(self) -> dict[str, str]:
        return {"command": self.command, "execution": self.execution, "outcome": self.outcome}


class SpineStore:
    """SQLite-backed personal store. Separate tables preserve store semantics."""

    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("PRIME_SPINE_DB") or "/tmp/prime-spine.db"
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back, then release the connection on every exit."""
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript("""
            create table if not exists trust_registry (
              action_type text primary key,
              policy_state text not null,
              trust_score real not null default 0,
              clean_successes integer not null default 0,
              failures integer not null default 0,
              platform_locked integer not null default 0,
              metadata_json text not null default '{}',
              updated_at text not null
            );
            create table if not exists event_bus (
              id text primary key,
              correlation_id text not null,
              event_type text not null,
              aggregate_id text not null,
              payload_json text not null,
              created_at text not null
            );
            create table if not exists audit_trail (
              id integer primary key autoincrement,
              correlation_id text not null,
              idempotency_key text not null unique,
              action_type text not null,
              policy_state text not null,
              execution_status text not null,
              verification_json text not null,
              envelope_json text not null,
              decision_record_json text not null,
              created_at text not null
            );
            create table if not exists approvals (
              idempotency_key text primary key,
              correlation_id text not null,
              action_type text not null,
              status text not null,
              envelope_json text not null,
              decision_json text not null,
              decided_at text,
              decision_note text,
              created_at text not null
            );
            create table if not exists trust_evidence (
              id integer primary key autoincrement,
              action_type text not null,
              idempotency_key text not null,
              execution_status text not null,
              verification_json text not null,
              evidence_json text not null,
              created_at text not null
            );
            """)

    def get_trust(self, action: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("select * from trust_registry where action_type=?", (action,)).fetchone()
        return dict(row) if row else None

    def audit(self, envelope: Mapping[str, Any], decision: Mapping[str, Any], execution_status: str, verification: Mapping[str, Any], decision_record: Mapping[str, Any]) -> bool:
        with self.connect() as db:
            cur = db.execute(
                "insert or ignore into audit_trail(correlation_id,idempotency_key,action_type,policy_state,execution_status,verification_json,envelope_json,decision_record_json,created_at) values(?,?,?,?,?,?,?,?,?)",
                (envelope["correlation_id"], envelope["idempotency_key"], envelope["action"], decision["state"], execution_status, json.dumps(verification, sort_keys=True), json.dumps(dict(envelope), sort_keys=True), json.dumps(dict(decision_record), sort_keys=True), utc_now()),
            )
            return cur.rowcount == 1

    def emit(self, envelope: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "insert into event_bus(id,correlation_id,event_type,aggregate_id,payload_json,created_at) values(?,?,?,?,?,?)",
                (str(uuid.uuid4()), envelope["correlation_id"], event_type, envelope["idempotency_key"], json.dumps(dict(payload), sort_keys=True), utc_now()),
            )

    def queue_approval(self, envelope: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "insert or ignore into approvals(idempotency_key,correlation_id,action_type,status,envelope_json,decision_json,created_at) values(?,?,?,?,?,?,?)",
                (envelope["idempotency_key"], envelope["correlation_id"], envelope["action"], "PENDING", json.dumps(dict(envelope), sort_keys=True), json.dumps(dict(decision), sort_keys=True), utc_now()),
            )

    def decide_approval(self, idempotency_key: str, decision: str, note: str | None = None,
                        modifications: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        decision = decision.strip().lower()
        if decision not in {"approve", "modify", "reject"}:
            raise ValueError("decision must be approve, modify, or reject")
        if decision == "modify" and not modifications:
            raise ValueError("modify requires explicit modifications")
        if decision in {"modify", "reject"} and not (note or "").strip():
            raise ValueError(f"{decision} requires a decision note")
        status = {"approve": "APPROVED", "modify": "MODIFIED", "reject": "REJECTED"}[decision]
        with self.connect() as db:
            row = db.execute("select * from approvals where idempotency_key=?", (idempotency_key,)).fetchone()
            if not row:
                return None
            if row["status"] != "PENDING":
                return {**dict(row), "decision_recorded": False}
            decision_note = json.dumps({"note": note, "modifications": dict(modifications or {})}, sort_keys=True)
            db.execute("update approvals set status=?,decided_at=?,decision_note=? where idempotency_key=?", (status, utc_now(), decision_note, idempotency_key))
            updated = db.execute("select * from approvals where idempotency_key=?", (idempotency_key,)).fetchone()
        return {**dict(updated), "decision_recorded": True} if updated else None

    def list_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("select * from approvals order by created_at desc limit ?", (max(1, min(limit, 200)),)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            envelope = json.loads(item.pop("envelope_json"))
            policy = json.loads(item.pop("decision_json"))
            parameters = envelope.get("parameters", {})
            context = envelope.get("context", {})
            item.update({
                "title": context.get("title") or envelope.get("action"),
                "risk": context.get("risk", "consequential"),
                "source": context.get("source", envelope.get("actor_id", "unknown")),
                "evidence": context.get("evidence", []),
                "reversibility": context.get("reversibility", "unknown"),
                "expected_effect": context.get("expected_effect", parameters),
                "policy": policy,
                "parameters": parameters,
            })
            output.append(item)
        return output

    def audit_explorer(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("select * from audit_trail order by created_at desc limit ?", (max(1, min(limit, 200)),)).fetchall()
            approvals = {row["idempotency_key"]: dict(row) for row in db.execute("select * from approvals").fetchall()}
        traces = []
        for row in rows:
            item = dict(row)
            envelope = json.loads(item["envelope_json"])
            record = json.loads(item["decision_record_json"])
            verification = json.loads(item["verification_json"])
            approval = approvals.get(item["idempotency_key"])
            traces.append({
                "correlation_id": item["correlation_id"],
                "request": {"action": item["action_type"], "parameters": envelope.get("parameters", {}), "actor": envelope.get("actor_id")},
                "evidence": record.get("evidence", envelope.get("context", {}).get("evidence", [])),
                "reasoning_route": record.get("reasoning_route", record.get("source", "deterministic_prime_spine")),
                "policy": {"state": item["policy_state"], "record": record},
                "approval": None if not approval else {"status": approval["status"], "decided_at": approval["decided_at"], "decision": approval["decision_note"]},
                "result": {"execution_status": item["execution_status"], "verification": verification},
                "created_at": item["created_at"],
            })
        return traces

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("select * from event_bus order by created_at desc limit ?", (max(1, min(limit, 200)),)).fetchall()
        return [dict(row) for row in rows]


class StableSpine:
    def __init__(self, store: SpineStore | None = None):
        self.store = store or SpineStore()

    def evaluate(self, envelope: Mapping[str, Any], decision_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
        error = validate_envelope(envelope)
        if error:
            return {"ok": False, "error": error, "status": 422}
        decision = classify_action(envelope, self.store.get_trust(str(envelope["action"])))
        verification = Verification().as_dict()
        record = dict(decision_record or {})
        record.setdefault("source", "deterministic_prime_spine")

        state = decision["state"]
        execution_status = "AUTHORIZED"
        event_type = "action.authorized"
        status = 200
        if state == "PROHIBITED":
            execution_status, event_type, status = "BLOCKED", "action.prohibited", 403
        elif state == "GATED":
            execution_status, event_type, status = "PENDING_APPROVAL", "approval.required", 202
            self.store.queue_approval(envelope, decision)

        inserted = self.store.audit(envelope, decision, execution_status, verification, record)
        if inserted:
            self.store.emit(envelope, event_type, {"decision": decision})
        return {"ok": True, "status": status, "decision": decision, "execution_status": execution_status, "verification": verification, "idempotent_replay": not inserted}
