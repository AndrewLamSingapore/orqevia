"""Internal, non-financial contribution ledger.

Records bounded contribution counts (sweep rounds, coaching cohorts, reported
findings). Explicitly NOT a token: no monetary value, no transfer, no
authority. A real tokenized reward system remains an Owner product decision.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

_KIND = re.compile(r"[a-z0-9_.-]{1,48}")
_CONTRIBUTOR = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS contributions(
  id TEXT PRIMARY KEY, contributor TEXT NOT NULL, kind TEXT NOT NULL,
  units INTEGER NOT NULL, detail_json TEXT NOT NULL,
  source_revision TEXT NOT NULL, recorded_at TEXT NOT NULL)
"""


class ContributionLedger:
    """Durable local ledger; units are internal merit counts only."""

    def __init__(self, path):
        self.path = str(path)
        with self._connect() as db:
            db.execute(_SCHEMA)
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def record(self, contributor, kind, units=1, detail=None, source_revision="UNKNOWN"):
        if not _CONTRIBUTOR.fullmatch(contributor) or not _KIND.fullmatch(kind):
            raise ValueError("bounded contributor and kind required")
        if not isinstance(units, int) or not 1 <= units <= 1000000:
            raise ValueError("bounded units required")
        row_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO contributions VALUES(?,?,?,?,?,?,?)",
                (row_id, contributor, kind, units,
                 json.dumps(detail or {}, sort_keys=True), source_revision, now),
            )
            db.commit()
        return row_id

    def totals(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT contributor, SUM(units) AS units FROM contributions GROUP BY contributor ORDER BY units DESC")]

    def recent(self, limit=20):
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM contributions ORDER BY recorded_at DESC LIMIT ?", (limit,))]
