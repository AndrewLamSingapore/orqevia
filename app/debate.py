"""Deterministic, evidence-preserving debate and judge resolution.

The service accepts independently produced positions. It never invents a
position or treats a model answer as execution evidence. A resolution is
retained with the original positions, disagreements, objections and escalation
reasons.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .agent_registry import RegistryError, canonical_agent_id


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Position:
    agent_id: str
    proposition: str
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 0.5
    assumptions: tuple[str, ...] = ()
    objections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            canonical_agent_id(self.agent_id)
        except RegistryError:
            raise ValueError("position agent is not registered") from None
        if not isinstance(self.proposition, str) or not self.proposition.strip():
            raise ValueError("position proposition is required")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
            raise ValueError("position confidence must be between zero and one")
        for name, values in (("evidence_refs", self.evidence_refs), ("assumptions", self.assumptions), ("objections", self.objections)):
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-empty strings")

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("evidence_refs", "assumptions", "objections"):
            value[name] = list(getattr(self, name))
        return value


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def resolve_debate(
    question: str,
    positions: list[Position],
    *,
    judge_agent: str = "a26",
    consensus_threshold: float = 0.66,
) -> dict[str, Any]:
    if not isinstance(question, str) or len(question.strip()) < 3:
        raise ValueError("debate question is required")
    if len(positions) < 2:
        raise ValueError("at least two independent positions are required")
    if len({position.agent_id for position in positions}) != len(positions):
        raise ValueError("each agent may contribute only one position")
    try:
        judge = canonical_agent_id(judge_agent)
    except RegistryError:
        raise ValueError("judge agent is not registered") from None
    if judge in {position.agent_id for position in positions}:
        raise ValueError("judge must be independent of the positions")
    if isinstance(consensus_threshold, bool) or not isinstance(consensus_threshold, (int, float)) or not 0.5 <= consensus_threshold <= 1:
        raise ValueError("consensus threshold must be between 0.5 and 1")

    groups: dict[str, list[Position]] = {}
    for position in positions:
        groups.setdefault(_normalize(position.proposition), []).append(position)
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    winner_key, winner_positions = ranked[0]
    tie = len(ranked) > 1 and len(ranked[1][1]) == len(winner_positions)
    consensus_share = len(winner_positions) / len(positions)
    objections = sorted(
        {
            objection
            for position in positions
            for objection in position.objections
        }
    )
    missing_evidence = sorted(
        position.agent_id for position in positions if not position.evidence_refs
    )
    minority = [
        position
        for position in positions
        if _normalize(position.proposition) != winner_key
    ]
    reasons: list[str] = []
    if tie:
        reasons.append("no_unique_majority")
    if missing_evidence:
        reasons.append("missing_evidence:" + ",".join(missing_evidence))
    if minority:
        reasons.append("minority_positions:" + ",".join(position.agent_id for position in minority))
    if objections:
        reasons.append("explicit_objections")

    winner_has_evidence = all(position.evidence_refs for position in winner_positions)
    if not winner_has_evidence:
        decision = "NEEDS_EVIDENCE"
    elif tie:
        decision = "ESCALATE"
    elif consensus_share >= consensus_threshold and not objections:
        decision = "RESOLVED"
    else:
        decision = "ESCALATE"
    confidence = round(
        min(1.0, consensus_share * mean(position.confidence for position in winner_positions)),
        4,
    )
    return {
        "schema_version": "orqevia.debate-resolution.v1",
        "debate_id": str(uuid.uuid4()),
        "question": question.strip(),
        "judge_agent": judge,
        "decision": decision,
        "selected_proposition": winner_positions[0].proposition,
        "consensus_share": round(consensus_share, 4),
        "consensus_threshold": consensus_threshold,
        "confidence": confidence,
        "reasons": reasons,
        "objections": objections,
        "missing_evidence_agent_ids": missing_evidence,
        "minority_positions": [position.as_dict() for position in minority],
        "evidence_refs": sorted({ref for position in winner_positions for ref in position.evidence_refs}),
        "positions": [position.as_dict() for position in positions],
        "escalation": {
            "required": decision == "ESCALATE",
            "target": "owner_or_independent_review" if decision == "ESCALATE" else "none",
        },
        "created_at": utcnow(),
    }


class DebateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        default = Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "debates.db"
        self.path = Path(path or os.getenv("ORQEVIA_DEBATE_DB") or default)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS debates(
                  debate_id TEXT PRIMARY KEY,
                  question TEXT NOT NULL,
                  judge_agent TEXT NOT NULL,
                  decision TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS debate_created_idx ON debates(created_at);
                """
            )
            db.commit()

    def record(self, resolution: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as db:
            db.execute(
                "INSERT INTO debates VALUES(?,?,?,?,?,?)",
                (
                    resolution["debate_id"],
                    resolution["question"],
                    resolution["judge_agent"],
                    resolution["decision"],
                    json.dumps(resolution, sort_keys=True, allow_nan=False),
                    resolution["created_at"],
                ),
            )
            db.commit()
        return resolution

    def get(self, debate_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT payload_json FROM debates WHERE debate_id=?", (debate_id,)).fetchone()
        if not row:
            raise KeyError(debate_id)
        return json.loads(row["payload_json"])

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload_json FROM debates ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]
