"""Fail-closed Agent Harness v0 policy-enforcement point.

Reasoners can propose work, but only a lease signed by the Trusted Authority
Plane after a Stable Spine decision can reach an executor. The signing secret
must remain confined to that authority plane; agents never receive it.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


AUTH_VERSION = "1.0.0"
ALGORITHM = "HMAC-SHA256"
REQUIRED_ENVELOPE_FIELDS = {
    "tenant_id", "actor_id", "actor_type", "action", "parameters", "context",
    "correlation_id", "idempotency_key", "schema_version", "timestamp",
    "authorization",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _signed_bytes(envelope: Mapping[str, Any]) -> bytes:
    value = copy.deepcopy(dict(envelope))
    authorization = value.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("authorization must be an object")
    authorization.pop("signature", None)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass(frozen=True)
class HarnessPolicy:
    policy_version: str = "harness-v0"
    max_ttl_seconds: int = 300
    clock_skew_seconds: int = 30
    pilot_agents: frozenset[str] = field(
        default_factory=lambda: frozenset({"a14", "a16", "a21"})
    )
    privileged_actions: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "calendar.create", "email.send", "public.publish", "spend.money",
            "iot.actuate", "executor.run", "deploy.production",
        })
    )
    advisory_fail_open_on_ledger_failure: bool = False


@dataclass(frozen=True)
class HarnessDecision:
    authorized: bool
    status: str
    reason: str
    lease_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "status": self.status,
            "reason": self.reason,
            "lease_id": self.lease_id,
        }


class HarnessUnavailable(RuntimeError):
    """Raised when a privileged decision cannot be durably recorded."""


class ActionEnvelopeIssuer:
    """Trusted-plane helper. Do not construct this inside an agent process."""

    def __init__(self, secret: bytes, key_id: str = "authority-v0"):
        if len(secret) < 32:
            raise ValueError("signing secret must contain at least 32 bytes")
        self.secret = bytes(secret)
        self.key_id = key_id

    def issue(
        self,
        proposal: Mapping[str, Any],
        *,
        decision_id: str,
        policy_version: str,
        ttl_seconds: int = 300,
        privileged: bool = False,
        owner_approval_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        issued = (now or utcnow()).astimezone(timezone.utc)
        expires = issued + timedelta(seconds=max(1, int(ttl_seconds)))
        envelope = copy.deepcopy(dict(proposal))
        envelope["schema_version"] = "2.0.0"
        envelope["authorization"] = {
            "version": AUTH_VERSION,
            "algorithm": ALGORITHM,
            "key_id": self.key_id,
            "nonce": str(uuid.uuid4()),
            "lease_id": str(uuid.uuid4()),
            "issued_at": _iso(issued),
            "expires_at": _iso(expires),
            "lease_expires_at": _iso(expires),
            "policy_version": policy_version,
            "decision_id": decision_id,
            "decision_source": "stable_spine",
            "decision_state": "AUTHORIZED",
            "privileged": bool(privileged),
            "owner_approval_id": owner_approval_id,
        }
        envelope["authorization"]["signature"] = hmac.new(
            self.secret, _signed_bytes(envelope), hashlib.sha256
        ).hexdigest()
        return envelope


class ActionHarness:
    """PEP that validates, records, leases, revokes and consumes executions."""

    def __init__(
        self,
        db_path: str | Path,
        verification_keys: Mapping[str, bytes],
        policy: HarnessPolicy | None = None,
    ):
        self.db_path = str(db_path)
        self.verification_keys = {
            str(key): bytes(value) for key, value in verification_keys.items()
        }
        self.policy = policy or HarnessPolicy()
        self._current_policy_version = self.policy.policy_version
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
            db.executescript("""
            CREATE TABLE IF NOT EXISTS harness_nonces(
              nonce TEXT PRIMARY KEY, lease_id TEXT NOT NULL,
              correlation_id TEXT NOT NULL, observed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS harness_decisions(
              decision_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              decision_id TEXT NOT NULL, correlation_id TEXT NOT NULL,
              lease_id TEXT NOT NULL UNIQUE, actor_id TEXT NOT NULL,
              action TEXT NOT NULL, privileged INTEGER NOT NULL,
              policy_version TEXT NOT NULL, status TEXT NOT NULL,
              reason TEXT NOT NULL, envelope_digest TEXT NOT NULL,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS harness_revocations(
              lease_id TEXT PRIMARY KEY, reason TEXT NOT NULL,
              revoked_by TEXT NOT NULL, revoked_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS harness_executions(
              lease_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL,
              consumed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS harness_events(
              event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              correlation_id TEXT, lease_id TEXT, event_type TEXT NOT NULL,
              details_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    @property
    def policy_version(self) -> str:
        return self._current_policy_version

    def set_policy_version(self, version: str) -> None:
        if not version.strip():
            raise ValueError("policy version cannot be empty")
        self._current_policy_version = version.strip()

    def _privileged(self, envelope: Mapping[str, Any]) -> bool:
        context = envelope.get("context")
        risk = context.get("risk") if isinstance(context, Mapping) else None
        external = context.get("external_execution") if isinstance(context, Mapping) else False
        return (
            envelope.get("action") in self.policy.privileged_actions
            or risk in {"consequential", "privileged"}
            or bool(external)
        )

    def _validate(
        self, envelope: Mapping[str, Any], now: datetime
    ) -> tuple[str | None, bool]:
        privileged = self._privileged(envelope)
        missing = sorted(REQUIRED_ENVELOPE_FIELDS - set(envelope))
        if missing:
            return f"missing fields: {', '.join(missing)}", privileged
        if envelope.get("tenant_id") != "personal":
            return "tenant is not authorized", privileged
        if envelope.get("schema_version") != "2.0.0":
            return "unsupported envelope schema", privileged
        if envelope.get("actor_id") not in self.policy.pilot_agents:
            return "actor is outside the Harness v0 pilot", privileged
        authorization = envelope.get("authorization")
        if not isinstance(authorization, Mapping):
            return "authorization must be an object", privileged
        if authorization.get("version") != AUTH_VERSION:
            return "unsupported authorization version", privileged
        if authorization.get("algorithm") != ALGORITHM:
            return "unsupported signature algorithm", privileged
        if authorization.get("decision_source") != "stable_spine":
            return "decision source is not Stable Spine", privileged
        if authorization.get("decision_state") != "AUTHORIZED":
            return "Stable Spine did not authorize execution", privileged
        if authorization.get("policy_version") != self.policy_version:
            return "policy version changed", privileged
        if not str(authorization.get("decision_id", "")).strip():
            return "Stable Spine decision id is required", privileged
        if privileged and not str(authorization.get("owner_approval_id", "")).strip():
            return "owner approval is required for privileged execution", privileged
        required_auth = {
            "key_id", "nonce", "lease_id", "issued_at", "expires_at",
            "lease_expires_at", "signature",
        }
        absent = sorted(name for name in required_auth if not authorization.get(name))
        if absent:
            return f"missing authorization fields: {', '.join(absent)}", privileged
        try:
            issued = _time(authorization["issued_at"])
            expires = _time(authorization["expires_at"])
            lease_expires = _time(authorization["lease_expires_at"])
        except (TypeError, ValueError):
            return "invalid authorization timestamp", privileged
        skew = timedelta(seconds=self.policy.clock_skew_seconds)
        if issued > now + skew:
            return "authorization was issued in the future", privileged
        if expires <= now or lease_expires <= now:
            return "authorization or lease expired", privileged
        if expires < issued or (expires - issued).total_seconds() > self.policy.max_ttl_seconds:
            return "authorization TTL exceeds policy", privileged
        if lease_expires > expires:
            return "lease outlives authorization", privileged
        key = self.verification_keys.get(str(authorization["key_id"]))
        if key is None:
            return "unknown signing key", privileged
        expected = hmac.new(key, _signed_bytes(envelope), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(authorization["signature"])):
            return "signature verification failed", privileged
        return None, privileged

    @staticmethod
    def _digest(envelope: Mapping[str, Any]) -> str:
        return hashlib.sha256(_signed_bytes(envelope)).hexdigest()

    def _event(
        self,
        db: sqlite3.Connection,
        envelope: Mapping[str, Any],
        event_type: str,
        details: Mapping[str, Any],
    ) -> None:
        authorization = envelope.get("authorization", {})
        db.execute(
            "INSERT INTO harness_events(correlation_id,lease_id,event_type,details_json,created_at) VALUES(?,?,?,?,?)",
            (
                envelope.get("correlation_id"),
                authorization.get("lease_id") if isinstance(authorization, Mapping) else None,
                event_type,
                json.dumps(dict(details), sort_keys=True, separators=(",", ":")),
                _iso(utcnow()),
            ),
        )

    def _deny(
        self, envelope: Mapping[str, Any], reason: str, privileged: bool
    ) -> HarnessDecision:
        try:
            with self.lock, self.connect() as db:
                self._event(db, envelope, "authorization.denied", {"reason": reason})
        except sqlite3.Error as exc:
            if privileged:
                raise HarnessUnavailable("privileged ledger unavailable") from exc
        authorization = envelope.get("authorization")
        lease_id = authorization.get("lease_id") if isinstance(authorization, Mapping) else None
        return HarnessDecision(False, "DENIED", reason, lease_id)

    def authorize(
        self, envelope: Mapping[str, Any], now: datetime | None = None
    ) -> HarnessDecision:
        current = (now or utcnow()).astimezone(timezone.utc)
        error, privileged = self._validate(envelope, current)
        if error:
            return self._deny(envelope, error, privileged)
        authorization = envelope["authorization"]
        try:
            with self.lock, self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM harness_revocations WHERE lease_id=?",
                    (authorization["lease_id"],),
                ).fetchone():
                    self._event(db, envelope, "authorization.denied", {"reason": "lease revoked"})
                    return HarnessDecision(False, "DENIED", "lease revoked", authorization["lease_id"])
                if db.execute(
                    "SELECT 1 FROM harness_nonces WHERE nonce=?",
                    (authorization["nonce"],),
                ).fetchone():
                    self._event(db, envelope, "authorization.denied", {"reason": "nonce replay"})
                    return HarnessDecision(False, "DENIED", "nonce replay", authorization["lease_id"])
                created = _iso(current)
                db.execute(
                    "INSERT INTO harness_nonces VALUES(?,?,?,?)",
                    (
                        authorization["nonce"], authorization["lease_id"],
                        envelope["correlation_id"], created,
                    ),
                )
                db.execute(
                    """INSERT INTO harness_decisions(
                       decision_id,correlation_id,lease_id,actor_id,action,privileged,
                       policy_version,status,reason,envelope_digest,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        authorization["decision_id"], envelope["correlation_id"],
                        authorization["lease_id"], envelope["actor_id"], envelope["action"],
                        int(privileged), self.policy_version, "AUTHORIZED",
                        "signed Stable Spine lease accepted", self._digest(envelope), created,
                    ),
                )
                self._event(db, envelope, "authorization.accepted", {
                    "policy_version": self.policy_version, "privileged": privileged
                })
            return HarnessDecision(
                True, "AUTHORIZED", "signed Stable Spine lease accepted",
                authorization["lease_id"],
            )
        except sqlite3.Error as exc:
            if privileged:
                raise HarnessUnavailable("privileged ledger unavailable") from exc
            if self.policy.advisory_fail_open_on_ledger_failure:
                return HarnessDecision(
                    True, "DEGRADED_ADVISORY",
                    "advisory tier permits operation without ledger",
                    authorization["lease_id"],
                )
            return HarnessDecision(False, "DENIED", "ledger unavailable", authorization["lease_id"])

    def revalidate_for_execution(
        self, envelope: Mapping[str, Any], now: datetime | None = None
    ) -> HarnessDecision:
        current = (now or utcnow()).astimezone(timezone.utc)
        error, privileged = self._validate(envelope, current)
        if error:
            return self._deny(envelope, error, privileged)
        authorization = envelope["authorization"]
        try:
            with self.lock, self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                lease_id = authorization["lease_id"]
                if db.execute(
                    "SELECT 1 FROM harness_revocations WHERE lease_id=?", (lease_id,)
                ).fetchone():
                    self._event(db, envelope, "execution.denied", {"reason": "lease revoked"})
                    return HarnessDecision(False, "DENIED", "lease revoked", lease_id)
                row = db.execute(
                    "SELECT status,policy_version,envelope_digest FROM harness_decisions WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
                if not row or row["status"] != "AUTHORIZED":
                    self._event(db, envelope, "execution.denied", {"reason": "lease was not authorized"})
                    return HarnessDecision(False, "DENIED", "lease was not authorized", lease_id)
                if row["policy_version"] != self.policy_version:
                    self._event(db, envelope, "execution.denied", {"reason": "policy version changed"})
                    return HarnessDecision(False, "DENIED", "policy version changed", lease_id)
                if row["envelope_digest"] != self._digest(envelope):
                    self._event(db, envelope, "execution.denied", {"reason": "envelope changed after authorization"})
                    return HarnessDecision(False, "DENIED", "envelope changed after authorization", lease_id)
                try:
                    db.execute(
                        "INSERT INTO harness_executions VALUES(?,?,?)",
                        (lease_id, envelope["correlation_id"], _iso(current)),
                    )
                except sqlite3.IntegrityError:
                    self._event(db, envelope, "execution.denied", {"reason": "lease replay"})
                    return HarnessDecision(False, "DENIED", "lease replay", lease_id)
                self._event(db, envelope, "execution.permitted", {
                    "policy_version": self.policy_version
                })
            return HarnessDecision(True, "EXECUTION_PERMITTED", "lease consumed", lease_id)
        except sqlite3.Error as exc:
            if privileged:
                raise HarnessUnavailable("privileged ledger unavailable") from exc
            return HarnessDecision(False, "DENIED", "ledger unavailable", authorization["lease_id"])

    def revoke(self, lease_id: str, *, reason: str, revoked_by: str) -> None:
        if not reason.strip() or not revoked_by.strip():
            raise ValueError("revocation reason and actor are required")
        try:
            with self.lock, self.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO harness_revocations VALUES(?,?,?,?)",
                    (lease_id, reason.strip(), revoked_by.strip(), _iso(utcnow())),
                )
                db.execute(
                    """INSERT INTO harness_events(
                       correlation_id,lease_id,event_type,details_json,created_at
                       ) VALUES(NULL,?,?,?,?)""",
                    (
                        lease_id, "lease.revoked",
                        json.dumps({"reason": reason, "revoked_by": revoked_by}, sort_keys=True),
                        _iso(utcnow()),
                    ),
                )
        except sqlite3.Error as exc:
            raise HarnessUnavailable("revocation ledger unavailable") from exc

    def reconstruct(self, correlation_id: str) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as db:
            decisions = [
                dict(row) for row in db.execute(
                    "SELECT * FROM harness_decisions WHERE correlation_id=? ORDER BY decision_sequence",
                    (correlation_id,),
                )
            ]
            events = [
                dict(row) for row in db.execute(
                    "SELECT * FROM harness_events WHERE correlation_id=? ORDER BY event_sequence",
                    (correlation_id,),
                )
            ]
            executions = [
                dict(row) for row in db.execute(
                    "SELECT * FROM harness_executions WHERE correlation_id=? ORDER BY consumed_at",
                    (correlation_id,),
                )
            ]
        return {"decisions": decisions, "events": events, "executions": executions}


class HarnessedExecutor:
    """The only supported adapter from an Action Envelope to an executor."""

    def __init__(self, harness: ActionHarness, executor: Callable[[Mapping[str, Any]], Any]):
        self._harness = harness
        self._executor = executor

    def execute(self, envelope: Mapping[str, Any], now: datetime | None = None) -> Any:
        decision = self._harness.revalidate_for_execution(envelope, now=now)
        if not decision.authorized:
            raise PermissionError(decision.reason)
        return self._executor(envelope)
