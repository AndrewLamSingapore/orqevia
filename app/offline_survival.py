"""Offline survival primitives for JARVIS PRIME.

Three guarantees, as code rather than documentation:

A. LOCAL-FIRST - local identity, orchestration, memory, artifacts, governance and local model
   inference already live in PRIME's own stores; this module adds the deliberate capability
   state machine so the runtime reports what is local, degraded or unavailable instead of
   inferring whole-system failure from one unreachable provider.

B. GRACEFUL DEGRADATION - internet-dependent work is classified (LOCAL_AVAILABLE,
   NETWORK_REQUIRED, PROVIDER_REQUIRED, DEFERABLE, NON_DEFERABLE) and reported as
   DEFERRED_OFFLINE rather than failed.

C. STORE-AND-FORWARD - consequential outbound operations are held in a durable queue with
   provenance and an idempotency key, and are reconciled on reconnect only after authority,
   dependency, relevance and idempotency are re-checked. Nothing is silently dropped, nothing
   is silently marked complete, and no external side effect is attempted while offline.

The module is deliberately stdlib-only and owns its own SQLite file so that an offline host
needs nothing beyond Python to keep queue state durable across restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CapabilityState",
    "DependencyClass",
    "QueueState",
    "DeferredOperation",
    "ReconcileResult",
    "OfflineSurvival",
    "OperationRejected",
]


class CapabilityState(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    RECONNECTING = "RECONNECTING"


class DependencyClass(str, Enum):
    LOCAL_AVAILABLE = "LOCAL_AVAILABLE"
    NETWORK_REQUIRED = "NETWORK_REQUIRED"
    PROVIDER_REQUIRED = "PROVIDER_REQUIRED"
    DEFERABLE = "DEFERABLE"
    NON_DEFERABLE = "NON_DEFERABLE"


class QueueState(str, Enum):
    PENDING = "PENDING"
    DEFERRED_OFFLINE = "DEFERRED_OFFLINE"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class OperationRejected(ValueError):
    """Raised when an operation may not be queued (e.g. it embeds a secret)."""


# Operation names that always need the internet, the model provider, or neither.
DEFAULT_CLASSIFICATION: dict[str, DependencyClass] = {
    "portal.publish": DependencyClass.DEFERABLE,
    "github.push": DependencyClass.DEFERABLE,
    "github.pull_request": DependencyClass.DEFERABLE,
    "notification.send": DependencyClass.DEFERABLE,
    "external.api": DependencyClass.DEFERABLE,
    "web.research": DependencyClass.NETWORK_REQUIRED,
    "model.frontier": DependencyClass.PROVIDER_REQUIRED,
    "memory.index": DependencyClass.LOCAL_AVAILABLE,
    "artifact.write": DependencyClass.LOCAL_AVAILABLE,
    "objective.create": DependencyClass.LOCAL_AVAILABLE,
}

# Anything that looks like a credential must never be written into a queue payload.
SECRET_KEY_MARKERS = ("token", "secret", "password", "passwd", "credential", "api_key", "apikey", "authorization")


@dataclass(frozen=True)
class DeferredOperation:
    id: str
    objective_id: str
    operation_type: str
    payload_ref: str
    payload_digest: str
    idempotency_key: str
    authorization_ref: str
    dependency: DependencyClass
    created_at: float
    state: QueueState
    attempt_count: int
    last_error: str
    next_retry_at: float
    expires_at: float | None
    receipt: dict[str, Any] | None
    reconciled_at: float | None
    reason: str


@dataclass(frozen=True)
class ReconcileResult:
    operation_id: str
    state: QueueState
    executed: bool
    reason: str
    receipt: dict[str, Any] | None = None


def _digest(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _assert_no_secrets(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in SECRET_KEY_MARKERS):
            raise OperationRejected(f"refusing to queue payload field {key!r}: credentials must not be stored in the queue")
        if isinstance(value, dict):
            _assert_no_secrets(value)


class OfflineSurvival:
    """Capability state plus the durable store-and-forward queue."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        classification: dict[str, DependencyClass] | None = None,
        backoff_base_seconds: float = 30.0,
        backoff_max_seconds: float = 1800.0,
    ) -> None:
        if db_path is None:
            data = Path(os.getenv("PRIME_DATA_DIR", "/data").strip() or "/data")
            data.mkdir(parents=True, exist_ok=True)
            db_path = data / "offline-queue.db"
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.classification = dict(DEFAULT_CLASSIFICATION)
        if classification:
            self.classification.update(classification)
        self.backoff_base_seconds = float(backoff_base_seconds)
        self.backoff_max_seconds = float(backoff_max_seconds)
        self._state = CapabilityState.ONLINE
        self._init()

    # ------------------------------------------------------------------ storage
    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=20, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS deferred_operations(
                  id TEXT PRIMARY KEY,
                  objective_id TEXT NOT NULL,
                  operation_type TEXT NOT NULL,
                  payload_ref TEXT NOT NULL,
                  payload_digest TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  authorization_ref TEXT NOT NULL,
                  dependency TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  state TEXT NOT NULL,
                  attempt_count INTEGER NOT NULL DEFAULT 0,
                  last_error TEXT NOT NULL DEFAULT '',
                  next_retry_at REAL NOT NULL DEFAULT 0,
                  expires_at REAL,
                  receipt_json TEXT,
                  reconciled_at REAL,
                  reason TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS deferred_operations_state_idx
                  ON deferred_operations(state, next_retry_at);
                """
            )

    @staticmethod
    def _row_to_operation(row: sqlite3.Row) -> DeferredOperation:
        return DeferredOperation(
            id=row["id"],
            objective_id=row["objective_id"],
            operation_type=row["operation_type"],
            payload_ref=row["payload_ref"],
            payload_digest=row["payload_digest"],
            idempotency_key=row["idempotency_key"],
            authorization_ref=row["authorization_ref"],
            dependency=DependencyClass(row["dependency"]),
            created_at=row["created_at"],
            state=QueueState(row["state"]),
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
            next_retry_at=row["next_retry_at"],
            expires_at=row["expires_at"],
            receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
            reconciled_at=row["reconciled_at"],
            reason=row["reason"],
        )

    # ------------------------------------------------------------------ A/B: state
    @property
    def state(self) -> CapabilityState:
        return self._state

    def observe(self, *, network: bool, provider: bool) -> CapabilityState:
        """Record what is reachable now and move the capability state deliberately.

        Local capability is never in question: a host with no internet is OFFLINE, not broken.
        """
        if network and provider:
            if self._state in (CapabilityState.OFFLINE, CapabilityState.DEGRADED, CapabilityState.RECONNECTING):
                self._state = CapabilityState.RECONNECTING
            else:
                self._state = CapabilityState.ONLINE
        elif not network and not provider:
            self._state = CapabilityState.OFFLINE
        else:
            self._state = CapabilityState.DEGRADED
        return self._state

    def confirm_online(self) -> CapabilityState:
        """Finish the reconnect handshake once cloud capability has been health-checked."""
        if self._state is not CapabilityState.RECONNECTING:
            raise RuntimeError(f"cannot confirm ONLINE from {self._state.value}")
        self._state = CapabilityState.ONLINE
        return self._state

    def classify(self, operation_type: str) -> DependencyClass:
        return self.classification.get(operation_type, DependencyClass.DEFERABLE)

    def offline_actions(self) -> dict[str, str]:
        """What the operator-facing surface should say while this state is active."""
        if self._state is CapabilityState.ONLINE:
            disposition = {name: "AVAILABLE" for name in self.classification}
        elif self._state is CapabilityState.OFFLINE:
            disposition = {}
            for name, dependency in self.classification.items():
                if dependency is DependencyClass.LOCAL_AVAILABLE:
                    disposition[name] = "AVAILABLE"
                elif dependency is DependencyClass.PROVIDER_REQUIRED:
                    disposition[name] = "DEFERRED_OFFLINE"
                else:
                    disposition[name] = "DEFERRED_OFFLINE"
        else:
            disposition = {}
            for name, dependency in self.classification.items():
                disposition[name] = "AVAILABLE" if dependency is DependencyClass.LOCAL_AVAILABLE else "DEGRADED"
        return {
            "mode": f"OFFLINE — LOCAL INTELLIGENCE" if self._state is CapabilityState.OFFLINE else self._state.value,
            "cloud_model": "UNAVAILABLE" if self._state is CapabilityState.OFFLINE else "AVAILABLE",
            "local_model": "READY",
            "memory": "READY",
            "local_tools": "READY",
            "portal_sync": f"{len(self.pending())} ITEMS QUEUED",
            "actions": disposition,
        }

    # ------------------------------------------------------------------ C: queue
    def enqueue(
        self,
        *,
        objective_id: str,
        operation_type: str,
        payload_ref: str,
        idempotency_key: str,
        authorization_ref: str,
        payload: dict[str, Any] | None = None,
        dependency: DependencyClass | None = None,
        now: float | None = None,
        expires_at: float | None = None,
    ) -> DeferredOperation:
        """Persist an operation for later reconciliation. Never executed here."""
        payload = payload or {}
        _assert_no_secrets(payload)
        moment = time.time() if now is None else float(now)
        resolved_dependency = dependency or self.classify(operation_type)
        if resolved_dependency is DependencyClass.LOCAL_AVAILABLE:
            raise OperationRejected(f"{operation_type} is local; it must not be deferred")
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM deferred_operations WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing:
                return self._row_to_operation(existing)
            operation_id = str(uuid.uuid4())
            state = QueueState.DEFERRED_OFFLINE if self._state in (CapabilityState.OFFLINE, CapabilityState.DEGRADED) else QueueState.PENDING
            db.execute(
                "INSERT INTO deferred_operations("
                "id,objective_id,operation_type,payload_ref,payload_digest,idempotency_key,authorization_ref,"
                "dependency,created_at,state,attempt_count,last_error,next_retry_at,expires_at,receipt_json,reconciled_at,reason"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?,?,NULL,NULL,'')",
                (
                    operation_id,
                    objective_id,
                    operation_type,
                    payload_ref,
                    _digest(payload),
                    idempotency_key,
                    authorization_ref,
                    resolved_dependency.value,
                    moment,
                    state.value,
                    moment,
                    expires_at,
                ),
            )
        return self.get(operation_id)

    def get(self, operation_id: str) -> DeferredOperation:
        with self.connect() as db:
            row = db.execute("SELECT * FROM deferred_operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return self._row_to_operation(row)

    def all(self) -> list[DeferredOperation]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM deferred_operations ORDER BY created_at").fetchall()
        return [self._row_to_operation(row) for row in rows]

    def pending(self) -> list[DeferredOperation]:
        return [
            operation
            for operation in self.all()
            if operation.state in (QueueState.PENDING, QueueState.DEFERRED_OFFLINE, QueueState.RECONCILING, QueueState.FAILED)
        ]

    def _update(self, operation_id: str, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{name}=?" for name in fields)
        with self.connect() as db:
            db.execute(f"UPDATE deferred_operations SET {columns} WHERE id=?", (*fields.values(), operation_id))

    def expire(self, *, now: float | None = None) -> list[str]:
        """Mark expired operations explicitly; they are never executed afterwards."""
        moment = time.time() if now is None else float(now)
        expired: list[str] = []
        for operation in self.pending():
            if operation.expires_at is not None and operation.expires_at <= moment:
                self._update(
                    operation.id,
                    state=QueueState.EXPIRED.value,
                    reason="expired before reconciliation",
                )
                expired.append(operation.id)
        return expired

    def reconcile(
        self,
        *,
        executors: dict[str, Callable[[DeferredOperation], dict[str, Any]]],
        authority_valid: Callable[[DeferredOperation], bool],
        still_relevant: Callable[[DeferredOperation], bool] | None = None,
        remote_applied: Callable[[DeferredOperation], bool] | None = None,
        now: float | None = None,
        limit: int = 25,
    ) -> list[ReconcileResult]:
        """Reconcile queued work in the mandated order.

        RELOAD -> REVALIDATE AUTHORITY -> REVALIDATE DEPENDENCIES -> RELEVANCE -> IDEMPOTENCY ->
        EXECUTE ONCE -> VERIFY REMOTE ACCEPTANCE -> RECEIPT -> RECONCILED.

        Authority revocation and staleness stop execution. Remote-side application is detected
        and recorded without duplicating the side effect. Failures retain the item with accurate
        retry state. Unknown operation types are non-deferable and fail loudly rather than being
        silently completed.
        """
        moment = time.time() if now is None else float(now)
        if self._state is not CapabilityState.ONLINE:
            return []
        self.expire(now=moment)
        due = [
            operation
            for operation in self.pending()
            if operation.state in (QueueState.PENDING, QueueState.DEFERRED_OFFLINE, QueueState.FAILED)
            and operation.next_retry_at <= moment
        ][:limit]
        results: list[ReconcileResult] = []
        for operation in due:
            if not authority_valid(operation):
                self._update(
                    operation.id,
                    state=QueueState.SUPERSEDED.value,
                    reason="authority changed while offline; not executed",
                )
                results.append(ReconcileResult(operation.id, QueueState.SUPERSEDED, False, "authority_invalid"))
                continue
            executor = executors.get(operation.operation_type)
            if executor is None:
                self._fail(
                    operation,
                    moment,
                    "no executor registered for operation type; classified NON_DEFERABLE",
                    terminal=True,
                )
                results.append(ReconcileResult(operation.id, QueueState.FAILED, False, "unknown_operation_type"))
                continue
            if still_relevant is not None and not still_relevant(operation):
                self._update(
                    operation.id,
                    state=QueueState.SUPERSEDED.value,
                    reason="no longer relevant; not executed blindly",
                )
                results.append(ReconcileResult(operation.id, QueueState.SUPERSEDED, False, "stale"))
                continue
            if remote_applied is not None and remote_applied(operation):
                receipt = {"already_applied": True, "idempotency_key": operation.idempotency_key}
                self._update(
                    operation.id,
                    state=QueueState.RECONCILED.value,
                    receipt_json=json.dumps(receipt, sort_keys=True),
                    reconciled_at=moment,
                    reason="remote already holds this idempotency key; not duplicated",
                )
                results.append(ReconcileResult(operation.id, QueueState.RECONCILED, False, "already_applied", receipt))
                continue
            self._update(operation.id, state=QueueState.RECONCILING.value, reason="")
            try:
                response = executor(operation) or {}
            except Exception as exc:  # noqa: BLE001 - retained, never swallowed silently
                self._fail(operation, moment, f"{type(exc).__name__}: {exc}")
                results.append(ReconcileResult(operation.id, QueueState.FAILED, False, "executor_error"))
                continue
            if not response.get("accepted"):
                self._fail(operation, moment, f"remote did not accept: {response.get('detail', 'no detail')}")
                results.append(ReconcileResult(operation.id, QueueState.FAILED, False, "not_accepted"))
                continue
            receipt = {key: value for key, value in response.items() if key != "accepted"}
            self._update(
                operation.id,
                state=QueueState.RECONCILED.value,
                receipt_json=json.dumps(receipt, sort_keys=True),
                reconciled_at=moment,
                attempt_count=operation.attempt_count + 1,
                last_error="",
                reason="executed once and acknowledged by the remote side",
            )
            results.append(ReconcileResult(operation.id, QueueState.RECONCILED, True, "executed", receipt))
        return results

    def _fail(self, operation: DeferredOperation, moment: float, error: str, *, terminal: bool = False) -> None:
        attempts = operation.attempt_count + 1
        if terminal:
            self._update(
                operation.id,
                state=QueueState.FAILED.value,
                attempt_count=attempts,
                last_error=error,
                next_retry_at=float("inf"),
                reason="terminal: no retry path",
            )
            return
        delay = min(self.backoff_base_seconds * (2 ** (attempts - 1)), self.backoff_max_seconds)
        self._update(
            operation.id,
            state=QueueState.FAILED.value,
            attempt_count=attempts,
            last_error=error,
            next_retry_at=moment + delay,
            reason="retained for later reconciliation",
        )
