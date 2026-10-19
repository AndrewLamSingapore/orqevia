from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .observation_integration import build_portal_result, canonical_event, validate_velyqua_event
from .portal_api import ensure_portal_schema

router = APIRouter(prefix="/api/integrations", tags=["cross-project-evidence"])


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: dict


def _db_path() -> Path:
    from . import main as prime_main
    return prime_main.DB


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(), timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("ORQEVIA_INTEGRATION_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="ORQEVIA integration authentication is not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid integration token")


def ensure_velyqua_schema() -> None:
    ensure_portal_schema()
    connection = _connect()
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS velyqua_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL UNIQUE,
                event_hash TEXT NOT NULL,
                account_id TEXT NOT NULL,
                experiment_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_json TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS velyqua_events_experiment_order
                ON velyqua_events(experiment_id, sequence);

            CREATE TABLE IF NOT EXISTS experiment_evaluations(
                experiment_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                result_version INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portal_result_outbox(
                result_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                result_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                delivered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS portal_result_outbox_pending
                ON portal_result_outbox(delivered_at, created_at, result_id);
        """)
        connection.commit()
    finally:
        connection.close()


def _experiment_id(event: dict) -> str:
    return event["payload"]["experiment_id"]


def _load_candidate(connection: sqlite3.Connection, experiment_id: str) -> dict:
    row = connection.execute(
        "SELECT candidate_json FROM portal_experiments WHERE experiment_id=? LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="VELYQUA event does not match a persisted Portal experiment")
    return json.loads(row["candidate_json"])


def _evaluate(connection: sqlite3.Connection, experiment_id: str, candidate: dict) -> dict:
    rows = connection.execute(
        "SELECT event_json FROM velyqua_events WHERE experiment_id=? ORDER BY sequence ASC",
        (experiment_id,),
    ).fetchall()
    events = [validate_velyqua_event(json.loads(row["event_json"])) for row in rows]
    result = build_portal_result(candidate, events, updated_at=_now())
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    connection.execute(
        """INSERT INTO experiment_evaluations(experiment_id,candidate_id,result_version,result_json,updated_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(experiment_id) DO UPDATE SET
             candidate_id=excluded.candidate_id,
             result_version=excluded.result_version,
             result_json=excluded.result_json,
             updated_at=excluded.updated_at""",
        (experiment_id, result["candidate_id"], result["result_version"], encoded, result["updated_at"]),
    )
    connection.execute(
        """INSERT OR IGNORE INTO portal_result_outbox
             (result_id,experiment_id,result_json,attempts,last_error,created_at,updated_at,delivered_at)
           VALUES(?,?,?,0,NULL,?,?,NULL)""",
        (result["result_id"], experiment_id, encoded, result["updated_at"], result["updated_at"]),
    )
    return result


def _record_delivery_failure(result_id: str, message: str) -> None:
    connection = _connect()
    try:
        connection.execute(
            """UPDATE portal_result_outbox
               SET attempts=attempts+1,last_error=?,updated_at=?
               WHERE result_id=? AND delivered_at IS NULL""",
            (message[:500], _now(), result_id),
        )
        connection.commit()
    finally:
        connection.close()


def deliver_pending_portal_results(limit: int = 10) -> dict:
    url = os.environ.get("PORTAL_RESULT_URL", "").strip()
    token = os.environ.get("PORTAL_RESULT_TOKEN", "")
    if not url or not token:
        return {"status": "not_configured", "delivered": 0, "pending": True}
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return {"status": "unsafe_url", "delivered": 0, "pending": True}

    ensure_velyqua_schema()
    connection = _connect()
    try:
        rows = connection.execute(
            """SELECT result_id,result_json FROM portal_result_outbox
               WHERE delivered_at IS NULL ORDER BY created_at ASC,result_id ASC LIMIT ?""",
            (max(1, min(50, int(limit))),),
        ).fetchall()
    finally:
        connection.close()

    delivered = 0
    for row in rows:
        request = urllib.request.Request(
            url,
            data=json.dumps({"result": json.loads(row["result_json"])}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = json.load(response)
            if body.get("accepted") is not True or body.get("result_id") != row["result_id"]:
                raise ValueError("Portal acknowledgement did not match the result")
            connection = _connect()
            try:
                connection.execute(
                    """UPDATE portal_result_outbox
                       SET delivered_at=?,updated_at=?,last_error=NULL
                       WHERE result_id=? AND delivered_at IS NULL""",
                    (_now(), _now(), row["result_id"]),
                )
                connection.commit()
            finally:
                connection.close()
            delivered += 1
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            _record_delivery_failure(row["result_id"], str(exc))
            return {"status": "delivery_failed", "delivered": delivered, "pending": True}
    return {"status": "delivered" if rows else "idle", "delivered": delivered, "pending": False}


@router.post("/velyqua/events")
def ingest_velyqua_event(envelope: EventEnvelope, _: None = Depends(_require_token)):
    try:
        event = validate_velyqua_event(envelope.event)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ensure_velyqua_schema()
    experiment_id = _experiment_id(event)
    encoded = canonical_event(event)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    connection = _connect()
    idempotent = False
    try:
        candidate = _load_candidate(connection, experiment_id)
        if event["payload"].get("candidate_id") not in {None, candidate["candidate_id"]}:
            raise HTTPException(status_code=409, detail="event candidate_id does not match the Portal candidate")
        account = connection.execute(
            "SELECT account_id FROM velyqua_events WHERE experiment_id=? LIMIT 1", (experiment_id,)
        ).fetchone()
        if account and account["account_id"] != event["account_id"]:
            raise HTTPException(status_code=409, detail="experiment evidence is already owned by another account")
        existing = connection.execute(
            "SELECT event_hash FROM velyqua_events WHERE operation_id=?", (event["operation_id"],)
        ).fetchone()
        if existing:
            if not hmac.compare_digest(existing["event_hash"], digest):
                raise HTTPException(status_code=409, detail="operation_id replay contains conflicting data")
            idempotent = True
        else:
            connection.execute(
                """INSERT INTO velyqua_events
                     (operation_id,event_hash,account_id,experiment_id,event_type,event_json,received_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    event["operation_id"], digest, event["account_id"], experiment_id,
                    event["event_type"], encoded, _now(),
                ),
            )
        result = _evaluate(connection, experiment_id, candidate)
        connection.commit()
    except HTTPException:
        connection.rollback()
        raise
    except ValueError as exc:
        connection.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        connection.close()

    delivery = deliver_pending_portal_results()
    return {
        "accepted": True,
        "operation_id": event["operation_id"],
        "idempotent": idempotent,
        "evaluation": result,
        "portal_delivery": delivery,
    }


@router.get("/velyqua/evaluations/{experiment_id}")
def get_velyqua_evaluation(experiment_id: str, _: None = Depends(_require_token)):
    ensure_velyqua_schema()
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT result_json FROM experiment_evaluations WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
    finally:
        connection.close()
    if not row:
        raise HTTPException(status_code=404, detail="experiment evaluation not found")
    return {"result": json.loads(row["result_json"])}


@router.post("/portal/results/flush")
def flush_portal_results(_: None = Depends(_require_token)):
    return deliver_pending_portal_results(limit=50)
