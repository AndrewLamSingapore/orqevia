"""Bounded Objective Store -> Evidence Ledger projection; not a truth authority."""
from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from . import objective_api
from .evidence_product import (EvidenceLedger, canonical_bytes, content_digest,
    OBSERVATION_PAYLOAD_BYTES, ObservationBudgetExceeded, observation_remaining)

NAMESPACE = "prime-objective"


def _task(task_id: str, authorization: str, *, read_only=False):
    try:
        if str(UUID(task_id)) != task_id:
            raise ValueError("noncanonical task id")
    except ValueError:
        raise HTTPException(404, "Objective not found") from None
    return objective_api.get_read_only(task_id, authorization) if read_only else objective_api.get(task_id, authorization)


def _ledger():
    return EvidenceLedger(_ledger_path())


def _ledger_path():
    return Path(os.getenv("PRIME_DATA_DIR", "/data")) / "evidence-lens.db"


def _snapshot(task: dict) -> dict:
    metadata = task["execution_metadata"]
    return {
        "task_id": task["id"],
        "revision": task["revision"],
        "execution_state": task["state"],
        "result_digest": content_digest(canonical_bytes(task.get("result"))),
        "metadata_digest": content_digest(canonical_bytes(metadata)),
        "claim_verification": (task.get("result") or {}).get("verification_status", "UNKNOWN"),
        "runtime": metadata["runtime"],
        "agent_ids": sorted({item["selected_agent_id"] for item in metadata["agent_execution"]
                             if item.get("selected_agent_id") and item.get("registry_binding") == "VERIFIED"}),
        "completed_at": metadata.get("completed_at"),
        "inference_attempts": metadata.get("inference_attempts", {
            "status": "UNAVAILABLE", "attempts": [], "verification": "UNVERIFIED"}),
    }


def _read(ledger: EvidenceLedger, task: dict) -> dict:
    record_id = f"objective:{task['id']}:r{task['revision']}"
    try:
        envelope = ledger.get(record_id, namespace=NAMESPACE)
    except KeyError:
        raise HTTPException(404, "Evidence projection not found") from None
    integrity = ledger.verify_chain(record_id, namespace=NAMESPACE)
    if ledger.observation_deadline is not None:
        observation_remaining(ledger.observation_deadline)
        if (type(envelope) is not dict or integrity.get('envelope_digest') != content_digest(canonical_bytes(envelope))['value']
                or type(envelope.get('observations')) is not list
                or len(envelope['observations']) != 1
                or type(envelope['observations'][0]) is not dict
                or type(envelope['observations'][0].get('value')) is not dict):
            return {'record_id': record_id, 'integrity': 'INVALID', 'currentness': 'UNKNOWN',
                    'verification': 'UNVERIFIED'}
    observations = envelope.get("observations", [])
    expected_actor = {"type": "SYSTEM", "id": "PRIME_OBJECTIVE_STORE"}
    expected_authority = {"scope": "objective.result.projection", "source": "PRIME_OBJECTIVE_STORE"}
    expected_inputs = [{"task_id": task["id"], "revision": task["revision"]}]
    bound = (envelope.get("action_id") == record_id
             and envelope.get("actor") == expected_actor
             and envelope.get("authority") == expected_authority
             and envelope.get("inputs") == expected_inputs
             and len(observations) == 1
             and observations[0].get("observation_id") == f"obs:{record_id}"
             and observations[0].get("source") == "PRIME_OBJECTIVE_STORE")
    if integrity["verdict"] != "VALID" or not bound:
        return {"record_id": record_id, "integrity": "INVALID", "currentness": "UNKNOWN",
                "verification": "UNVERIFIED"}
    observed = observations[0]["value"]
    current = _snapshot(task)
    runtime = observed.get("runtime") or {}
    # Runtime fields are captured from the Objective Store, which obtains them
    # from environment metadata. Presence is not independent deployment proof.
    unproven = ["independent_claim_verification", "production_acceptance",
                "time_freshness", "source_revision_binding", "runtime_image_binding"]
    return {"record_id": record_id, "task_id": task["id"], "revision": task["revision"],
            "integrity": "VALID", "currentness": "CURRENT" if observed == current else "STALE",
            "verification": "UNVERIFIED", "source": "PRIME_OBJECTIVE_STORE",
            "result_state": observed["execution_state"], "observed": observed,
            "ledger_head": integrity["head"],
            "proof": {"producer": observations[0].get("source", "UNKNOWN"),
                      "captured_at": observations[0].get("observed_at"),
                      "completed_at": observed.get("completed_at"),
                      "currentness_basis": "OBJECTIVE_SNAPSHOT_EQUALITY",
                      "time_freshness": "UNKNOWN",
                      "runtime": runtime,
                      "unproven": unproven}}


def materialize(task_id: str, authorization: str) -> dict:
    task = _task(task_id, authorization)
    if task.get("state") not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise HTTPException(409, "Objective is not terminal")
    metadata = task.get("execution_metadata")
    if not isinstance(metadata, dict) or metadata.get("task_id") != task_id:
        raise HTTPException(409, "Objective metadata is not bound")
    ledger = _ledger()
    record_id = f"objective:{task_id}:r{task['revision']}"
    def bind(envelope):
        envelope["observations"].append({"observation_id": f"obs:{record_id}",
            "source": "PRIME_OBJECTIVE_STORE", "value": _snapshot(task),
            "observed_at": objective_api.utcnow(), "verification_ref": None})
        envelope["verification"] = {"state": "UNVERIFIED", "evidence": [f"obs:{record_id}"]}
        envelope["status"] = "FAILED" if task["state"] == "COMPLETED_WITH_FAILURES" else "COMPLETED"
        envelope["completed_at"] = objective_api.utcnow()

    try:
        ledger.create(namespace=NAMESPACE, objective=f"Objective result {task_id}",
                      actor={"type": "SYSTEM", "id": "PRIME_OBJECTIVE_STORE"},
                      authority={"scope": "objective.result.projection", "source": "PRIME_OBJECTIVE_STORE"},
                      inputs=[{"task_id": task_id, "revision": task["revision"]}],
                      action_id=record_id, idempotency_key=f"lens:create:{record_id}")
        ledger.mutate(record_id, namespace=NAMESPACE, event_type="OBJECTIVE_RESULT_OBSERVED",
                      idempotency_key=f"lens:observe:{record_id}", apply=bind)
    except ValueError as exc:
        if str(exc).startswith("LEDGER_INTEGRITY:"):
            raise HTTPException(409, "Evidence integrity conflict") from None
        raise
    return _read(ledger, task)


def read(task_id: str, authorization: str, *, observation_deadline=None, task=None) -> dict:
    if observation_deadline is None:
        if task is not None:raise ValueError('OBSERVATION_TASK_REQUIRES_BUDGET')
        task = _task(task_id, authorization, read_only=True)
    else:
        from .client_auth import authenticate_owner
        authenticate_owner(authorization)
        observation_remaining(observation_deadline)
        try:
            canonical = str(UUID(task_id)) == task_id
        except (ValueError, TypeError, AttributeError):
            canonical = False
        if not canonical:raise HTTPException(404, 'Objective not found')
        if task is None:
            task = objective_api.get_read_only(task_id, authorization, observation_deadline=observation_deadline)
        metadata = task.get('execution_metadata') if type(task) is dict else None
        if (type(task) is not dict or task.get('id') != task_id or type(task.get('revision')) is not int
                or type(metadata) is not dict or metadata.get('task_id') != task_id
                or type(metadata.get('revision')) is not int or metadata['revision'] != task['revision']
                or metadata.get('authoritative') is not True):
            raise ObservationBudgetExceeded('OBSERVATION_TASK_BINDING_INVALID')
        if len(canonical_bytes(task)) > OBSERVATION_PAYLOAD_BYTES:
            raise ObservationBudgetExceeded('OBSERVATION_TASK_PAYLOAD_EXCEEDED')
        observation_remaining(observation_deadline)
    if not _ledger_path().is_file():
        raise HTTPException(404, "Evidence projection not found")
    result = _read(EvidenceLedger(_ledger_path(), read_only=True, observation_deadline=observation_deadline), task)
    if observation_deadline is not None:observation_remaining(observation_deadline)
    return result
