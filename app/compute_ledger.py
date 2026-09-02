"""Durable, local compute accounting for PRIME reasoning calls."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _percentile(values: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile for small, durable telemetry windows."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[rank], 3)


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
                    event_id text primary key, task_id text not null, stage text not null,
                    provider text not null, model text not null, latency_ms integer not null,
                    input_units integer, output_units integer, estimated_cost_usd real,
                    success integer not null, confidence text, verification text,
                    metadata_json text not null, created_at text not null
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

    def summary(self, limit: int = 500) -> dict[str, Any]:
        events = self.recent(limit)
        groups: dict[str, dict[str, Any]] = {}
        for event in events:
            key = f"{event['provider']}:{event['model']}"
            group = groups.setdefault(key, {
                "provider": event["provider"], "model": event["model"], "calls": 0,
                "successful_calls": 0, "latency_ms": 0, "input_units": 0,
                "output_units": 0, "output_tokens_per_second_samples": [],
            })
            group["calls"] += 1
            group["successful_calls"] += int(event["success"])
            group["latency_ms"] += int(event["latency_ms"] or 0)
            group["latency_samples"].append(float(event["latency_ms"] or 0))
            group["stages"].add(event["stage"])
            group["last_seen_at"] = max(group["last_seen_at"], event["created_at"])
            group["input_units"] += int(event["input_units"] or 0)
            group["output_units"] += int(event["output_units"] or 0)
            rate = event.get("metadata", {}).get("output_tokens_per_second")
            if isinstance(rate, (int, float)):
                group["output_tokens_per_second_samples"].append(float(rate))
        output = []
        for group in groups.values():
            calls = group["calls"]
            samples = group.pop("output_tokens_per_second_samples")
            latency_samples = group.pop("latency_samples")
            group["stages"] = sorted(group["stages"])
            group["failed_calls"] = calls - group["successful_calls"]
            group["success_rate"] = round(group["successful_calls"] / calls, 4)
            group["average_latency_ms"] = round(group.pop("latency_ms") / calls, 2)
            group["p95_latency_ms"] = _percentile(latency_samples, 0.95)
            group["average_output_tokens_per_second"] = round(sum(samples) / len(samples), 3) if samples else None
            output.append(group)
        output.sort(key=lambda item: (item["provider"], item["model"]))
        return {"window": len(events), "groups": output}

    def scorecard(self, limit: int = 500) -> dict[str, Any]:
        """Rank measured model routes without granting execution authority."""
        summary = self.summary(limit)
        ranked = []
        for group in summary["groups"]:
            throughput = group.get("average_output_tokens_per_second") or 0.0
            latency = group.get("average_latency_ms") or 0.0
            reliability = group.get("success_rate") or 0.0
            measured_score = round((reliability * 100.0) + min(throughput, 100.0) - min(latency / 1000.0, 60.0), 3)
            ranked.append({**group, "measured_score": measured_score})
        ranked.sort(key=lambda item: (-item["measured_score"], item["provider"], item["model"]))
        return {
            "window": summary["window"],
            "ranking": ranked,
            "selection_mode": "evidence_only",
            "authority": "routing policy remains deterministic and approval-gated",
        }
