"""Durable, local compute accounting for PRIME reasoning calls."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComputeLedger:
    def __init__(self, path: str | None = None):
        data_dir = os.getenv("PRIME_DATA_DIR", "/data").strip() or "/data"
        self.path = path or os.getenv("PRIME_COMPUTE_DB") or str(Path(data_dir) / "compute-ledger.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                create table if not exists compute_events (
                    event_id text primary key,
                    task_id text not null,
                    stage text not null,
                    provider text not null,
                    model text not null,
                    latency_ms integer not null,
                    input_units integer,
                    output_units integer,
                    estimated_cost_usd real,
                    success integer not null,
                    confidence text,
                    verification text,
                    metadata_json text not null,
                    created_at text not null
                )
            """)
            db.execute("create index if not exists compute_task_idx on compute_events(task_id, created_at)")

    def record(self, *, task_id: str, stage: str, provider: str, model: str,
               latency_ms: int, success: bool, input_units: int | None = None,
               output_units: int | None = None, estimated_cost_usd: float | None = None,
               confidence: str | None = None, verification: str | None = None,
               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()), "task_id": task_id, "stage": stage,
            "provider": provider, "model": model, "latency_ms": max(0, int(latency_ms)),
            "input_units": input_units, "output_units": output_units,
            "estimated_cost_usd": estimated_cost_usd, "success": 1 if success else 0,
            "confidence": confidence, "verification": verification,
            "metadata_json": json.dumps(metadata or {}, sort_keys=True), "created_at": _now(),
        }
        with sqlite3.connect(self.path) as db:
            db.execute("""insert into compute_events(event_id,task_id,stage,provider,model,latency_ms,input_units,output_units,estimated_cost_usd,success,confidence,verification,metadata_json,created_at)
                        values(:event_id,:task_id,:stage,:provider,:model,:latency_ms,:input_units,:output_units,:estimated_cost_usd,:success,:confidence,:verification,:metadata_json,:created_at)""", event)
        return {**event, "success": bool(event["success"]), "metadata": metadata or {}}

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("select * from compute_events order by created_at desc limit ?", (max(1, min(limit, 500)),)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["success"] = bool(item["success"])
            item["metadata"] = json.loads(item.pop("metadata_json"))
            out.append(item)
        return out
