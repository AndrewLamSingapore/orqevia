"""Run and preserve one complete 21-task ORQEVIA project workflow."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8000"
TOKEN = os.environ["ORQEVIA_SPINE_TOKEN"].strip()
OUTPUT = Path(os.getenv("ORQEVIA_FINAL_21_OUTPUT", "/data/final-21-20261020"))
RUN_LABEL = os.getenv("ORQEVIA_FINAL_21_LABEL", "20261020-v1").strip()
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED"}


def api(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
        "Origin": BASE,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE + path,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def api_bytes(path: str) -> bytes:
    request = urllib.request.Request(
        BASE + path,
        headers={"Authorization": "Bearer " + TOKEN, "Origin": BASE},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "template_id": "sme-profitability.v1",
        "project_key": f"ORQ-MIT-21-{RUN_LABEL}",
        "title": f"ORQEVIA final runtime 21-task workflow {RUN_LABEL}",
        "currency": "SGD",
        "inputs": {
            "salaries": 18000,
            "marketing": 3000,
            "other_expenses": 2000,
            "revenue": 50000,
            "rent": 8000,
            "inventory": 12000,
            "utilities": 2000,
        },
        "scenarios": {
            "revenue_lift_percent": 8,
            "marketing_increase_percent": 20,
            "inventory_reduction_percent": 10,
        },
        "idempotency_key": f"orqevia-final-21-{RUN_LABEL}",
    }
    (OUTPUT / "request.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    run = api("/api/project-workflows", payload)
    run_id = run["run_id"]
    started = time.monotonic()
    last_phase = None
    while True:
        run = api("/api/project-workflows/" + urllib.parse.quote(run_id))
        (OUTPUT / "latest-status.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        phase = run.get("current_phase")
        if phase != last_phase:
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "state": run.get("state"),
                        "phase": phase,
                        "summary": run.get("summary"),
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            last_phase = phase
        if run.get("state") in TERMINAL:
            break
        if time.monotonic() - started > 7200:
            raise TimeoutError(run_id)
        time.sleep(10)
    (OUTPUT / "workflow-results.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifact_receipts = []
    for item in run.get("artifacts", []):
        name = item["name"]
        raw = api_bytes(
            "/api/project-workflows/" + urllib.parse.quote(run_id) + "/artifacts/" + urllib.parse.quote(name)
        )
        path = OUTPUT / name
        path.write_bytes(raw)
        artifact_receipts.append(
            {
                "name": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "matches_workflow_manifest": hashlib.sha256(raw).hexdigest() == item.get("sha256"),
            }
        )
    summary = {
        "run_id": run_id,
        "state": run.get("state"),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "task_summary": run.get("summary"),
        "artifact_receipts": artifact_receipts,
        "evidence": str(OUTPUT / "workflow-results.json"),
        "evidence_sha256": hashlib.sha256((OUTPUT / "workflow-results.json").read_bytes()).hexdigest(),
    }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if run.get("state") == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
