"""Public-safe release gate observability.

Stores only bounded aggregate evaluator metadata keyed by ORQEVIA trace ID. No
prompt, answer, rationale, claim text, evidence text, credentials or endpoints
are persisted here. The sidecar is deliberately independent from the authority
ledger so evaluation observability cannot mutate authorization decisions.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLIC_BLOCKING_METRICS = frozenset({
    "source_coverage",
    "supported_claims",
    "contradiction_resistance",
    "uncertainty_calibration",
    "required_evidence",
    "policy_conformance",
    "task_success",
})
PUBLIC_GATE_FIELDS = frozenset({
    "decision",
    "score",
    "blocking_metrics",
    "evidence_gap_count",
    "unsupported_claim_count",
    "contradiction_count",
    "evaluator_valid",
    "evaluation_version",
})


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_count(value: Any) -> int:
    if isinstance(value, list):
        value = len(value)
    try:
        return max(0, min(int(value), 999))
    except (TypeError, ValueError):
        return 0


def _bounded_score(value: Any) -> float:
    try:
        return round(max(0.0, min(float(value), 1.0)), 4)
    except (TypeError, ValueError):
        return 0.0


class ReleaseGateLedger:
    """Durable, allowlisted release/hold telemetry keyed by trace ID."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            data = Path(os.getenv("ORQEVIA_DATA_DIR", "/data").strip() or "/data")
            try:
                data.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                data = Path("/tmp/prime")
                data.mkdir(parents=True, exist_ok=True)
            db_path = data / "release-gate.db"
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
            CREATE TABLE IF NOT EXISTS release_gate_events(
              trace_id TEXT PRIMARY KEY,
              recorded_at TEXT NOT NULL,
              decision TEXT NOT NULL,
              score REAL NOT NULL,
              blocking_metrics TEXT NOT NULL,
              evidence_gap_count INTEGER NOT NULL,
              unsupported_claim_count INTEGER NOT NULL,
              contradiction_count INTEGER NOT NULL,
              evaluator_valid INTEGER NOT NULL,
              evaluation_version TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_release_gate_time
              ON release_gate_events(recorded_at DESC);
            """)

    @staticmethod
    def sanitize_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
        released = evaluation.get("released") is True
        raw_blocking = evaluation.get("blocking_metrics", [])
        blocking = sorted({
            str(item) for item in raw_blocking
            if isinstance(item, str) and item in PUBLIC_BLOCKING_METRICS
        }) if isinstance(raw_blocking, list) else []
        version = str(evaluation.get("version") or "unknown")[:24]
        return {
            "decision": "released" if released else "withheld",
            "score": _bounded_score(evaluation.get("score")),
            "blocking_metrics": blocking,
            "evidence_gap_count": _bounded_count(evaluation.get("evidence_gaps", [])),
            "unsupported_claim_count": _bounded_count(evaluation.get("unsupported_claims", [])),
            "contradiction_count": _bounded_count(evaluation.get("contradictions", [])),
            "evaluator_valid": evaluation.get("parse_error") in (None, ""),
            "evaluation_version": version,
        }

    def record(self, *, trace_id: str, evaluation: dict[str, Any]) -> dict[str, Any]:
        trace = (trace_id or "").strip()[:120]
        if not trace:
            raise ValueError("trace_id is required")
        public = self.sanitize_evaluation(evaluation)
        with self.lock, self.connect() as db:
            db.execute(
                """INSERT INTO release_gate_events
                (trace_id,recorded_at,decision,score,blocking_metrics,evidence_gap_count,
                 unsupported_claim_count,contradiction_count,evaluator_valid,evaluation_version)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trace_id) DO UPDATE SET
                  recorded_at=excluded.recorded_at,
                  decision=excluded.decision,
                  score=excluded.score,
                  blocking_metrics=excluded.blocking_metrics,
                  evidence_gap_count=excluded.evidence_gap_count,
                  unsupported_claim_count=excluded.unsupported_claim_count,
                  contradiction_count=excluded.contradiction_count,
                  evaluator_valid=excluded.evaluator_valid,
                  evaluation_version=excluded.evaluation_version""",
                (
                    trace, utcnow(), public["decision"], public["score"],
                    json.dumps(public["blocking_metrics"], separators=(",", ":")),
                    public["evidence_gap_count"], public["unsupported_claim_count"],
                    public["contradiction_count"], int(public["evaluator_valid"]),
                    public["evaluation_version"],
                ),
            )
        return public

    def for_traces(self, trace_ids: list[str]) -> dict[str, dict[str, Any]]:
        traces = list(dict.fromkeys((str(item).strip()[:120] for item in trace_ids if str(item).strip())))[:500]
        if not traces:
            return {}
        placeholders = ",".join("?" for _ in traces)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM release_gate_events WHERE trace_id IN ({placeholders})",
                traces,
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                blocking = json.loads(row["blocking_metrics"])
            except (TypeError, ValueError, json.JSONDecodeError):
                blocking = []
            public = {
                "decision": row["decision"] if row["decision"] in {"released", "withheld"} else "withheld",
                "score": _bounded_score(row["score"]),
                "blocking_metrics": [item for item in blocking if item in PUBLIC_BLOCKING_METRICS] if isinstance(blocking, list) else [],
                "evidence_gap_count": _bounded_count(row["evidence_gap_count"]),
                "unsupported_claim_count": _bounded_count(row["unsupported_claim_count"]),
                "contradiction_count": _bounded_count(row["contradiction_count"]),
                "evaluator_valid": bool(row["evaluator_valid"]),
                "evaluation_version": str(row["evaluation_version"] or "unknown")[:24],
            }
            result[row["trace_id"]] = public
        return result

    def withheld_today(self) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM release_gate_events WHERE recorded_at>=? AND decision='withheld'",
                (start,),
            ).fetchone()
        return int(row[0] or 0)

    def enrich_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Attach only allowlisted aggregate gate metadata to terminal reasoning events."""
        result = dict(snapshot)
        events = [dict(event) for event in snapshot.get("events", []) if isinstance(event, dict)]
        gates = self.for_traces([str(event.get("trace_id") or "") for event in events])
        for event in events:
            if event.get("stage") == "reasoning" and event.get("status") in {"completed", "withheld"}:
                gate = gates.get(str(event.get("trace_id") or ""))
                if gate:
                    event["gate"] = {key: gate[key] for key in PUBLIC_GATE_FIELDS}
        summary = dict(snapshot.get("summary") or {})
        summary["withheld_executions_today"] = self.withheld_today()
        result["events"] = events
        result["summary"] = summary
        result["boundary"] = "sanitized runtime authority and aggregate release-gate metadata only; no prompts, results, rationale, claim text, credentials or endpoints"
        return result


release_gates = ReleaseGateLedger()
