"""Run inside the existing interface child: metadata timings, no private rows."""

import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time

from app import interface_telemetry

root = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
path = root / "compute-queue.db"
original_connect = sqlite3.connect
queries = []


def traced_connect(*args, **kwargs):
    connection = original_connect(*args, **kwargs)
    connection.set_trace_callback(lambda query: queries.append(query) if query.startswith("WITH times") else None)
    return connection


sqlite3.connect = traced_connect
values = []
cpu = time.process_time()
for _ in range(12):
    start = time.perf_counter()
    result = interface_telemetry.agent_activity()
    values.append(time.perf_counter() - start)
cpu = time.process_time() - cpu
sqlite3.connect = original_connect
with original_connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2) as db:
    count = db.execute("SELECT COUNT(*) FROM compute_jobs").fetchone()[0]
    indexes = [row[1] for row in db.execute("PRAGMA index_list(compute_jobs)")]
    plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + queries[-1])] if queries else None
samples = sorted(values[1:])
print(
    json.dumps(
        {
            "scope": "LIVE_READONLY_METADATA_NO_TASK_CONTENT",
            "production_mutated": False,
            "source_function_sha256": hashlib.sha256(
                inspect.getsource(interface_telemetry.agent_activity).encode()
            ).hexdigest(),
            "journal_rows": count,
            "index_names": indexes,
            "query_plan": plan,
            "returned_agents": len(result) if result is not None else None,
            "n": len(samples),
            "warmup_runs": 1,
            "raw_seconds": values[1:],
            "median_seconds": statistics.median(samples),
            "p95_seconds": samples[math.ceil(0.95 * len(samples)) - 1],
            "variance_seconds_squared": statistics.variance(samples),
            "process_cpu_seconds_including_warmup": cpu,
        }
    )
)
