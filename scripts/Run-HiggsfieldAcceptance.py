"""Preflight or explicitly approved one-job Higgsfield REST acceptance."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


BACKEND = "orqevia-epoch-20261016-backend-1"
BASE_URL = "http://127.0.0.1:8000"
APPROVAL_TOKEN = "APPROVE-ORQEVIA-HIGGSFIELD-20261019"
MODEL_PATH = "higgsfield-ai/soul/v2/standard"
TASK_ID = "higgsfield-acceptance-20261019"
IDEMPOTENCY_KEY = "orqevia-acceptance-20261019-soul-v2-1"
MAX_COST_USD = "0.25"
PAYLOAD = {
    "prompt": "A single matte red cube centered on a plain white background, soft studio lighting, no text.",
    "batch_size": 1,
    "resolution": "720p",
    "aspect_ratio": "1:1",
    "enhance_prompt": False,
}
OUTPUT_ROOT = Path(r"C:\ProgramData\ORQEVIA\acceptance")


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        with pending.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def owner_headers() -> dict[str, str]:
    environment = json.loads(
        subprocess.run(
            ["docker", "inspect", BACKEND, "--format", "{{json .Config.Env}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    values = dict(item.split("=", 1) for item in environment)
    return {"Authorization": "Bearer " + values["PRIME_SPINE_TOKEN"]}


def request(path: str, *, body: dict | None = None, headers: dict[str, str]):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={**headers, **({"Content-Type": "application/json"} if data else {})},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def submission(charge_authorized: bool) -> dict:
    return {
        "task_id": TASK_ID,
        "operation": "image",
        "model_path": MODEL_PATH,
        "payload": PAYLOAD,
        "data_classification": "CLOUD_PERMITTED",
        "max_cost_usd": MAX_COST_USD,
        "charge_authorized": charge_authorized,
        "idempotency_key": IDEMPOTENCY_KEY,
        "timeout_seconds": 900,
    }


def terminal(status: object) -> bool:
    return status in {"completed", "failed", "nsfw", "canceled"}


def save_result(job: dict) -> list[dict]:
    folder = OUTPUT_ROOT / str(job["request_id"])
    folder.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index, output in enumerate(job.get("outputs") or []):
        url = output.get("url") if isinstance(output, dict) else None
        if not isinstance(url, str):
            continue
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError("unsafe provider output URL")
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read(100 * 1024 * 1024 + 1)
        if len(raw) > 100 * 1024 * 1024:
            raise RuntimeError("provider output exceeded size bound")
        path = folder / f"output-{index + 1}"
        atomic_write(path, raw)
        artifacts.append({
            "path": str(path),
            "host": parsed.hostname,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-charge")
    parser.add_argument("--poll-timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    if not 30 <= args.poll_timeout_seconds <= 3600:
        raise SystemExit("poll timeout must be between 30 and 3600 seconds")

    headers = owner_headers()
    health = request("/media/v1/health", headers=headers)
    required_health = (
        health.get("enabled") is True
        and health.get("rest_credentials_valid") is True
        and health.get("catalog_snapshot_fresh") is True
    )
    if not required_health:
        raise SystemExit("Higgsfield health gates are not satisfied")

    estimate = request(
        "/media/v1/estimate",
        headers=headers,
        body=submission(False),
    )
    cost = float(estimate["usd"])
    if not math.isfinite(cost) or cost < 0 or cost > float(MAX_COST_USD):
        raise SystemExit("provider estimate exceeds the US$0.25 acceptance cap")

    plan = {
        "mode": "PREFLIGHT_ONLY" if args.approve_charge is None else "APPROVED_EXECUTION",
        "provider": "higgsfield",
        "model": MODEL_PATH,
        "estimated_usd": estimate["usd"],
        "estimated_credits": estimate.get("credits"),
        "maximum_cost_usd": MAX_COST_USD,
        "idempotency_key": IDEMPOTENCY_KEY,
        "charge_authorized": args.approve_charge is not None,
        "billable_request_submitted": False,
        "polling": "2s initial, 1.5x backoff, 10s maximum",
    }
    if args.approve_charge is None:
        plan["approval_required"] = APPROVAL_TOKEN
        print(json.dumps(plan, sort_keys=True))
        return 0
    if args.approve_charge != APPROVAL_TOKEN:
        raise SystemExit("explicit approval token mismatch")

    started = time.monotonic()
    job = request("/media/v1/jobs", headers=headers, body=submission(True))
    plan["billable_request_submitted"] = True
    polls = 0
    delay = 2.0
    while not terminal(job.get("status")):
        if time.monotonic() - started >= args.poll_timeout_seconds:
            job["status"] = "timeout"
            break
        time.sleep(delay + random.uniform(0, 0.5))
        job = request("/media/v1/jobs/" + str(job["request_id"]), headers=headers)
        polls += 1
        delay = min(delay * 1.5, 10.0)

    artifacts = save_result(job) if job.get("status") == "completed" else []
    receipt = {
        "schema_version": "orqevia.higgsfield-generation-acceptance.v1",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "request_id": job.get("request_id"),
        "task_id": TASK_ID,
        "model": MODEL_PATH,
        "idempotency_key": IDEMPOTENCY_KEY,
        "estimated_usd": estimate["usd"],
        "maximum_cost_usd": MAX_COST_USD,
        "terminal_status": job.get("status"),
        "polls": polls,
        "error_code": job.get("error_code"),
        "outputs": artifacts,
        "result_urls_exported": False,
    }
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    stem = OUTPUT_ROOT / f"higgsfield-acceptance-{job.get('request_id', 'unknown')}.json"
    atomic_write(stem, raw)
    atomic_write(stem.with_name(stem.name + ".sha256"), (hashlib.sha256(raw).hexdigest() + "\n").encode("ascii"))
    plan.update({
        "terminal_status": job.get("status"),
        "polls": polls,
        "output_count": len(artifacts),
        "receipt": str(stem),
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
    })
    print(json.dumps(plan, sort_keys=True))
    return 0 if job.get("status") == "completed" and len(artifacts) == len(job.get("outputs") or []) else 2


if __name__ == "__main__":
    raise SystemExit(main())
