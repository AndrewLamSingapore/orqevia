"""Deterministic JARVIS ORQEVIA FAILSAFE v0.

FAILSAFE has negative authority only: it may freeze consequential execution,
record containment state, and require explicit validated recovery. It never
issues Action Envelopes, grants TAP authority, or invokes an executor.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FailsafeSnapshot:
    state: str
    reason: str
    changed_by: str
    changed_at: str
    generation: int

    @property
    def execution_frozen(self) -> bool:
        return self.state in {"EXECUTION_FREEZE", "CONTAINED", "RECOVERY_PENDING", "VALIDATION", "HARD_LOCK"}


class FailsafeError(RuntimeError):
    pass


class Failsafe:
    """Durable fail-closed containment state.

    Recovery is intentionally two-step: request_recovery() then
    validate_recovery(). HARD_LOCK additionally requires owner authorization.
    """

    VALID_STATES = {
        "NOMINAL", "DEGRADED", "EXECUTION_FREEZE", "CONTAINED",
        "RECOVERY_PENDING", "VALIDATION", "HARD_LOCK",
    }

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=20, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS failsafe_state(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                state TEXT NOT NULL, reason TEXT NOT NULL, changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL, generation INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS failsafe_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                from_state TEXT NOT NULL, to_state TEXT NOT NULL,
                reason TEXT NOT NULL, changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL, generation INTEGER NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO failsafe_state VALUES(1,'NOMINAL','initial state','system',?,0)", (_now(),))

    def snapshot(self) -> FailsafeSnapshot:
        try:
            with self.connect() as db:
                row = db.execute("SELECT * FROM failsafe_state WHERE singleton=1").fetchone()
        except sqlite3.Error as exc:
            # If FAILSAFE state cannot be proven, callers must fail closed.
            raise FailsafeError("failsafe state unavailable") from exc
        if row is None or row["state"] not in self.VALID_STATES:
            raise FailsafeError("failsafe state invalid")
        return FailsafeSnapshot(row["state"], row["reason"], row["changed_by"], row["changed_at"], row["generation"])

    def _transition(self, to_state: str, *, reason: str, changed_by: str) -> FailsafeSnapshot:
        if to_state not in self.VALID_STATES:
            raise ValueError("invalid failsafe state")
        if not reason.strip() or not changed_by.strip():
            raise ValueError("reason and changed_by are required")
        with self.lock:
            try:
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM failsafe_state WHERE singleton=1").fetchone()
                    if row is None:
                        raise FailsafeError("failsafe state missing")
                    generation = int(row["generation"]) + 1
                    changed_at = _now()
                    db.execute("UPDATE failsafe_state SET state=?,reason=?,changed_by=?,changed_at=?,generation=? WHERE singleton=1",
                               (to_state, reason.strip(), changed_by.strip(), changed_at, generation))
                    db.execute("INSERT INTO failsafe_events(from_state,to_state,reason,changed_by,changed_at,generation) VALUES(?,?,?,?,?,?)",
                               (row["state"], to_state, reason.strip(), changed_by.strip(), changed_at, generation))
                return FailsafeSnapshot(to_state, reason.strip(), changed_by.strip(), changed_at, generation)
            except sqlite3.Error as exc:
                raise FailsafeError("failsafe transition could not be recorded") from exc

    def degrade(self, *, reason: str, changed_by: str = "watchdog") -> FailsafeSnapshot:
        current = self.snapshot()
        if current.state == "HARD_LOCK":
            return current
        return self._transition("DEGRADED", reason=reason, changed_by=changed_by)

    def freeze(self, *, reason: str, changed_by: str = "watchdog", hard: bool = False) -> FailsafeSnapshot:
        return self._transition("HARD_LOCK" if hard else "EXECUTION_FREEZE", reason=reason, changed_by=changed_by)

    def contain(self, *, reason: str, changed_by: str = "watchdog") -> FailsafeSnapshot:
        current = self.snapshot()
        if current.state == "HARD_LOCK":
            return current
        return self._transition("CONTAINED", reason=reason, changed_by=changed_by)

    def request_recovery(self, *, reason: str, changed_by: str) -> FailsafeSnapshot:
        current = self.snapshot()
        if current.state == "NOMINAL":
            return current
        return self._transition("RECOVERY_PENDING", reason=reason, changed_by=changed_by)

    def begin_validation(self, *, reason: str, changed_by: str) -> FailsafeSnapshot:
        current = self.snapshot()
        if current.state != "RECOVERY_PENDING":
            raise FailsafeError("recovery validation requires RECOVERY_PENDING")
        return self._transition("VALIDATION", reason=reason, changed_by=changed_by)

    def validate_recovery(self, *, checks_passed: bool, reason: str, changed_by: str,
                          owner_approval_id: str | None = None) -> FailsafeSnapshot:
        current = self.snapshot()
        if current.state != "VALIDATION":
            raise FailsafeError("recovery completion requires VALIDATION")
        if not checks_passed:
            return self._transition("CONTAINED", reason=reason, changed_by=changed_by)
        # Clearing containment always requires an explicit owner approval reference.
        if not owner_approval_id or not owner_approval_id.strip():
            raise FailsafeError("owner approval required to restore NOMINAL")
        return self._transition("NOMINAL", reason=f"{reason}; owner_approval={owner_approval_id.strip()}", changed_by=changed_by)

    def assert_consequential_execution_allowed(self) -> None:
        """PEP/Executor hook: call immediately before consequential execution."""
        snapshot = self.snapshot()
        if snapshot.execution_frozen:
            raise PermissionError(f"FAILSAFE blocks consequential execution: {snapshot.state}: {snapshot.reason}")
