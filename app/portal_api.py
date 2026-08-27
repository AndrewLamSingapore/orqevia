from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .portal_integration import build_experiment_spec, serialize_record, validate_experiment_candidate, validate_experiment_spec

router = APIRouter(prefix="/api/integrations/portal", tags=["portal-integration"])


class CandidateEnvelope(BaseModel):
    candidate: dict


def _db_path() -> Path:
    from . import main as prime_main
    return prime_main.DB


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=20)
    c.row_factory = sqlite3.Row
    return c


def ensure_portal_schema() -> None:
    c = _connect()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS portal_experiments(
            candidate_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL UNIQUE,
            candidate_json TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            specialist TEXT,
            approval_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.commit()
    finally:
        c.close()


@router.post("/experiments")
def ingest_portal_experiment(envelope: CandidateEnvelope):
    try:
        candidate = validate_experiment_candidate(envelope.candidate)
        if candidate["status"] not in {"proposed", "accepted"}:
            raise ValueError("only proposed or accepted candidates may be ingested")
        spec = validate_experiment_spec(build_experiment_spec(candidate))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ensure_portal_schema()
    c = _connect()
    try:
        existing = c.execute("SELECT spec_json FROM portal_experiments WHERE candidate_id=?", (candidate["candidate_id"],)).fetchone()
        if existing:
            # Idempotent ingestion: a canonical Portal candidate ID maps to one PRIME spec.
            return {"candidate": candidate, "experiment_spec": json.loads(existing["spec_json"]), "idempotent": True}
        verification = spec.get("verification") or {}
        c.execute(
            "INSERT INTO portal_experiments(candidate_id,experiment_id,candidate_json,spec_json,specialist,approval_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (candidate["candidate_id"], spec["experiment_id"], json.dumps(candidate, ensure_ascii=False), json.dumps(spec, ensure_ascii=False), verification.get("specialist"), spec["approval_state"], spec["created_at"], spec["created_at"]),
        )
        c.commit()
    finally:
        c.close()
    return {"candidate": candidate, "experiment_spec": spec, "idempotent": False}


@router.get("/experiments/{candidate_id}")
def get_portal_experiment(candidate_id: str):
    ensure_portal_schema()
    c = _connect()
    try:
        row = c.execute("SELECT candidate_json,spec_json FROM portal_experiments WHERE candidate_id=?", (candidate_id,)).fetchone()
    finally:
        c.close()
    if not row:
        raise HTTPException(status_code=404, detail="experiment candidate not found")
    return {"candidate": json.loads(row["candidate_json"]), "experiment_spec": json.loads(row["spec_json"])}
