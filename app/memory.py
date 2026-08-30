"""JARVIS cognitive memory v1.

Operational telemetry does not belong here. This store accepts notable episodes
and promotes only explicitly durable, keyed items into update-in-place memory.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DURABLE_KINDS = {"semantic", "preference", "entity", "project", "decision", "task"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("PRIME_MEMORY_DB") or "/tmp/jarvis-memory.db"
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript("""
            create table if not exists episodic_memory (
              episode_id text primary key,
              event_type text not null,
              content_json text not null,
              source text not null,
              salience real not null default 0,
              durable_kind text,
              durable_key text,
              status text not null default 'RAW',
              created_at text not null,
              promoted_at text
            );
            create index if not exists episodic_status_idx on episodic_memory(status, created_at);
            create table if not exists durable_memory (
              memory_kind text not null,
              memory_key text not null,
              value_json text not null,
              source_episode_id text,
              confidence real not null default 1,
              updated_at text not null,
              primary key(memory_kind, memory_key)
            );
            """)

    def record_episode(self, *, event_type: str, content: Mapping[str, Any], source: str,
                       salience: float = 0.0, durable_kind: str | None = None,
                       durable_key: str | None = None) -> dict[str, Any]:
        kind = durable_kind.strip().lower() if durable_kind else None
        if kind and kind not in DURABLE_KINDS:
            raise ValueError(f"unsupported durable memory kind: {kind}")
        if bool(kind) != bool(durable_key and durable_key.strip()):
            raise ValueError("durable_kind and durable_key must be supplied together")
        episode_id = str(uuid.uuid4())
        row = {
            "episode_id": episode_id,
            "event_type": event_type.strip(),
            "content_json": json.dumps(dict(content), sort_keys=True),
            "source": source.strip(),
            "salience": max(0.0, min(float(salience), 1.0)),
            "durable_kind": kind,
            "durable_key": durable_key.strip() if durable_key else None,
            "status": "RAW",
            "created_at": now(),
        }
        if not row["event_type"] or not row["source"]:
            raise ValueError("event_type and source are required")
        with self.connect() as db:
            db.execute("insert into episodic_memory(episode_id,event_type,content_json,source,salience,durable_kind,durable_key,status,created_at) values(:episode_id,:event_type,:content_json,:source,:salience,:durable_kind,:durable_key,:status,:created_at)", row)
        return {**row, "content": dict(content)}

    def consolidate(self, *, minimum_salience: float = 0.6, limit: int = 100) -> dict[str, int]:
        """Promote explicitly keyed episodes; never infer durable facts from raw logs."""
        with self.connect() as db:
            rows = db.execute(
                "select * from episodic_memory where status='RAW' and durable_kind is not null and durable_key is not null and salience>=? order by created_at asc limit ?",
                (max(0.0, min(float(minimum_salience), 1.0)), max(1, min(int(limit), 500))),
            ).fetchall()
            promoted = 0
            for row in rows:
                db.execute(
                    "insert into durable_memory(memory_kind,memory_key,value_json,source_episode_id,confidence,updated_at) values(?,?,?,?,?,?) on conflict(memory_kind,memory_key) do update set value_json=excluded.value_json,source_episode_id=excluded.source_episode_id,confidence=excluded.confidence,updated_at=excluded.updated_at",
                    (row["durable_kind"], row["durable_key"], row["content_json"], row["episode_id"], row["salience"], now()),
                )
                db.execute("update episodic_memory set status='PROMOTED',promoted_at=? where episode_id=?", (now(), row["episode_id"]))
                promoted += 1
        return {"promoted": promoted, "examined": len(rows)}

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("select * from durable_memory where memory_kind=? and memory_key=?", (kind, key)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        return result

    def recent_episodes(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("select * from episodic_memory order by created_at desc limit ?", (max(1, min(limit, 200)),)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["content"] = json.loads(item.pop("content_json"))
            output.append(item)
        return output
