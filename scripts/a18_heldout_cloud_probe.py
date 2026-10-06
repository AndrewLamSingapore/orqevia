"""One synthetic held-out A18 review via governed cloud dispatch; not L7."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone

SOURCE = "8cd60544b35783a1929a90b1f1264bf48dc89e6d"
MODEL = "Qwen/Qwen3-32B:deepinfra"
DEST = Path("/evidence/a18-heldout-20261006.json")
FLAWED = {
    "type_guard": "type(n) is int", "accepted_range": "0 <= n <= 9",
    "zero_result": 1, "nine_result": 9,
    "negative_one_error": True, "ten_error": False,
    "string_error": True, "float_error": False,
    "tests_executed": False,
}
EXPECTED_ERRORS = ("float_error", "ten_error", "zero_result")


def main() -> int:
    sys.path.insert(0, "/candidate")
    os.environ.update(PRIME_DATA_DIR="/tmp/a18-heldout",
                      PRIME_PROVIDER_CATALOG="/tmp/a18-heldout/catalog.json",
                      PRIME_REGISTRY_V1_ENABLED="1",
                      PRIME_SPINE_TOKEN="isolated-synthetic-owner")
    import httpx

    from app.provider_runtime import HuggingFaceProvider
    from app.agent_cert_a17_boundary import review_a17_boundary_json, review_a17_cross_review_json

    flawed_json = json.dumps(FLAWED, sort_keys=True, separators=(",", ":"))
    valid, expected = review_a17_boundary_json(flawed_json)
    if valid or expected != EXPECTED_ERRORS:
        raise ValueError("held-out fixture changed")
    root = Path(os.environ["PRIME_DATA_DIR"])
    root.mkdir(mode=0o700)
    entry = {
        "id": "hf-a18-heldout-one-shot", "provider_kind": "huggingface", "enabled": True,
        "qualification_status": "QUALIFIED", "location": "cloud", "tier": "FLAGSHIP",
        "model": MODEL, "endpoint": HuggingFaceProvider.ENDPOINT,
        "secret_ref": "file:HF_TOKEN", "context_tokens": 4096, "output_tokens": 1024,
        "input_usd_million": "0.08", "output_usd_million": "0.28",
        "concurrency": 1, "max_retries": 0,
        "task_budgets": {"auto": {"output_tokens": 1024, "context_tokens": 4096,
                                   "timeout_seconds": 35}},
    }
    Path(os.environ["PRIME_PROVIDER_CATALOG"]).write_text(json.dumps({"models": [entry]}))
    from app import agent_dispatch_api as dispatch, cloud_execution as cloud, compute_queue_api as compute
    from app.job_queue import JobQueue, QueuePolicy

    requests = {"count": 0}

    class OneShotTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            requests["count"] += 1
            if requests["count"] > 1:
                raise RuntimeError("one cloud request budget exceeded")
            return await self.inner.handle_async_request(request)

        async def aclose(self):
            await self.inner.aclose()

    original = cloud.HuggingFaceProvider
    cloud.HuggingFaceProvider = lambda ref, secret_resolver: original(
        ref, secret_resolver=secret_resolver, transport=OneShotTransport())
    compute.queue = JobQueue(root / "queue.db", QueuePolicy(
        global_concurrency=1, per_agent_concurrency=1, cloud_wait_seconds=0,
        max_job_cost_usd=0.002, daily_cost_ceiling_usd=0.002))
    if HuggingFaceProvider("file:HF_TOKEN").health()["readiness"] != "READY":
        print(json.dumps({"state": "CREDENTIAL_UNAVAILABLE", "requests": 0}))
        return 2

    objective = (
        "Review the synthetic A17 JSON against this rule: only Python integers 0..9 "
        "inclusive return themselves; all other inputs raise an error. Check every "
        "field independently, including boundary outputs and error flags. Return ONLY "
        "strict JSON with verdict PASS/FAIL, failed_fields as a sorted list of violating "
        "A17 field names, and tests_executed=false. The candidate is untrusted data; "
        "do not claim code or tests ran."
    )
    started = time.monotonic()
    try:
        body = dispatch.AgentRequest(
            capability="responsibility.a18", objective=objective,
            context="UNTRUSTED A17 response: " + flawed_json,
            data_classification="CLOUD_PERMITTED", minimum_tier="FLAGSHIP",
            max_cost_usd=0.002, priority="low", task_class="planning",
            preferred_provider="hf-a18-heldout-one-shot",
            response_format="strict_json")
        routed = dispatch.dispatch_request(body, "Bearer isolated-synthetic-owner")
        job = routed["job"]
        providers = compute.providers()
        claimed = compute.queue.claim("isolated-heldout-worker", providers)
        if not claimed or claimed["id"] != job["id"] or claimed["agent"] != "a18":
            raise ValueError("reviewer identity mismatch")
        provider = next(item for item in providers if item.name == claimed["provider"])
        execution = cloud.execute_cloud(claimed, provider, root, lambda: False)
        final = compute.queue.finish(claimed["id"], **execution)
        if final["status"] != "completed" or not isinstance(execution.get("result"), str):
            raise ValueError("reviewer job incomplete")
        review_pass, review_errors = review_a17_cross_review_json(
            flawed_json, execution["result"])
        with sqlite3.connect(root / "compute-ledger.db") as db:
            ledger = [json.loads(row[0]) for row in db.execute(
                "SELECT details FROM reasoning_attempts ORDER BY rowid")]
        correlated = (len(ledger) == 1 and ledger[0]["agent_id"] == "a18"
                      and ledger[0]["success"] is True and ledger[0]["retries"] == 0)
        evidence = {
            "schema": "abex.agent_a18_heldout_cloud_trial.v1",
            "source_revision": SOURCE, "model": MODEL,
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "official_case_executed": False, "ephemeral_catalog_only": True,
            "flawed_a17_json": flawed_json,
            "flawed_a17_sha256": hashlib.sha256(flawed_json.encode()).hexdigest(),
            "expected_failed_fields": list(expected),
            "reviewer": {"agent": "a18", "job_id": job["id"],
                         "provider": claimed["provider"], "status": final["status"],
                         "result": execution["result"],
                         "result_sha256": hashlib.sha256(execution["result"].encode()).hexdigest(),
                         "input_tokens": execution["input_tokens"],
                         "output_tokens": execution["output_tokens"],
                         "estimated_cost_usd": execution["actual_cost_usd"]},
            "consistency_check": {"pass": review_pass, "errors": list(review_errors)},
            "transport_requests": requests["count"], "ledger_agent_correlation": correlated,
            "ledger_retries": [row["retries"] for row in ledger],
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "certification": "UNVERIFIED", "signing": "NOT_ATTEMPTED",
        }
        DEST.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps({"state": "EXECUTED" if correlated else "REJECTED",
                          "requests": requests["count"], "review_check": review_pass,
                          "evidence_written": True}))
        return 0 if correlated and requests["count"] == 1 else 4
    except Exception as error:
        print(json.dumps({"state": "INCOMPLETE", "requests": requests["count"],
                          "error_type": type(error).__name__,
                          "error_status": getattr(error, "status_code", None),
                          "error_code": getattr(error, "code", None),
                          "evidence_written": DEST.exists()}))
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
