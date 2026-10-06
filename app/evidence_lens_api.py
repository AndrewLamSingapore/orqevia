"""Bounded Objective Store -> Evidence Ledger projection; not a truth authority."""
from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from . import objective_api
from .evidence_product import EvidenceLedger, canonical_bytes, content_digest

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
    }


def _read(ledger: EvidenceLedger, task: dict) -> dict:
    record_id = f"objective:{task['id']}:r{task['revision']}"
    try:
        envelope = ledger.get(record_id, namespace=NAMESPACE)
    except KeyError:
        raise HTTPException(404, "Evidence projection not found") from None
    integrity = ledger.verify_chain(record_id, namespace=NAMESPACE)
    observations = envelope.get("observations", [])
    if integrity["verdict"] != "VALID" or len(observations) != 1:
        return {"record_id": record_id, "integrity": "INVALID", "currentness": "UNKNOWN",
                "verification": "UNVERIFIED"}
    observed = observations[0]["value"]
    current = _snapshot(task)
    return {"record_id": record_id, "task_id": task["id"], "revision": task["revision"],
            "integrity": "VALID", "currentness": "CURRENT" if observed == current else "STALE",
            "verification": "UNVERIFIED", "source": "PRIME_OBJECTIVE_STORE",
            "result_state": observed["execution_state"], "observed": observed,
            "ledger_head": integrity["head"]}


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


def read(task_id: str, authorization: str) -> dict:
    task = _task(task_id, authorization, read_only=True)
    if not _ledger_path().is_file():
        raise HTTPException(404, "Evidence projection not found")
    return _read(EvidenceLedger(_ledger_path(), read_only=True), task)
