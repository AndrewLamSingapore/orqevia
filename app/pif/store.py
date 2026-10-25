"""Namespaced probabilistic artifacts in ORQEVIA's existing model registry DB."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .core import MarkovModel, canonical, digest, identifier


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PIFStore:
    def __init__(self, path: str | Path | None = None):
        default = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "model-registry.db"
        self.path = Path(path or os.getenv("ORQEVIA_MODEL_REGISTRY_DB") or default)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pif_models(
                    tenant TEXT NOT NULL, model_id TEXT NOT NULL, version TEXT NOT NULL,
                    artifact_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(tenant,model_id,version));
                CREATE TABLE IF NOT EXISTS pif_active(
                    tenant TEXT NOT NULL, model_id TEXT NOT NULL, version TEXT NOT NULL,
                    PRIMARY KEY(tenant,model_id),
                    FOREIGN KEY(tenant,model_id,version) REFERENCES pif_models(tenant,model_id,version));
                CREATE TABLE IF NOT EXISTS pif_events(
                    event_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, model_id TEXT NOT NULL,
                    version TEXT NOT NULL, event TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pif_predictions(
                    trace_id TEXT NOT NULL, tenant TEXT NOT NULL, result_json TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant,trace_id));
            """)
            with db:
                yield db
        finally:
            db.close()

    def save_model(
        self, tenant: str, model_id: str, model: MarkovModel, metadata: dict[str, Any], *, select: bool = True
    ) -> str:
        identifier(tenant)
        identifier(model_id)
        artifact = canonical(model.as_dict())
        meta = canonical(metadata)
        version = model.version
        with self.connect() as db:
            prior = db.execute(
                "SELECT artifact_json FROM pif_models WHERE tenant=? AND model_id=? AND version=?",
                (tenant, model_id, version),
            ).fetchone()
            if prior and prior["artifact_json"] != artifact:
                raise ValueError("model digest collision or corruption")
            if not prior:
                db.execute(
                    "INSERT INTO pif_models VALUES(?,?,?,?,?,?)", (tenant, model_id, version, artifact, meta, utcnow())
                )
                self._event(db, tenant, model_id, version, "fitted_shadow")
            if select:
                self._select(db, tenant, model_id, version, "selected_shadow")
        return version

    @staticmethod
    def _event(db: sqlite3.Connection, tenant: str, model_id: str, version: str, event: str) -> None:
        db.execute(
            "INSERT INTO pif_events VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), tenant, model_id, version, event, utcnow()),
        )

    def _select(self, db: sqlite3.Connection, tenant: str, model_id: str, version: str, event: str) -> None:
        if not db.execute(
            "SELECT 1 FROM pif_models WHERE tenant=? AND model_id=? AND version=?", (tenant, model_id, version)
        ).fetchone():
            raise KeyError("model version unavailable in tenant scope")
        db.execute(
            "INSERT INTO pif_active VALUES(?,?,?) ON CONFLICT(tenant,model_id) DO UPDATE SET version=excluded.version",
            (tenant, model_id, version),
        )
        self._event(db, tenant, model_id, version, event)

    def select_version(self, tenant: str, model_id: str, version: str) -> None:
        """Reversible shadow-model selection; never registers an execution route."""
        identifier(tenant)
        identifier(model_id)
        identifier(version)
        with self.connect() as db:
            self._select(db, tenant, model_id, version, "rollback_or_selection_shadow")

    def load_model(self, tenant: str, model_id: str, version: str | None = None) -> tuple[MarkovModel, dict[str, Any]]:
        identifier(tenant)
        identifier(model_id)
        if version is not None:
            identifier(version)
        with self.connect() as db:
            if version is None:
                active = db.execute(
                    "SELECT version FROM pif_active WHERE tenant=? AND model_id=?", (tenant, model_id)
                ).fetchone()
                if not active:
                    raise KeyError("no model selected")
                version = active["version"]
            row = db.execute(
                "SELECT artifact_json,metadata_json FROM pif_models WHERE tenant=? AND model_id=? AND version=?",
                (tenant, model_id, version),
            ).fetchone()
        if not row:
            raise KeyError("model unavailable")
        try:
            artifact = json.loads(row["artifact_json"])
            if digest(artifact) != version:
                raise ValueError("model artifact integrity mismatch")
            model = MarkovModel.from_dict(artifact)
            metadata = json.loads(row["metadata_json"])
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid model artifact or metadata") from exc
        return model, metadata

    def record_prediction(self, tenant: str, result: dict[str, Any]) -> None:
        identifier(tenant)
        payload = canonical(result)
        with self.connect() as db:
            db.execute(
                "INSERT INTO pif_predictions VALUES(?,?,?,?,?)",
                (result["trace_id"], tenant, payload, digest(result), utcnow()),
            )

    def prediction(self, tenant: str, trace_id: str) -> dict[str, Any]:
        identifier(tenant)
        identifier(trace_id)
        with self.connect() as db:
            row = db.execute(
                "SELECT result_json,result_sha256 FROM pif_predictions WHERE tenant=? AND trace_id=?",
                (tenant, trace_id),
            ).fetchone()
        if not row:
            raise KeyError("prediction unavailable")
        result = json.loads(row["result_json"])
        if digest(result) != row["result_sha256"]:
            raise ValueError("prediction evidence integrity mismatch")
        return result
