"""First-class model registration, evaluation, promotion and rollback.

The registry is deliberately separate from the compute queue. A registered or
evaluated model is not routable until it is explicitly approved, activated and
assigned to an agent. Every state transition is append-only evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_registry import RegistryError, canonical_agent_id


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
STATES = {"registered", "evaluated", "approved", "active", "deprecated", "retired"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ModelVersion:
    model_id: str
    version: str
    provider: str
    model_name: str
    location: str
    context_tokens: int
    output_tokens: int
    capabilities: tuple[str, ...]
    artifact_sha256: str
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("model_id", self.model_id), ("version", self.version)):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"{name} must be a stable identifier")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name is required")
        if self.location not in {"local", "cloud"}:
            raise ValueError("location must be local or cloud")
        for name, value in (("context_tokens", self.context_tokens), ("output_tokens", self.output_tokens)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.output_tokens >= self.context_tokens:
            raise ValueError("output_tokens must be smaller than context_tokens")
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise ValueError("at least one capability is required")
        if len(set(self.capabilities)) != len(self.capabilities) or not all(
            isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in self.capabilities
        ):
            raise ValueError("capabilities must be unique stable identifiers")
        if not isinstance(self.artifact_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.artifact_sha256):
            raise ValueError("artifact_sha256 must be a SHA-256 digest")
        if self.source_url is not None:
            if not isinstance(self.source_url, str) or not self.source_url.startswith("https://"):
                raise ValueError("source_url must use HTTPS")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        json.dumps(self.metadata, allow_nan=False)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        return value


class ModelRegistryStore:
    def __init__(self, path: str | Path | None = None) -> None:
        default = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "model-registry.db"
        self.path = Path(path or os.getenv("ORQEVIA_MODEL_REGISTRY_DB") or default)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_versions(
                  model_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  provider TEXT NOT NULL,
                  model_name TEXT NOT NULL,
                  location TEXT NOT NULL CHECK(location IN ('local','cloud')),
                  context_tokens INTEGER NOT NULL,
                  output_tokens INTEGER NOT NULL,
                  capabilities_json TEXT NOT NULL,
                  artifact_sha256 TEXT NOT NULL,
                  source_url TEXT,
                  metadata_json TEXT NOT NULL,
                  state TEXT NOT NULL,
                  evaluation_json TEXT,
                  compatibility_json TEXT,
                  created_by TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(model_id,version)
                );
                CREATE TABLE IF NOT EXISTS model_events(
                  event_id TEXT PRIMARY KEY,
                  model_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  event TEXT NOT NULL,
                  from_state TEXT,
                  to_state TEXT,
                  actor TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  details_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(model_id,version) REFERENCES model_versions(model_id,version)
                );
                CREATE TABLE IF NOT EXISTS model_assignments(
                  agent_id TEXT PRIMARY KEY,
                  model_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  assigned_by TEXT NOT NULL,
                  assigned_at TEXT NOT NULL,
                  FOREIGN KEY(model_id,version) REFERENCES model_versions(model_id,version)
                );
                """
            )
            db.commit()

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        model_id: str,
        version: str,
        event: str,
        *,
        actor: str,
        reason: str,
        from_state: str | None = None,
        to_state: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO model_events VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                model_id,
                version,
                event,
                from_state,
                to_state,
                actor,
                reason[:1000],
                json.dumps(details or {}, sort_keys=True, allow_nan=False),
                utcnow(),
            ),
        )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["capabilities"] = json.loads(value.pop("capabilities_json"))
        value["metadata"] = json.loads(value.pop("metadata_json"))
        for key in ("evaluation_json", "compatibility_json"):
            raw = value.pop(key, None)
            value[key.removesuffix("_json")] = json.loads(raw) if raw else None
        return value

    def register(self, version: ModelVersion, *, actor: str) -> dict[str, Any]:
        now = utcnow()
        payload = version.as_dict()
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM model_versions WHERE model_id=? AND version=?",
                (version.model_id, version.version),
            ).fetchone()
            if existing:
                current = self._decode(existing)
                comparable = {
                    key: payload[key]
                    for key in (
                        "provider",
                        "model_name",
                        "location",
                        "context_tokens",
                        "output_tokens",
                        "capabilities",
                        "artifact_sha256",
                        "source_url",
                        "metadata",
                    )
                }
                if all(current[key] == value for key, value in comparable.items()):
                    return current
                raise ValueError("model version already exists with different metadata")
            db.execute(
                """INSERT INTO model_versions
                (model_id,version,provider,model_name,location,context_tokens,output_tokens,
                 capabilities_json,artifact_sha256,source_url,metadata_json,state,
                 evaluation_json,compatibility_json,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,'registered',NULL,NULL,?,?,?)""",
                (
                    version.model_id,
                    version.version,
                    version.provider,
                    version.model_name,
                    version.location,
                    version.context_tokens,
                    version.output_tokens,
                    json.dumps(list(version.capabilities), sort_keys=True),
                    version.artifact_sha256.lower(),
                    version.source_url,
                    json.dumps(version.metadata, sort_keys=True, allow_nan=False),
                    actor,
                    now,
                    now,
                ),
            )
            self._event(
                db,
                version.model_id,
                version.version,
                "registered",
                actor=actor,
                reason="model metadata registered",
                to_state="registered",
                details={"artifact_sha256": version.artifact_sha256.lower()},
            )
            db.commit()
        return self.get(version.model_id, version.version)

    def get(self, model_id: str, version: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM model_versions WHERE model_id=? AND version=?",
                (model_id, version),
            ).fetchone()
        if not row:
            raise KeyError(f"{model_id}:{version}")
        return self._decode(row)

    def list_models(self, *, model_id: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM model_versions"
        clauses: list[str] = []
        args: list[Any] = []
        if model_id:
            clauses.append("model_id=?")
            args.append(model_id)
        if state:
            if state not in STATES:
                raise ValueError("unknown model state")
            clauses.append("state=?")
            args.append(state)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY model_id,created_at DESC"
        with self.connect() as db:
            return [self._decode(row) for row in db.execute(sql, args).fetchall()]

    def evaluate(self, model_id: str, version: str, evaluation: dict[str, Any], *, actor: str) -> dict[str, Any]:
        record = self.get(model_id, version)
        if record["state"] not in {"registered", "evaluated"}:
            raise ValueError("model must be registered or evaluated before evaluation")
        status = str(evaluation.get("status", "")).upper()
        if status not in {"PASS", "FAIL"}:
            raise ValueError("evaluation status must be PASS or FAIL")
        evidence = evaluation.get("evidence_ref")
        checks = evaluation.get("checks")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("evaluation evidence_ref is required")
        if not isinstance(checks, (list, dict)) or not checks:
            raise ValueError("evaluation checks are required")
        json.dumps(evaluation, allow_nan=False)
        next_state = "evaluated" if status == "PASS" else "registered"
        with self.connect() as db:
            db.execute(
                "UPDATE model_versions SET state=?,evaluation_json=?,updated_at=? WHERE model_id=? AND version=?",
                (next_state, json.dumps(evaluation, sort_keys=True), utcnow(), model_id, version),
            )
            self._event(
                db,
                model_id,
                version,
                "evaluated",
                actor=actor,
                reason=f"evaluation {status}",
                from_state=record["state"],
                to_state=next_state,
                details={"status": status, "evidence_ref": evidence},
            )
            db.commit()
        return self.get(model_id, version)

    def approve(
        self,
        model_id: str,
        version: str,
        compatibility: dict[str, Any],
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        record = self.get(model_id, version)
        if record["state"] != "evaluated" or (record["evaluation"] or {}).get("status") != "PASS":
            raise ValueError("a passing evaluation is required before approval")
        if compatibility.get("compatible") is not True:
            raise ValueError("compatibility must be proven before approval")
        if not isinstance(compatibility.get("evidence_ref"), str) or not compatibility["evidence_ref"].strip():
            raise ValueError("compatibility evidence_ref is required")
        with self.connect() as db:
            db.execute(
                "UPDATE model_versions SET state='approved',compatibility_json=?,updated_at=? WHERE model_id=? AND version=?",
                (json.dumps(compatibility, sort_keys=True), utcnow(), model_id, version),
            )
            self._event(
                db,
                model_id,
                version,
                "approved",
                actor=actor,
                reason=reason,
                from_state="evaluated",
                to_state="approved",
                details={"compatibility": compatibility},
            )
            db.commit()
        return self.get(model_id, version)

    def activate(self, model_id: str, version: str, *, actor: str, reason: str) -> dict[str, Any]:
        record = self.get(model_id, version)
        if record["state"] != "approved":
            raise ValueError("model must be approved before activation")
        with self.connect() as db:
            active = db.execute(
                "SELECT version FROM model_versions WHERE model_id=? AND state='active'",
                (model_id,),
            ).fetchall()
            for row in active:
                if row["version"] != version:
                    db.execute(
                        "UPDATE model_versions SET state='deprecated',updated_at=? WHERE model_id=? AND version=?",
                        (utcnow(), model_id, row["version"]),
                    )
                    self._event(
                        db,
                        model_id,
                        row["version"],
                        "deprecated",
                        actor=actor,
                        reason="superseded by activation",
                        from_state="active",
                        to_state="deprecated",
                        details={"replacement": version},
                    )
            db.execute(
                "UPDATE model_versions SET state='active',updated_at=? WHERE model_id=? AND version=?",
                (utcnow(), model_id, version),
            )
            self._event(
                db,
                model_id,
                version,
                "activated",
                actor=actor,
                reason=reason,
                from_state="approved",
                to_state="active",
                details={"previous_active": [row["version"] for row in active]},
            )
            db.commit()
        return self.get(model_id, version)

    def assign(self, agent_id: str, model_id: str, version: str, *, actor: str) -> dict[str, Any]:
        try:
            canonical = canonical_agent_id(agent_id)
        except RegistryError:
            raise ValueError("unknown agent") from None
        record = self.get(model_id, version)
        if record["state"] != "active":
            raise ValueError("only an active model can be assigned")
        with self.connect() as db:
            db.execute(
                """INSERT INTO model_assignments(agent_id,model_id,version,assigned_by,assigned_at)
                VALUES(?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET
                model_id=excluded.model_id,version=excluded.version,
                assigned_by=excluded.assigned_by,assigned_at=excluded.assigned_at""",
                (canonical, model_id, version, actor, utcnow()),
            )
            self._event(
                db,
                model_id,
                version,
                "assigned",
                actor=actor,
                reason="agent assignment",
                to_state="active",
                details={"agent_id": canonical},
            )
            db.commit()
        return {"agent_id": canonical, "model_id": model_id, "version": version}

    def rollback(self, model_id: str, target_version: str, *, actor: str, reason: str) -> dict[str, Any]:
        target = self.get(model_id, target_version)
        if target["state"] not in {"approved", "deprecated", "active"}:
            raise ValueError("rollback target must be approved, deprecated or active")
        with self.connect() as db:
            current = db.execute(
                "SELECT version FROM model_versions WHERE model_id=? AND state='active'",
                (model_id,),
            ).fetchall()
            if not current:
                raise ValueError("model has no active version to roll back")
            for row in current:
                if row["version"] != target_version:
                    db.execute(
                        "UPDATE model_versions SET state='deprecated',updated_at=? WHERE model_id=? AND version=?",
                        (utcnow(), model_id, row["version"]),
                    )
            db.execute(
                "UPDATE model_versions SET state='active',updated_at=? WHERE model_id=? AND version=?",
                (utcnow(), model_id, target_version),
            )
            db.execute(
                "UPDATE model_assignments SET version=?,assigned_at=?,assigned_by=? WHERE model_id=?",
                (target_version, utcnow(), actor, model_id),
            )
            self._event(
                db,
                model_id,
                target_version,
                "rolled_back",
                actor=actor,
                reason=reason,
                from_state=target["state"],
                to_state="active",
                details={"previous_active": [row["version"] for row in current]},
            )
            db.commit()
        return self.get(model_id, target_version)

    def history(self, model_id: str, version: str) -> dict[str, Any]:
        self.get(model_id, version)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM model_events WHERE model_id=? AND version=? ORDER BY created_at",
                (model_id, version),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            events.append(item)
        return {"model_id": model_id, "version": version, "events": events}

    def health(self) -> dict[str, Any]:
        with self.connect() as db:
            states = {
                row["state"]: row["n"]
                for row in db.execute(
                    "SELECT state,COUNT(*) AS n FROM model_versions GROUP BY state"
                ).fetchall()
            }
            assignments = db.execute("SELECT COUNT(*) FROM model_assignments").fetchone()[0]
            events = db.execute("SELECT COUNT(*) FROM model_events").fetchone()[0]
        return {
            "database": str(self.path),
            "states": states,
            "models": sum(states.values()),
            "assignments": assignments,
            "events": events,
        }
