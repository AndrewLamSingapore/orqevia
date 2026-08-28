"""Deterministic VELYQUA evidence validation and PRIME result evaluation.

This module is deliberately model-free. It summarizes attributable evidence
without turning observation counts into scientific support or execution
authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

EVENT_TYPES = {
    "experiment_execution.awaiting_owner_approval",
    "experiment_execution.approved_for_observation",
    "experiment_execution.collecting_evidence",
    "experiment_execution.completed",
    "experiment_execution.rejected",
    "observation.recorded",
}
EXECUTION_STATES = {
    "awaiting_owner_approval",
    "approved_for_observation",
    "collecting_evidence",
    "completed",
    "rejected",
}
ALLOWED_TRANSITIONS = {
    "awaiting_owner_approval": {"approved_for_observation", "rejected"},
    "approved_for_observation": {"collecting_evidence"},
    "collecting_evidence": {"completed"},
    "completed": set(),
    "rejected": set(),
}
EVIDENCE_LEVELS = {"raw", "reference", "derived"}
OBSERVATION_KINDS = {
    "sensor",
    "reference_test",
    "care_event",
    "livestock_observation",
    "system_event",
    "derived_result",
}
EXPERIMENT_ID = re.compile(r"PRM-EXP-[A-Z0-9-]+")
OBSERVATION_ID = re.compile(r"VLY-OBS-[A-Z0-9-]+")


def _nonempty(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} is too long")
    return normalized


def _string_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field} must be an array of non-empty strings")
    if required and not value:
        raise ValueError(f"{field} must not be empty")
    return list(dict.fromkeys(item.strip() for item in value))


def _timestamp(value: Any, field: str) -> str:
    text = _nonempty(value, field, maximum=64)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 date-time") from exc
    return text


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_execution(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("execution payload must be an object")
    required = {
        "experiment_id", "candidate_id", "state", "objective",
        "evidence_requirements", "owner_approval", "created_at",
    }
    if set(payload) != required:
        raise ValueError("execution payload fields do not match the version 1.0 contract")
    experiment_id = _nonempty(payload.get("experiment_id"), "experiment_id")
    if not EXPERIMENT_ID.fullmatch(experiment_id):
        raise ValueError("invalid experiment_id")
    state = payload.get("state")
    if state not in EXECUTION_STATES:
        raise ValueError("invalid execution state")
    result = dict(payload)
    result["candidate_id"] = _nonempty(payload.get("candidate_id"), "candidate_id")
    result["objective"] = _nonempty(payload.get("objective"), "objective", maximum=4000)
    result["evidence_requirements"] = _string_list(
        payload.get("evidence_requirements"), "evidence_requirements", required=True
    )
    result["created_at"] = _timestamp(payload.get("created_at"), "created_at")
    approval = payload.get("owner_approval")
    needs_approval = state in {"approved_for_observation", "collecting_evidence", "completed"}
    if needs_approval:
        if not isinstance(approval, dict) or set(approval) != {
            "owner_id", "approved_at", "scope", "provenance"
        }:
            raise ValueError("an auditable owner approval is required")
        if approval.get("scope") != "observation_only":
            raise ValueError("owner approval must be observation_only")
        result["owner_approval"] = {
            "owner_id": _nonempty(approval.get("owner_id"), "owner_id"),
            "approved_at": _timestamp(approval.get("approved_at"), "approved_at"),
            "scope": "observation_only",
            "provenance": _string_list(approval.get("provenance"), "approval provenance", required=True),
        }
    elif approval is not None:
        raise ValueError("unapproved or rejected execution cannot contain owner approval")
    return result


def validate_observation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("observation payload must be an object")
    allowed = {
        "schema_version", "observation_id", "source", "experiment_id", "tank_id",
        "observed_at", "kind", "metric", "value", "unit", "evidence_level",
        "provenance", "notes",
    }
    if set(payload) != allowed:
        raise ValueError("observation payload fields do not match the version 1.0 contract")
    if payload.get("schema_version") != "1.0" or payload.get("source") != "velyqua":
        raise ValueError("unsupported observation identity")
    observation_id = _nonempty(payload.get("observation_id"), "observation_id")
    if not OBSERVATION_ID.fullmatch(observation_id):
        raise ValueError("invalid observation_id")
    experiment_id = _nonempty(payload.get("experiment_id"), "experiment_id")
    if not EXPERIMENT_ID.fullmatch(experiment_id):
        raise ValueError("invalid observation experiment_id")
    if payload.get("kind") not in OBSERVATION_KINDS:
        raise ValueError("invalid observation kind")
    if payload.get("evidence_level") not in EVIDENCE_LEVELS:
        raise ValueError("invalid evidence_level")
    value = payload.get("value")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("invalid observation value")
    if isinstance(value, float) and not (-float("inf") < value < float("inf")):
        raise ValueError("observation value must be finite")
    for field in ("tank_id", "metric", "unit", "notes"):
        if payload.get(field) is not None and not isinstance(payload.get(field), str):
            raise ValueError(f"{field} must be a string or null")
    result = dict(payload)
    result["observed_at"] = _timestamp(payload.get("observed_at"), "observed_at")
    result["provenance"] = _string_list(payload.get("provenance"), "provenance", required=True)
    return result


def validate_velyqua_event(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("event must be an object")
    allowed = {
        "schema_version", "operation_id", "account_id", "aggregate_type",
        "aggregate_id", "event_type", "payload", "occurred_at",
    }
    if set(payload) != allowed:
        raise ValueError("event fields do not match the version 1.0 contract")
    if payload.get("schema_version") != "1.0":
        raise ValueError("schema_version must be 1.0")
    event_type = payload.get("event_type")
    if event_type not in EVENT_TYPES:
        raise ValueError("unsupported event_type")
    result = dict(payload)
    result["operation_id"] = _nonempty(payload.get("operation_id"), "operation_id")
    result["account_id"] = _nonempty(payload.get("account_id"), "account_id")
    result["aggregate_id"] = _nonempty(payload.get("aggregate_id"), "aggregate_id")
    result["occurred_at"] = _timestamp(payload.get("occurred_at"), "occurred_at")
    if event_type.startswith("experiment_execution."):
        if payload.get("aggregate_type") != "experiment_execution":
            raise ValueError("execution event has the wrong aggregate_type")
        execution = validate_execution(payload.get("payload"))
        if execution["experiment_id"] != result["aggregate_id"]:
            raise ValueError("execution aggregate_id does not match experiment_id")
        if event_type != f"experiment_execution.{execution['state']}":
            raise ValueError("execution event_type does not match state")
        result["payload"] = execution
    else:
        if payload.get("aggregate_type") != "observation":
            raise ValueError("observation event has the wrong aggregate_type")
        observation = validate_observation(payload.get("payload"))
        if observation["observation_id"] != result["aggregate_id"]:
            raise ValueError("observation aggregate_id does not match observation_id")
        result["payload"] = observation
    return result


def assert_event_sequence(events: list[dict[str, Any]]) -> None:
    state: str | None = None
    approved = False
    for event in events:
        if event["event_type"].startswith("experiment_execution."):
            execution = event["payload"]
            next_state = execution["state"]
            if state is None:
                if next_state not in {"awaiting_owner_approval", "rejected"}:
                    raise ValueError("an experiment must begin awaiting owner approval or rejected")
            elif next_state != state and next_state not in ALLOWED_TRANSITIONS[state]:
                raise ValueError(f"invalid execution transition: {state} -> {next_state}")
            state = next_state
            approval = execution.get("owner_approval") or {}
            approved = approval.get("scope") == "observation_only"
        else:
            if state not in {"collecting_evidence", "completed"} or not approved:
                raise ValueError("observations require an owner-approved collecting-evidence execution")


def build_portal_result(
    candidate: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if not events:
        raise ValueError("at least one VELYQUA event is required")
    assert_event_sequence(events)
    executions = [event["payload"] for event in events if event["event_type"].startswith("experiment_execution.")]
    observations = [event["payload"] for event in events if event["event_type"] == "observation.recorded"]
    latest_state = executions[-1]["state"] if executions else "awaiting_owner_approval"
    status = latest_state
    if latest_state == "completed":
        conclusion = "evidence_collected" if observations else "completed_without_observations"
    elif latest_state == "rejected":
        conclusion = "rejected_by_owner"
    else:
        conclusion = "evaluation_pending"
    levels = {level: sum(1 for item in observations if item["evidence_level"] == level) for level in sorted(EVIDENCE_LEVELS)}
    observation_times = sorted(item["observed_at"] for item in observations)
    experiment_id = executions[-1]["experiment_id"] if executions else events[-1]["payload"]["experiment_id"]
    candidate_id = _nonempty(candidate.get("candidate_id"), "candidate_id")
    version = len(events)
    result_id = "PRM-RES-" + hashlib.sha256(f"{experiment_id}:{version}".encode()).hexdigest()[:16].upper()
    return {
        "schema_version": "1.0",
        "result_id": result_id,
        "result_version": version,
        "source": "prime",
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "node_ids": list(candidate.get("node_ids") or []),
        "status": status,
        "conclusion": conclusion,
        "evidence_summary": {
            "observation_count": len(observations),
            "evidence_levels": levels,
            "provenance_complete": all(bool(item.get("provenance")) for item in observations),
            "first_observed_at": observation_times[0] if observation_times else None,
            "last_observed_at": observation_times[-1] if observation_times else None,
        },
        "safety": {
            "actuation_authorized": False,
            "owner_approval_inferred": False,
            "scientific_support_claimed": False,
        },
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }


def canonical_event(payload: dict[str, Any]) -> str:
    return _canonical(validate_velyqua_event(payload))
