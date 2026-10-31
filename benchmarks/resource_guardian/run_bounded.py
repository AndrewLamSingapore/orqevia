"""Sequential, finite qualification using unique source-compilation partitions.

This exercises 21 logical task identities, not model quality or 21 local agents.
No imports/execution of target source, production mutations, or network writes.
"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import ssl

import psutil

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from app.agent_registry import registered_agent_ids  # noqa: E402
from app.resource_guardian import Profile, ResourceGuardian, Workload  # noqa: E402
from app.resource_process import connect, run_guarded  # noqa: E402

CHILD = r"""
from pathlib import Path
import json,sys,time
files=json.loads(Path(sys.argv[1]).read_text())
total=0
for name in files:
 p=Path(name);data=p.read_bytes();compile(data,str(p),'exec');total+=len(data)
Path(sys.argv[2]).write_text(json.dumps({'files':len(files),'bytes':total,'syntax':'PASS'}))
"""


def summary(values):
    values = sorted(values)
    return {
        "n": len(values),
        "median": statistics.median(values),
        "p95": values[max(0, math.ceil(len(values) * 0.95) - 1)],
        "variance": statistics.variance(values) if len(values) > 1 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    profile = Profile.read(REPO / "config/resource-guardian.abex.example.json")
    paths = sorted(p for p in (REPO / "app").rglob("*.py") if "__pycache__" not in p.parts)
    agents = sorted(registered_agent_ids(include_orchestrator=False))
    groups = [paths[i :: len(agents)] for i in range(len(agents))]
    group_files = []
    for agent, group in zip(agents, groups):
        path = args.output / (agent + "-input.json")
        path.write_text(json.dumps([str(p) for p in group]))
        group_files.append(path)
    run_id = str(time.time_ns())
    trials = []
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    for label, workers, guarded in [("baseline-one", 1, False), ("guarded-one", 1, True), ("guarded-two", 2, True)]:
        samples = []
        latencies = []
        stop = threading.Event()
        safety = threading.Event()
        database = args.output / (label + "-" + run_id + ".sqlite")
        guardian = ResourceGuardian(profile)
        if guarded:
            with connect(database) as db:
                guardian.install(db)
                guardian.set_mode(db, "Balanced")

        def monitor():
            psutil.cpu_percent(None)
            busy_samples = 0
            while not stop.wait(0.2):
                memory = psutil.virtual_memory()
                cpu = psutil.cpu_percent(None)
                samples.append({"at": time.time(), "cpu_percent": cpu, "available_memory_bytes": memory.available})
                if memory.available < profile.data["hardware"]["host_memory_bytes"] * 0.2:
                    safety.set()
                busy_samples = busy_samples + 1 if cpu >= profile.data["thresholds"]["cpu_busy_percent"] else 0
                if busy_samples >= 3:
                    safety.set()

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

        def health():
            start = time.perf_counter()
            try:
                with opener.open("https://127.0.0.1:8443/interface/v1/health", timeout=5) as response:
                    value = json.load(response)
                    latencies.append(
                        {
                            "seconds": time.perf_counter() - start,
                            "status": response.status,
                            "state": value.get("state"),
                            "tls_verified": True,
                        }
                    )
            except Exception as error:
                latencies.append({"error": type(error).__name__})

        def execute(pair):
            agent, input_path = pair
            if safety.is_set():
                return {"agent": agent, "status": "DEFERRED_SAFETY", "wall_seconds": 0, "syntax_result": None}
            output = args.output / (label + "-" + agent + "-result.json")
            command = [sys.executable, "-c", CHILD, str(input_path), str(output)]
            started = time.perf_counter()
            if guarded:
                result = run_guarded(
                    guardian,
                    database,
                    command,
                    workload=Workload("tools", 128 * 1048576, 1),
                    work_key=run_id + ":" + label + ":" + agent,
                    timeout_seconds=15,
                    cwd=str(REPO),
                    cancel_event=safety,
                    output=subprocess.DEVNULL,
                )
            else:
                item = subprocess.run(
                    command, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
                )
                result = {"status": "COMPLETED" if item.returncode == 0 else "FAILED", "exit_code": item.returncode}
            result.update(
                agent=agent,
                wall_seconds=time.perf_counter() - started,
                syntax_result=json.loads(output.read_text()) if output.exists() else None,
            )
            return result

        health()
        started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(execute, zip(agents, group_files)))
        finally:
            elapsed = time.perf_counter() - started
            stop.set()
            thread.join(timeout=2)
        health()
        statuses = {
            status: sum(r["status"] == status for r in results) for status in sorted({r["status"] for r in results})
        }
        trials.append(
            {
                "label": label,
                "max_owned_processes": workers,
                "elapsed_seconds": elapsed,
                "logical_tasks": len(results),
                "statuses": statuses,
                "tasks_per_second": len(results) / elapsed,
                "task_latency_seconds": summary([r["wall_seconds"] for r in results]),
                "cpu_peak_percent": max((s["cpu_percent"] for s in samples), default=None),
                "minimum_available_memory_bytes": min((s["available_memory_bytes"] for s in samples), default=None),
                "safety_stopped": safety.is_set(),
                "https_latency": latencies,
                "resource_samples": samples,
                "results": results,
            }
        )
        if safety.is_set() or any(r["status"] != "COMPLETED" for r in results):
            break
    sample = guardian.observe()
    work = Workload("tools", 128 * 1048576)
    timings = []
    for _ in range(1000):
        start = time.perf_counter()
        profile.decide(sample, work)
        timings.append(time.perf_counter() - start)
    package = {
        "scope": "BOUNDED_UNIQUE_SOURCE_SYNTAX_COMPILATION_NOT_AGENT_ROLE_QUALITY_OR_HEAVY_BUILD_CAPACITY",
        "production_background_resumed": False,
        "native_or_model_calls": 0,
        "agent_identities": agents,
        "source_files": len(paths),
        "source_bytes": sum(p.stat().st_size for p in paths),
        "source_inventory_sha256": hashlib.sha256(
            "\n".join(str(p.relative_to(REPO)) for p in paths).encode()
        ).hexdigest(),
        "source_content_sha256": hashlib.sha256(
            b"".join(str(p.relative_to(REPO)).encode() + b"\0" + p.read_bytes() for p in paths)
        ).hexdigest(),
        "profile_sha256": profile.digest,
        "trials": trials,
        "policy_evaluation_seconds": summary(timings),
        "limitations": [
            "One trial per concurrency; startup and SQLite overhead are included",
            "This does not qualify arbitrary builds, rendering, thermal limits or model memory",
            "Sampled CPU/working-set counters are not energy measurements",
            "Production profile remains unconfigured",
        ],
    }
    (args.output / "bounded-validation.json").write_text(json.dumps(package, indent=2) + "\n")
    print(
        json.dumps(
            {
                "source_files": len(paths),
                "trials": [{k: v for k, v in t.items() if k not in ["results", "resource_samples"]} for t in trials],
                "policy_evaluation_seconds": package["policy_evaluation_seconds"],
            }
        )
    )
    return 0 if len(trials) == 3 and all(t["statuses"] == {"COMPLETED": 21} for t in trials) else 1


if __name__ == "__main__":
    raise SystemExit(main())
