"""Observe A19's official role:normal case on a disposable cloud runner.

This is execution evidence only. Independent protected review and signing are
separate, and a branch observation cannot certify the canonical runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from datetime import datetime, timezone

from scripts.run_a18_offhost_observation import (
    _events, _model_digest, _required_absolute, _require_read_only_mount,
)


AGENT = "a19"
CAPABILITY = "responsibility.a19"
CASE = "role:normal"
ORACLE = "group_two_exact_role_oracle/v1"


def _case_digest(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _require_deterministic_profile(profile: dict | None) -> None:
    if not isinstance(profile, dict) or profile.get("generation_options") != {"temperature": 0}:
        raise RuntimeError("hash-bound deterministic generation options required")


def _verify_lineage(spec: dict, observation: dict, job: dict,
                    events: list[dict], correlation_id: str | None) -> tuple[bool, tuple[str, ...]]:
    """Check identity and provenance independently of the role oracle verdict."""
    errors = []
    job_id = observation.get("job_id")
    if (observation.get("agent_id") != AGENT or
            observation.get("capability_id") != CAPABILITY or
            observation.get("case") != CASE or
            observation.get("state") != "EXECUTED" or
            observation.get("certification") != "UNVERIFIED" or
            observation.get("oracle_id") != ORACLE or
            observation.get("case_spec_sha256") != _case_digest(spec)):
        errors.append("case_observation_binding")
    if (not isinstance(job_id, str) or job.get("id") != job_id or
            job.get("agent") != AGENT or job.get("status") != "completed" or
            type(job.get("attempts")) is not int or job["attempts"] != 1 or
            job.get("allow_cloud") or job.get("provider") != "ollama-deep"):
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
                row.get("agent_id") == AGENT and row.get("action_type") == action_type]
        if not any(row.get("phase") == "started" for row in rows) or not any(
                row.get("phase") == "completed" and row.get("success") is True
                for row in rows):
            errors.append("ledger_" + action_type)
    return not errors, tuple(errors)


def main() -> int:
    if os.name != "posix" or os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("disposable GitHub Linux runner required")
    if Path("/var/run/docker.sock").exists() or Path("/run/docker.sock").exists():
        raise RuntimeError("Docker socket must not be available to PRIME consumer")
    output = _required_absolute("PRIME_A19_OBSERVATION_OUTPUT")
    data_dir = _required_absolute("PRIME_DATA_DIR")
    runner_temp = _required_absolute("RUNNER_TEMP").resolve()
    if not data_dir.resolve().is_relative_to(runner_temp) or not output.resolve().is_relative_to(runner_temp):
        raise RuntimeError("runner-temp-only evidence boundary required")
    backend_receipt = _required_absolute("PRIME_BACKEND_MEMORY_RECEIPT")
    compute_profile = _required_absolute("PRIME_MEASURED_COMPUTE_PROFILE")
    _require_read_only_mount(backend_receipt)
    _require_read_only_mount(compute_profile)
    _require_read_only_mount(Path(__file__).resolve())
    source_revision = os.getenv("PRIME_A19_SOURCE_REVISION", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", source_revision) or
            source_revision != os.getenv("GITHUB_SHA")):
        raise RuntimeError("exact checked-out source revision required")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdecimal() or not run_attempt.isdecimal():
        raise RuntimeError("GitHub run identity required")
    endpoint = os.environ["OLLAMA_BASE_URL"].rstrip("/")
    if endpoint != "http://127.0.0.1:11434":
        raise RuntimeError("runner-local Ollama endpoint required")
    model = os.environ["PRIME_DEEP_MODEL"]
    expected_digest = os.environ["PRIME_A19_EXPECTED_MODEL_DIGEST"]
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or
            _model_digest(endpoint, model) != expected_digest):
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

    from app.agent_cert_role_group_two import observe_role_case, role_case
    from app.agent_dispatch_api import AgentRequest, dispatch_request
    from app import compute_queue_api
    from app.action_records import action_ledger
    from app.compute_profile import load_compute_profile
    from app.backend_admission import observation as backend_observation

    profile = load_compute_profile()
    _require_deterministic_profile(profile)
    details = profile.get("models", {}).get(model)
    if not isinstance(details, dict) or type(details.get("peak_mib")) is not int:
        raise RuntimeError("hash-pinned model peak required")
    backend_observation(endpoint)
    bearer = "Bearer " + ephemeral_token
    spec = role_case(AGENT)
    correlation_id = None

    def dispatch(request: dict) -> dict:
        nonlocal correlation_id
        reply = dispatch_request(AgentRequest(**request), bearer)
        correlation_id = reply.get("correlation_id")
        return reply

    compute_queue_api.start_compute_queue()
    try:
        observed = observe_role_case(spec, dispatch=dispatch,
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
    lineage_pass, lineage_errors = _verify_lineage(spec, observed, job, events,
                                                   correlation_id)
    role_review_pass = observed.get("case_review") == "ROLE_CHECK_PASS"
    receipt = {
        "schema": "prime.a19.offhost-role-normal-observation.v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": source_revision,
        "github_run_id": run_id, "github_run_attempt": run_attempt,
        "model": model, "model_digest": expected_digest,
        "profile_sha256": os.environ.get("PRIME_MEASURED_COMPUTE_PROFILE_SHA256"),
        "case": CASE, "challenge": spec, "case_spec_sha256": _case_digest(spec),
        "observation": observed, "correlation_id": correlation_id,
        "queue_job": job, "action_events": events,
        "lineage_pass": lineage_pass, "lineage_errors": lineage_errors,
        "role_review_pass": role_review_pass,
        "certification": "UNVERIFIED",
        "scope": "off-host execution; independent protected review and current-source binding outstanding",
    }
    serialized = json.dumps(receipt, sort_keys=True, indent=2)
    if ephemeral_token in serialized:
        raise RuntimeError("ephemeral credential unexpectedly entered receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(serialized + "\n")
    print(json.dumps({"receipt": str(output), "sha256": hashlib.sha256(
        (serialized + "\n").encode()).hexdigest(),
        "lineage_pass": lineage_pass, "role_review_pass": role_review_pass,
        "certification": "UNVERIFIED"}))
    return 0 if lineage_pass and role_review_pass else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Exception messages may embed environment or upstream payloads.
        print("A19 off-host observation blocked: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
