"""Isolated real-backend owner-priority probe; never imports the live queue."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import time

from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from benchmarks.ollama_concurrency import request


def probe(width: int, base_url: str = "http://127.0.0.1:11435", owner_reserve: bool = False,
          sequence_max: int = 20) -> dict:
    if width not in (2, 3) or base_url != "http://127.0.0.1:11435":
        raise ValueError("only bounded isolated N=2/3 loopback probes are supported")
    provider = Provider("isolated-ollama", "local", "gemma3:4b", 6144, 0, width)
    policy = QueuePolicy(global_concurrency=width, per_agent_concurrency=1,
                         background_concurrency=(width - 1 if owner_reserve else 0),
                         local_ram_mb=8192, local_vram_mb=0)
    agents = ("a01", "a02", "a04", "a05", "a06")
    measurements: dict[str, dict] = {}
    lock = threading.Lock()
    with tempfile.TemporaryDirectory(prefix="prime-owner-queue-probe-") as directory:
        queue = JobQueue(Path(directory) / "queue.db", policy)

        def execute(job: dict, _provider: Provider) -> dict:
            begun = time.perf_counter()
            observed = request(base_url, provider.model, begun, 120, 8192, sequence_max)
            with lock:
                measurements[job["id"]] = {"claim_perf_s": begun, **observed}
            if not observed["ok"]:
                return {"error": "ISOLATED_PROBE_INCORRECT", "retryable": False}
            return {"result": "sequence-valid", "input_tokens": 0,
                    "output_tokens": observed.get("eval_count") or 0}

        initial_count = width - 1 if owner_reserve else width
        background = [queue.submit(agent=agent, prompt="numeric-sequence", priority="background",
                                   max_retries=0) for agent in agents[:initial_count]]
        pool = WorkerPool(queue, [provider], execute)
        pool.start()
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if all(queue.get(job["id"])["status"] == "running" for job in background):
                    break
                time.sleep(0.02)
            else:
                raise TimeoutError("initial background slots did not start")

            background += [queue.submit(agent=agent, prompt="numeric-sequence",
                                        priority="background", max_retries=0)
                           for agent in agents[initial_count:]]
            owner_submitted = time.perf_counter()
            owner = queue.submit(agent="a26", prompt="numeric-sequence", priority="critical",
                                 max_retries=0)
            deadline = time.monotonic() + 120
            all_jobs = background + [owner]
            while time.monotonic() < deadline:
                if all(queue.get(job["id"])["status"] in {"completed", "failed"} for job in all_jobs):
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError("isolated queued workload did not terminate")
            ended = time.perf_counter()
            states = {job["id"]: queue.get(job["id"])["status"] for job in all_jobs}
            owner_row = measurements.get(owner["id"])
            return {
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "isolated JobQueue plus loopback-only pinned Ollama; not production PRIME or PWA",
                "configured_parallel_label": width,
                "owner_reserve_enabled": owner_reserve,
                "sequence_max": sequence_max,
                "backend_parallel_verified_by_harness": False,
                "policy": asdict(policy),
                "request_count": len(all_jobs),
                "all_correct": all(states[job["id"]] == "completed" and
                                   measurements.get(job["id"], {}).get("ok") for job in all_jobs),
                "owner_queue_wait_s": None if owner_row is None else owner_row["claim_perf_s"] - owner_submitted,
                "owner_backend_ttft_s": None if owner_row is None else owner_row["ttft_s"],
                "owner_submit_to_first_token_s": None if owner_row is None or owner_row["first_token_s"] is None
                    else owner_row["first_token_s"] - owner_submitted,
                "owner_submit_to_completion_s": None if owner_row is None else owner_row["end_s"] - owner_submitted,
                "all_workload_completion_after_owner_submit_s": ended - owner_submitted,
                "owner_claim_before_queued_background": owner_row is not None and all(
                    owner_row["claim_perf_s"] <= measurements[job["id"]]["claim_perf_s"]
                    for job in background[initial_count:] if job["id"] in measurements),
                "model_load_duration_ns": {job["id"]: measurements.get(job["id"], {}).get("load_duration_ns")
                                           for job in all_jobs},
                "states": states,
            }
        finally:
            pool.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True, choices=(2, 3))
    parser.add_argument("--owner-reserve", action="store_true")
    parser.add_argument("--sequence-max", type=int, choices=(20, 50), default=20)
    args = parser.parse_args()
    print(json.dumps(probe(args.width, owner_reserve=args.owner_reserve,
                           sequence_max=args.sequence_max), indent=2))
