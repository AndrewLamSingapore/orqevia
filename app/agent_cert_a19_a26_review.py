"""Build an unsigned A19 review only from two distinct protected agent runs.

An A26 label on fixed oracle code is not independent A26 execution. The second
receipt must contain its own completed A26 queue job and action lineage. GitHub
run metadata must be fetched independently by the protected workflow caller.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from .agent_cert_a19_protected_review import review_a19_role_receipt


REVIEW_TEST_VERSION = "a19-role-exact+a26-independent/v1"
_A26_WORKFLOW = "AndrewLamSingapore/prime/.github/workflows/a26-a19-observation.yml@refs/heads/main"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_RUN_FIELDS = {
    "repository", "repository_id", "workflow_ref", "ref", "ref_protected",
    "event_name", "head_sha", "run_id", "run_attempt", "conclusion",
    "artifact_sha256",
}
_A26_FIELDS = {
    "schema", "source_revision", "github_run_id", "github_run_attempt",
    "reviewed_at", "reviewer_agent_id", "subject_agent_id", "case",
    "execution_receipt_sha256", "case_spec_sha256", "result_sha256",
    "decision", "queue_job", "correlation_id", "action_events",
    "certification",
}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate A26 review field")
        result[key] = value
    return result


def _time(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid A26 review time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid A26 review time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A26 review time requires timezone")
    return parsed.astimezone(timezone.utc)


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _a26_run(trusted: Mapping[str, object], raw: bytes, source_revision: str,
             execution_run_id: str) -> None:
    if not isinstance(trusted, Mapping) or set(trusted) != _RUN_FIELDS:
        raise ValueError("independent A26 run provenance required")
    if (trusted["repository"] != "AndrewLamSingapore/prime"
            or trusted["repository_id"] != "1345668764"
            or trusted["workflow_ref"] != _A26_WORKFLOW
            or trusted["ref"] != "refs/heads/main"
            or trusted["ref_protected"] is not True
            or trusted["event_name"] != "workflow_dispatch"
            or trusted["head_sha"] != source_revision
            or trusted["conclusion"] != "success"
            or not isinstance(trusted["run_id"], str)
            or not trusted["run_id"].isdecimal()
            or trusted["run_id"] == execution_run_id
            or not isinstance(trusted["run_attempt"], str)
            or not trusted["run_attempt"].isdecimal()
            or trusted["artifact_sha256"] != hashlib.sha256(raw).hexdigest()):
        raise ValueError("protected independent A26 run or artifact mismatch")


def build_a19_a26_review_artifact(
        execution_raw: bytes, profile_raw: bytes, a26_raw: bytes, *,
        source_revision: str, review_run_id: str,
        trusted_execution_run: Mapping[str, object],
        trusted_a26_run: Mapping[str, object]) -> bytes:
    """Return a distinct generic review envelope, never a signed L7 record."""
    if not isinstance(source_revision, str) or not _REVISION.fullmatch(source_revision):
        raise ValueError("exact source revision required")
    observed = review_a19_role_receipt(
        execution_raw, profile_raw=profile_raw, source_revision=source_revision,
        trusted_run=trusted_execution_run)
    if not isinstance(a26_raw, bytes) or not 0 < len(a26_raw) <= 1024 * 1024:
        raise ValueError("bounded A26 execution artifact required")
    _a26_run(trusted_a26_run, a26_raw, source_revision, observed["github_run_id"])
    if (not isinstance(review_run_id, str) or not review_run_id.isdecimal()
            or review_run_id in {observed["github_run_id"], trusted_a26_run["run_id"]}):
        raise ValueError("distinct protected review workflow run required")
    try:
        receipt = json.loads(a26_raw, object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid A26 execution artifact") from exc
    if not isinstance(receipt, dict) or set(receipt) != _A26_FIELDS:
        raise ValueError("A26 execution artifact schema mismatch")
    if (receipt["schema"] != "prime.a26.a19-role-review.v1"
            or receipt["source_revision"] != source_revision
            or receipt["github_run_id"] != trusted_a26_run["run_id"]
            or receipt["github_run_attempt"] != trusted_a26_run["run_attempt"]
            or receipt["reviewer_agent_id"] != "a26"
            or receipt["subject_agent_id"] != "a19"
            or receipt["case"] != "role:normal"
            or receipt["certification"] != "UNVERIFIED"
            or receipt["decision"] != "PASS"
            or receipt["execution_receipt_sha256"] != observed["execution_receipt_sha256"]
            or receipt["case_spec_sha256"] != observed["case_spec_sha256"]
            or receipt["result_sha256"] != observed["result_sha256"]):
        raise ValueError("A26 decision is not bound to passing A19 execution")
    job, events = receipt["queue_job"], receipt["action_events"]
    correlation = receipt["correlation_id"]
    if not isinstance(job, dict) or not isinstance(events, list):
        raise ValueError("A26 queue and action lineage required")
    result = job.get("result")
    try:
        decision = json.loads(result, object_pairs_hook=_unique) if isinstance(result, str) else None
    except json.JSONDecodeError as exc:
        raise ValueError("invalid A26 result") from exc
    if (not _uuid(job.get("id")) or job["id"] == observed["job_id"]
            or not _uuid(correlation)
            or job.get("agent") != "a26" or job.get("status") != "completed"
            or job.get("provider") != "ollama-deep"
            or job.get("allow_cloud") is not False
            or type(job.get("attempts")) is not int or job["attempts"] != 1
            or not isinstance(result, str)
            or not isinstance(decision, dict)
            or decision != {
                "decision": "PASS",
                "execution_receipt_sha256": observed["execution_receipt_sha256"],
                "case_spec_sha256": observed["case_spec_sha256"],
                "result_sha256": observed["result_sha256"],
            }):
        raise ValueError("A26 independent queue decision failed")
    if (_time(job.get("started_at")) > _time(job.get("completed_at"))
            or _time(job.get("completed_at")) > _time(receipt["reviewed_at"])):
        raise ValueError("A26 review time order invalid")
    if not 4 <= len(events) <= 64 or any(not isinstance(event, dict) for event in events):
        raise ValueError("bounded A26 action lineage required")
    for task_id, action in ((job["id"], "inference.run"),
                            (correlation, "inference.enqueue")):
        matches = [event for event in events if event.get("task_id") == task_id
                   and event.get("action_type") == action and event.get("agent_id") == "a26"]
        if (len(matches) != 2 or {event.get("phase") for event in matches}
                != {"started", "completed"}
                or next(event for event in matches if event["phase"] == "completed").get("success") is not True):
            raise ValueError("A26 action lineage failed")
    envelope = {
        "schema_version": "prime.agent-certification.review.v1",
        "reviewer_identity": "a26",
        "review_run_id": review_run_id,
        "source_revision": source_revision,
        "agent_id": "a19",
        "capability_id": "responsibility.a19",
        "dimension": "role",
        "test_case": "normal",
        "execution_evidence_sha256": observed["execution_receipt_sha256"],
        "test_result": "PASS",
        "review_test_version": REVIEW_TEST_VERSION,
        "observations": {**observed,
                         "a26_receipt_sha256": hashlib.sha256(a26_raw).hexdigest(),
                         "a26_job_id": job["id"],
                         "a26_run_id": trusted_a26_run["run_id"],
                         "a26_run_attempt": trusted_a26_run["run_attempt"]},
    }
    return (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
