"""Offline independent check of one A19 role observation before protected review.

The caller supplies run provenance obtained independently from GitHub, not from
the observation artifact. This code cannot authenticate GitHub, review another
agent's work, sign a record, or award a certification level by itself.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from .agent_cert_role_group_two import review_role_json, role_case


_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WORKFLOW = "AndrewLamSingapore/prime/.github/workflows/a19-offhost-role.yml@refs/heads/main"
_SCHEMA = "prime.a19.offhost-role-normal-observation.v1"
_ORACLE = "group_two_exact_role_oracle/v1"
_FIELDS = {
    "schema", "captured_at", "source_revision", "github_run_id",
    "github_run_attempt", "model", "model_digest", "profile_sha256",
    "case", "challenge", "case_spec_sha256", "observation",
    "correlation_id", "queue_job", "action_events", "lineage_pass",
    "lineage_errors", "role_review_pass", "certification", "scope",
}
_RUN_FIELDS = {
    "repository", "repository_id", "workflow_ref", "ref", "ref_protected",
    "event_name", "head_sha", "run_id", "run_attempt", "conclusion",
    "artifact_sha256",
}


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate observation field")
        result[name] = value
    return result


def _time(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid observation time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid observation time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observation time requires timezone")
    return parsed.astimezone(timezone.utc)


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def review_a19_role_receipt(raw: bytes, *, source_revision: str,
                            trusted_run: Mapping[str, object]) -> dict[str, str]:
    """Recompute A19's role verdict and lineage; reject feature-run provenance.

    ``trusted_run`` must come from an authenticated, protected-side retrieval of
    GitHub run and artifact metadata. A caller assertion is not provenance.
    The returned observations can be placed in a distinct review artifact only
    after an actual independent reviewer accepts the case.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1024 * 1024:
        raise ValueError("bounded execution artifact required")
    if not isinstance(source_revision, str) or not _REVISION.fullmatch(source_revision):
        raise ValueError("exact source revision required")
    if not isinstance(trusted_run, Mapping) or set(trusted_run) != _RUN_FIELDS:
        raise ValueError("independent run provenance required")
    if (trusted_run["repository"] != "AndrewLamSingapore/prime"
            or trusted_run["repository_id"] != "1345668764"
            or trusted_run["workflow_ref"] != _WORKFLOW
            or trusted_run["ref"] != "refs/heads/main"
            or trusted_run["ref_protected"] is not True
            or trusted_run["event_name"] != "workflow_dispatch"
            or trusted_run["head_sha"] != source_revision
            or trusted_run["conclusion"] != "success"
            or not isinstance(trusted_run["artifact_sha256"], str)
            or not _SHA256.fullmatch(trusted_run["artifact_sha256"])
            or trusted_run["artifact_sha256"] != hashlib.sha256(raw).hexdigest()
            or not isinstance(trusted_run["run_id"], str)
            or not trusted_run["run_id"].isdecimal()
            or not isinstance(trusted_run["run_attempt"], str)
            or not trusted_run["run_attempt"].isdecimal()):
        raise ValueError("protected main run or artifact mismatch")
    try:
        item = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid execution artifact") from exc
    if not isinstance(item, dict) or set(item) != _FIELDS:
        raise ValueError("execution artifact schema mismatch")
    if (item["schema"] != _SCHEMA or item["source_revision"] != source_revision
            or item["github_run_id"] != trusted_run["run_id"]
            or item["github_run_attempt"] != trusted_run["run_attempt"]
            or item["case"] != "role:normal" or item["certification"] != "UNVERIFIED"
            or item["lineage_pass"] is not True or item["lineage_errors"] != []
            or item["role_review_pass"] is not True
            or item["model"] != "qwen2.5:1.5b"
            or not isinstance(item["model_digest"], str)
            or not _SHA256.fullmatch(item["model_digest"])
            or not isinstance(item["profile_sha256"], str)
            or not _SHA256.fullmatch(item["profile_sha256"])):
        raise ValueError("execution result or source mismatch")
    expected_case = json.dumps(role_case("a19"), sort_keys=True,
                               separators=(",", ":"))
    case_digest = hashlib.sha256(expected_case.encode()).hexdigest()
    if (item["challenge"] != json.loads(expected_case)
            or item["case_spec_sha256"] != case_digest):
        raise ValueError("A19 challenge changed")
    observed, job, events = item["observation"], item["queue_job"], item["action_events"]
    if not isinstance(observed, dict) or not isinstance(job, dict) or not isinstance(events, list):
        raise ValueError("execution lineage missing")
    job_id, correlation = observed.get("job_id"), item["correlation_id"]
    result = job.get("result")
    if (not _uuid(job_id) or not _uuid(correlation)
            or observed.get("agent_id") != "a19"
            or observed.get("capability_id") != "responsibility.a19"
            or observed.get("case") != "role:normal"
            or observed.get("state") != "EXECUTED"
            or observed.get("certification") != "UNVERIFIED"
            or observed.get("oracle_id") != _ORACLE
            or observed.get("case_spec_sha256") != case_digest
            or observed.get("case_review") != "ROLE_CHECK_PASS"
            or observed.get("review_errors") != []
            or job.get("id") != job_id or job.get("agent") != "a19"
            or job.get("status") != "completed" or job.get("provider") != "ollama-deep"
            or job.get("allow_cloud") is not False
            or type(job.get("attempts")) is not int or job["attempts"] != 1
            or not isinstance(result, str) or not result
            or hashlib.sha256(result.encode()).hexdigest() != observed.get("result_sha256")):
        raise ValueError("worker identity or result mismatch")
    passed, errors = review_role_json("a19", result)
    if not passed or errors:
        raise ValueError("independent A19 role oracle rejected result")
    if (_time(job.get("started_at")) > _time(job.get("completed_at"))
            or _time(job.get("completed_at")) > _time(item["captured_at"])):
        raise ValueError("execution time order invalid")
    if not 4 <= len(events) <= 64 or any(not isinstance(event, dict) for event in events):
        raise ValueError("bounded action lineage required")
    for task_id, action in ((job_id, "inference.run"),
                            (correlation, "inference.enqueue")):
        matches = [event for event in events if event.get("task_id") == task_id
                   and event.get("action_type") == action and event.get("agent_id") == "a19"]
        if (len(matches) != 2 or {event.get("phase") for event in matches}
                != {"started", "completed"}
                or next(event for event in matches if event["phase"] == "completed").get("success") is not True):
            raise ValueError("independent action lineage failed")
    return {
        "execution_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "case_spec_sha256": case_digest,
        "job_id": job_id,
        "result_sha256": observed["result_sha256"],
        "github_run_id": trusted_run["run_id"],
        "github_run_attempt": trusted_run["run_attempt"],
        "oracle_id": _ORACLE,
    }
