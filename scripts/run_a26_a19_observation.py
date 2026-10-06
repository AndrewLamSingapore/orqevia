"""Observe a distinct registered A26 review of one passing A19 case off-host.

The host authenticates the A19 Actions run before dispatch. The isolated PRIME
consumer receives only hash-bound case data, never the GitHub read token. This
runner emits execution evidence, not an attestation or certification level.
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

from app.agent_cert_a19_a26_review import (
    a26_review_prompt, a26_review_request, a26_review_result,
)
from app.agent_cert_a19_protected_review import _local_only, review_a19_role_receipt
from scripts.run_a18_offhost_observation import (
    _events, _model_digest, _required_absolute, _require_read_only_mount,
)
from scripts.run_a19_offhost_observation import _require_deterministic_profile
from scripts.run_a19_protected_review_job import _api_json, _file, _trusted_run


REPOSITORY = "AndrewLamSingapore/prime"
WORKFLOW_REF = f"{REPOSITORY}/.github/workflows/a26-a19-observation.yml@refs/heads/main"
REVIEWER = "a26"
SUBJECT = "a19"
CASE = "role:normal"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate A26 input field")
        result[key] = value
    return result


def preflight() -> tuple[str, str, str, str]:
    source = os.getenv("GITHUB_SHA", "")
    review_run = os.getenv("GITHUB_RUN_ID", "")
    a19_run = os.getenv("PRIME_A19_RUN_ID", "")
    artifact_id = os.getenv("PRIME_A19_ARTIFACT_ID", "")
    if (os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("GITHUB_REPOSITORY") != REPOSITORY
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_REF_PROTECTED") != "true"
            or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.getenv("PRIME_A26_WORKFLOW_REF") != WORKFLOW_REF
            or not _SHA.fullmatch(source)
            or not review_run.isdecimal()
            or not a19_run.isdecimal() or len(a19_run) > 20
            or not artifact_id.isdecimal() or len(artifact_id) > 20
            or review_run == a19_run):
        raise ValueError("distinct protected-main A26 invocation required")
    return source, review_run, a19_run, artifact_id


def reviewed_input(execution_raw: bytes, profile_raw: bytes, *,
                   trusted_run: dict, source_revision: str,
                   review_run_id: str,
                   reviewer_agent_id: str = REVIEWER) -> dict:
    """Recompute PASS from authenticated A19 bytes before A26 sees the case."""
    if reviewer_agent_id != REVIEWER or reviewer_agent_id == SUBJECT:
        raise ValueError("independent registered A26 reviewer required")
    checked = review_a19_role_receipt(
        execution_raw, profile_raw=profile_raw, source_revision=source_revision,
        trusted_run=trusted_run)
    execution = json.loads(execution_raw, object_pairs_hook=_unique)
    if (execution["observation"]["agent_id"] != SUBJECT
            or execution["queue_job"]["agent"] != SUBJECT
            or not review_run_id.isdecimal()
            or execution["github_run_id"] == review_run_id):
        raise ValueError("A19 subject or independent run mismatch")
    request = a26_review_request(execution, checked, source_revision=source_revision)
    return {
        "schema": "prime.a26.a19-review-input.v1",
        "source_revision": source_revision,
        "a19_run_id": trusted_run["run_id"],
        "a19_run_attempt": trusted_run["run_attempt"],
        "a19_job_id": checked["job_id"],
        "subject_agent_id": SUBJECT,
        "reviewer_agent_id": REVIEWER,
        "case": CASE,
        "execution_receipt_sha256": checked["execution_receipt_sha256"],
        "case_spec_sha256": checked["case_spec_sha256"],
        "result_sha256": checked["result_sha256"],
        "request": request,
        "certification": "UNVERIFIED",
    }


def prepare() -> str:
    source, review_run, a19_run, artifact_id = preflight()
    token = os.getenv("GH_TOKEN", "")
    branch = _api_json("branches/main", token)
    if branch.get("protected") is not True:
        raise ValueError("GitHub main protection is not active")
    runner_temp = _required_absolute("RUNNER_TEMP").resolve()
    root = runner_temp / "a19-execution"
    execution_raw = _file(root, "a19-observation.json")
    profile_raw = _file(root, "profile.json")
    trusted = _trusted_run(
        a19_run, artifact_id, workflow="a19-offhost-role",
        artifact_name=f"a19-offhost-observation-{a19_run}",
        raw=execution_raw, source=source, protected=True, token=token)
    item = reviewed_input(execution_raw, profile_raw,
                          trusted_run=trusted, source_revision=source,
                          review_run_id=review_run)
    raw = (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
    output = runner_temp / "a26-input" / "a19-reviewed-input.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _lineage(observed: dict, job: dict, events: list[dict], correlation: object,
             a19_job_id: str, request: dict) -> bool:
    job_id = observed.get("job_id")
    prompt = job.get("prompt")
    expected_prompt = a26_review_prompt(request)
    if (observed.get("state") != "EXECUTED"
            or observed.get("agent_id") != REVIEWER
            or observed.get("capability_id") != "responsibility.a26"
            or observed.get("certification") != "UNVERIFIED"
            or not isinstance(job_id, str) or job_id == a19_job_id
            or job.get("id") != job_id or job.get("agent") != REVIEWER
            or job.get("status") != "completed" or job.get("provider") != "ollama-deep"
            or not _local_only(job.get("allow_cloud"))
            or job.get("classification") != "R0"
            or job.get("data_classification") != "LOCAL_ONLY"
            or type(job.get("max_cost_usd")) not in (int, float)
            or job["max_cost_usd"] != 0
            or type(job.get("attempts")) is not int or job["attempts"] != 1
            or prompt != expected_prompt
            or not isinstance(correlation, str) or not correlation
            or not isinstance(events, list)):
        return False
    raw_result = job.get("result")
    if (not isinstance(raw_result, str)
            or hashlib.sha256(raw_result.encode()).hexdigest()
            != observed.get("result_sha256")):
        return False
    for task_id, action in ((job_id, "inference.run"),
                            (correlation, "inference.enqueue")):
        matches = [event for event in events if isinstance(event, dict)
                   and event.get("task_id") == task_id
                   and event.get("agent_id") == REVIEWER
                   and event.get("action_type") == action]
        if (len(matches) != 2 or {event.get("phase") for event in matches}
                != {"started", "completed"}
                or next(event for event in matches if event["phase"] == "completed").get("success") is not True):
            return False
        if action == "inference.enqueue" and any(
                not isinstance(event.get("parameters_summary"), dict)
                or event["parameters_summary"].get("prompt_sha256")
                != hashlib.sha256(prompt.encode()).hexdigest()
                for event in matches):
            return False
    return True


def execute() -> int:
    if os.name != "posix" or os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("disposable GitHub Linux runner required")
    if Path("/var/run/docker.sock").exists() or Path("/run/docker.sock").exists():
        raise RuntimeError("Docker socket must not be available to PRIME consumer")
    runner_temp = _required_absolute("RUNNER_TEMP").resolve()
    data_dir = _required_absolute("PRIME_DATA_DIR")
    output = _required_absolute("PRIME_A26_OBSERVATION_OUTPUT")
    input_path = _required_absolute("PRIME_A26_REVIEW_INPUT")
    if (not data_dir.resolve().is_relative_to(runner_temp)
            or not output.resolve().is_relative_to(runner_temp)):
        raise RuntimeError("runner-temp-only evidence boundary required")
    for path in (input_path, _required_absolute("PRIME_BACKEND_MEMORY_RECEIPT"),
                 _required_absolute("PRIME_MEASURED_COMPUTE_PROFILE"),
                 Path(__file__).resolve()):
        _require_read_only_mount(path)
    input_raw = input_path.read_bytes()
    input_digest = os.getenv("PRIME_A26_REVIEW_INPUT_SHA256", "")
    if (not _DIGEST.fullmatch(input_digest)
            or len(input_raw) > 1024 * 1024
            or hashlib.sha256(input_raw).hexdigest() != input_digest):
        raise RuntimeError("prepared A19 review input digest mismatch")
    item = json.loads(input_raw, object_pairs_hook=_unique)
    source = os.getenv("GITHUB_SHA", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "")
    if (item.get("schema") != "prime.a26.a19-review-input.v1"
            or item.get("source_revision") != source
            or item.get("subject_agent_id") != SUBJECT
            or item.get("reviewer_agent_id") != REVIEWER
            or item.get("case") != CASE
            or item.get("certification") != "UNVERIFIED"
            or item.get("a19_run_id") == run_id
            or not _SHA.fullmatch(source)
            or not run_id.isdecimal() or not run_attempt.isdecimal()
            or not all(isinstance(item.get(name), str) and _DIGEST.fullmatch(item[name])
                       for name in ("execution_receipt_sha256", "case_spec_sha256",
                                    "result_sha256"))):
        raise RuntimeError("A26 review input identity mismatch")
    request = item.get("request")
    if (not isinstance(request, dict)
            or request.get("capability") != "responsibility.a26"
            or request.get("data_classification") != "LOCAL_ONLY"
            or request.get("max_cost_usd") != 0
            or request.get("preferred_provider") != "ollama-deep"
            or request.get("response_format") != "strict_json"):
        raise RuntimeError("A26 registered review route required")
    endpoint = os.environ["OLLAMA_BASE_URL"].rstrip("/")
    if endpoint != "http://127.0.0.1:11434":
        raise RuntimeError("runner-local Ollama endpoint required")
    model = os.environ["PRIME_DEEP_MODEL"]
    expected_digest = os.environ["PRIME_A26_EXPECTED_MODEL_DIGEST"]
    if (not _DIGEST.fullmatch(expected_digest)
            or _model_digest(endpoint, model) != expected_digest):
        raise RuntimeError("local model digest differs from pinned expected value")
    os.environ.update({
        "PRIME_QUEUE_CONCURRENCY": "1", "PRIME_REGISTRY_V1_ENABLED": "1",
        "PRIME_DEEP_MODEL": model, "PRIME_EVALUATOR_MODEL": model,
        "PRIME_EMBED_MODEL": model, "PRIME_MULTI_SPECIALIST_WORKERS": "1",
        "PRIME_CONTEXT_TOKENS": "2048", "PRIME_MAX_OUTPUT_TOKENS": "256",
        "PRIME_CONTEXT_PACKS_ENABLED": "0", "PRIME_SKILL_PACKS_ENABLED": "0",
    })
    ephemeral_token = secrets.token_urlsafe(32)
    os.environ["PRIME_SPINE_TOKEN"] = ephemeral_token

    from app.agent_cert_execution import observe_cert_case
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
    correlation = None

    def dispatch(prepared: dict) -> dict:
        nonlocal correlation
        reply = dispatch_request(AgentRequest(**prepared), bearer)
        correlation = reply.get("correlation_id")
        return reply

    spec = {"agent_id": REVIEWER, "capability_id": "responsibility.a26",
            "case": "review:a19:role:normal", "request": request,
            "certification": "UNVERIFIED"}
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
    action_ledger().flush()
    events = _events(data_dir / "action-records.jsonl",
                     {str(observed.get("job_id")), str(correlation)})
    lineage = _lineage(observed, job, events, correlation,
                       item["a19_job_id"], request)
    decision = "PASS" if lineage and a26_review_result(job.get("result")) else "FAIL"
    receipt = {
        "schema": "prime.a26.a19-role-review.v1",
        "source_revision": source, "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer_agent_id": REVIEWER, "subject_agent_id": SUBJECT,
        "case": CASE,
        "execution_receipt_sha256": item["execution_receipt_sha256"],
        "case_spec_sha256": item["case_spec_sha256"],
        "result_sha256": item["result_sha256"],
        "decision": decision, "queue_job": job,
        "correlation_id": correlation, "action_events": events,
        "certification": "UNVERIFIED",
    }
    serialized = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    if ephemeral_token in serialized:
        raise RuntimeError("ephemeral credential unexpectedly entered receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(serialized)
    print(json.dumps({"receipt_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                      "decision": decision, "certification": "UNVERIFIED"}))
    return 0 if decision == "PASS" else 1


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--preflight"]:
            preflight()
            print("A26 protected-main preflight: PASS")
        elif sys.argv[1:] == ["--prepare"]:
            print("A26 reviewed input SHA-256: " + prepare())
        elif sys.argv[1:] == ["--execute"]:
            sys.exit(execute())
        else:
            raise ValueError("preflight, prepare, or execute mode required")
    except Exception as exc:
        print("A26 off-host observation blocked: " + type(exc).__name__, file=sys.stderr)
        sys.exit(2)
