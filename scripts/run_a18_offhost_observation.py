"""One off-host A18 official-case observation; never a certification or signer.

Run only in a disposable runner with an independently produced, fresh backend
receipt and a hash-pinned measured compute profile. No bypass or test-mode
admission sample is installed here. The caller provides a pinned model digest.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen


def _required_absolute(name: str) -> Path:
    raw = os.getenv(name, "")
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise RuntimeError(f"{name} absolute path required")
    return path


def _model_digest(endpoint: str, model: str) -> str:
    with urlopen(endpoint.rstrip("/") + "/api/tags", timeout=10) as response:
        rows = json.load(response).get("models", [])
    matches = [row.get("digest") for row in rows
               if isinstance(row, dict) and row.get("name") == model]
    if len(matches) != 1 or not isinstance(matches[0], str) or not matches[0]:
        raise RuntimeError("exact local model digest unavailable")
    return matches[0]


def _events(path: Path, task_ids: set[str]) -> list[dict]:
    if not path.exists():
        return []
    return [row for line in path.read_text(encoding="utf-8").splitlines()
            if (row := json.loads(line)).get("task_id") in task_ids]


def _verify_lineage(observation: dict, job: dict, events: list[dict],
                    correlation_id: str | None) -> tuple[bool, tuple[str, ...]]:
    errors = []
    job_id = observation.get("job_id")
    if (not isinstance(job_id, str) or job.get("id") != job_id or
            job.get("agent") != "a18" or job.get("status") != "completed" or
            job.get("attempts") != 1 or job.get("allow_cloud") or
            job.get("provider") != "ollama-fast"):
        errors.append("queue_identity_or_completion")
    raw = job.get("result")
    if (not isinstance(raw, str) or
            hashlib.sha256(raw.encode()).hexdigest() != observation.get("result_sha256")):
        errors.append("raw_result_digest")
    if not isinstance(correlation_id, str) or not correlation_id:
        errors.append("dispatch_correlation")
    for task_id, action_type in ((job_id, "inference.run"),
                                 (correlation_id, "inference.enqueue")):
        rows = [row for row in events if row.get("task_id") == task_id and
                row.get("agent_id") == "a18" and row.get("action_type") == action_type]
        if not any(row.get("phase") == "started" for row in rows) or not any(
                row.get("phase") == "completed" and row.get("success") is True
                for row in rows):
            errors.append("ledger_" + action_type)
    if observation.get("state") != "EXECUTED" or observation.get("case_review") != "ARTIFACT_CHECK_PASS":
        errors.append("independent_oracle")
    return not errors, tuple(errors)


def main() -> int:
    if os.name != "posix" or os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("disposable GitHub Linux runner required")
    output = _required_absolute("PRIME_A18_OBSERVATION_OUTPUT")
    data_dir = _required_absolute("PRIME_DATA_DIR")
    runner_temp = _required_absolute("RUNNER_TEMP").resolve()
    if not data_dir.resolve().is_relative_to(runner_temp) or not output.resolve().is_relative_to(runner_temp):
        raise RuntimeError("runner-temp-only evidence boundary required")
    _required_absolute("PRIME_BACKEND_MEMORY_RECEIPT")
    _required_absolute("PRIME_MEASURED_COMPUTE_PROFILE")
    endpoint = os.environ["OLLAMA_BASE_URL"].rstrip("/")
    if endpoint != "http://127.0.0.1:11434":
        raise RuntimeError("runner-local Ollama endpoint required")
    model = os.environ["PRIME_FAST_MODEL"]
    expected_digest = os.environ["PRIME_A18_EXPECTED_MODEL_DIGEST"]
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or _model_digest(endpoint, model) != expected_digest:
        raise RuntimeError("local model digest differs from pinned expected value")
    os.environ["PRIME_QUEUE_CONCURRENCY"] = "1"
    os.environ["PRIME_REGISTRY_V1_ENABLED"] = "1"
    os.environ["PRIME_DEEP_MODEL"] = model
    os.environ["PRIME_EVALUATOR_MODEL"] = model
    os.environ["PRIME_EMBED_MODEL"] = model
    os.environ["PRIME_MULTI_SPECIALIST_WORKERS"] = "1"
    os.environ["PRIME_CONTEXT_TOKENS"] = "2048"
    os.environ["PRIME_MAX_OUTPUT_TOKENS"] = "256"
    ephemeral_token = secrets.token_urlsafe(32)
    os.environ["PRIME_SPINE_TOKEN"] = ephemeral_token

    # Delayed imports bind the disposable runner environment, never ABEX data.
    from app.agent_cert_cases import challenge
    from app.agent_cert_execution import observe_cert_case
    from app.agent_dispatch_api import AgentRequest, dispatch_request
    from app import compute_queue_api
    from app.action_records import action_ledger
    from app.compute_profile import load_compute_profile

    profile = load_compute_profile()
    details = profile.get("models", {}).get(model)
    if not isinstance(details, dict) or type(details.get("peak_mib")) is not int:
        raise RuntimeError("hash-pinned model peak required")
    from app.backend_admission import observation as backend_observation
    backend_observation(endpoint)  # Actual scoped, fresh collector receipt required.
    bearer = "Bearer " + ephemeral_token
    spec = challenge("adversarial:invalid_artifact", agent_id="a18")
    correlation_id = None

    def dispatch(request: dict) -> dict:
        nonlocal correlation_id
        reply = dispatch_request(AgentRequest(**request), bearer)
        correlation_id = reply.get("correlation_id")
        return reply

    compute_queue_api.start_compute_queue()
    try:
        observed = observe_cert_case(spec, dispatch=dispatch,
                                     get_job=compute_queue_api.queue.get,
                                     timeout_seconds=120)
        job_id = observed.get("job_id")
        if observed.get("state") == "INCOMPLETE" and isinstance(job_id, str):
            compute_queue_api.queue.cancel(job_id)
    finally:
        compute_queue_api.stop_compute_queue()

    job = (compute_queue_api.queue.get(observed["job_id"])
           if isinstance(observed.get("job_id"), str) else {})
    ledger = action_ledger()
    ledger.flush()
    events = _events(data_dir / "action-records.jsonl",
                     {str(observed.get("job_id")), str(correlation_id)})
    verified, errors = _verify_lineage(observed, job, events, correlation_id)
    receipt = {
        "schema": "prime.a18.offhost-invalid-artifact-observation.v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "model": model, "model_digest": expected_digest,
        "profile_sha256": os.environ.get("PRIME_MEASURED_COMPUTE_PROFILE_SHA256"),
        "case": spec["case"], "challenge": spec, "observation": observed,
        "correlation_id": correlation_id, "queue_job": job,
        "action_events": events, "lineage_pass": verified,
        "lineage_errors": errors, "certification": "UNVERIFIED",
        "scope": "off-host synthetic compare-only; no hash-computation or L7 proof",
    }
    serialized = json.dumps(receipt, sort_keys=True, indent=2)
    if ephemeral_token in serialized:
        raise RuntimeError("ephemeral credential unexpectedly entered receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(serialized + "\n")
    print(json.dumps({"receipt": str(output), "sha256": hashlib.sha256(
        (serialized + "\n").encode()).hexdigest(), "lineage_pass": verified,
        "certification": "UNVERIFIED"}))
    return 0 if verified else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Exception messages may embed environment or upstream payloads.
        print("A18 off-host observation blocked: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
