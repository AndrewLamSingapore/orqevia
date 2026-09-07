"""Live, owner-authenticated Harness v0 pilot dispatch surface."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app import compute_queue_api, spine_api
from app.action_harness import (
    ActionEnvelopeIssuer,
    ActionHarness,
    HarnessPolicy,
    HarnessUnavailable,
    HarnessedExecutor,
)

router = APIRouter(prefix="/api/harness", tags=["action-harness"])
_runtime_cache: tuple[ActionHarness, ActionEnvelopeIssuer] | None = None
_runtime_fingerprint: tuple[str, str, str] | None = None


def _enabled() -> bool:
    return os.getenv("PRIME_HARNESS_PILOT_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _runtime() -> tuple[ActionHarness, ActionEnvelopeIssuer]:
    global _runtime_cache, _runtime_fingerprint
    if not _enabled():
        raise HTTPException(status_code=503, detail="Harness v0 pilot is disabled")
    token = os.getenv("PRIME_SPINE_TOKEN", "").strip()
    explicit = os.getenv("PRIME_HARNESS_SIGNING_SECRET", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Stable Spine authority is not configured")
    secret = explicit.encode() if explicit else hashlib.sha256(
        b"JARVIS-HARNESS-V0\0" + token.encode()
    ).digest()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Harness signing secret must contain at least 32 bytes")
    db_path = os.getenv(
        "PRIME_HARNESS_DB",
        str(Path(os.getenv("PRIME_DATA_DIR", "/data")) / "action-harness.db"),
    )
    version = os.getenv("PRIME_HARNESS_POLICY_VERSION", "harness-v0").strip() or "harness-v0"
    fingerprint = (db_path, version, hashlib.sha256(secret).hexdigest())
    if _runtime_cache is None or _runtime_fingerprint != fingerprint:
        policy = HarnessPolicy(policy_version=version)
        issuer = ActionEnvelopeIssuer(secret, key_id="prime-authority-v0")
        harness = ActionHarness(db_path, {issuer.key_id: secret}, policy)
        _runtime_cache, _runtime_fingerprint = (harness, issuer), fingerprint
    return _runtime_cache


class PilotDispatch(BaseModel):
    actor_id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=120000)
    priority: Literal["background", "low", "normal", "high", "critical"] = "normal"
    model_role: Literal["auto", "fast", "deep", "embedding", "evaluator"] = "auto"
    ram_mb: int = Field(default=1024, ge=0, le=1048576)
    vram_mb: int = Field(default=0, ge=0, le=1048576)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    max_retries: int = Field(default=2, ge=0, le=10)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)


@router.get("/status")
def status(authorization: str | None = Header(default=None)):
    spine_api.require_token(authorization)
    harness, _ = _runtime()
    with harness.connect() as db:
        counts = {
            "authorized": db.execute("select count(*) from harness_decisions").fetchone()[0],
            "executed": db.execute("select count(*) from harness_executions").fetchone()[0],
            "revoked": db.execute("select count(*) from harness_revocations").fetchone()[0],
        }
    return {
        "ready": True,
        "mode": "pilot-local-only",
        "policy_version": harness.policy_version,
        "pilot_agents": sorted(harness.policy.pilot_agents),
        "cloud_overflow": False,
        "local_concurrency": compute_queue_api.queue.policy.global_concurrency,
        "counts": counts,
    }


@router.post("/pilot/dispatch", status_code=202)
def dispatch(body: PilotDispatch, authorization: str | None = Header(default=None)):
    spine_api.require_token(authorization)
    harness, issuer = _runtime()
    actor = body.actor_id.strip().lower()
    if actor not in harness.policy.pilot_agents:
        raise HTTPException(status_code=403, detail="Actor is outside the Harness v0 pilot")

    now = datetime.now(timezone.utc)
    decision_id = f"spine:{uuid.uuid4()}"
    parameters = {
        "prompt_sha256": hashlib.sha256(body.prompt.encode()).hexdigest(),
        "priority": body.priority,
        "model_role": body.model_role,
        "ram_mb": body.ram_mb,
        "vram_mb": body.vram_mb,
        "timeout_seconds": body.timeout_seconds,
        "max_retries": body.max_retries,
        "allow_cloud": False,
        "external_execution": False,
    }
    proposal = {
        "tenant_id": "personal",
        "actor_id": actor,
        "actor_type": "reasoner",
        "action": "agent.infer",
        "parameters": parameters,
        "context": {
            "risk": "advisory",
            "source": "harness_v0_pilot",
            "external_execution": False,
            "policy_limits": {"cloud": False, "local_concurrency": 1},
        },
        "correlation_id": body.correlation_id,
        "idempotency_key": body.idempotency_key,
        "schema_version": "1.0.0",
        "timestamp": now.isoformat(),
    }
    spine_result = spine_api.spine.evaluate(
        proposal,
        {"source": "harness_v0_pilot", "decision_id": decision_id},
    )
    if not spine_result.get("ok"):
        raise HTTPException(
            status_code=int(spine_result.get("status", 422)),
            detail=spine_result.get("error", "Stable Spine rejected the proposal"),
        )
    if spine_result.get("idempotent_replay"):
        raise HTTPException(status_code=409, detail="Idempotency key was already evaluated")
    if spine_result.get("execution_status") != "AUTHORIZED":
        raise HTTPException(
            status_code=int(spine_result.get("status", 403)),
            detail="Stable Spine did not authorize this dispatch",
        )

    envelope = issuer.issue(
        proposal,
        decision_id=decision_id,
        policy_version=harness.policy_version,
        ttl_seconds=min(300, harness.policy.max_ttl_seconds),
        privileged=False,
        now=now,
    )
    decision = harness.authorize(envelope, now=now)
    if not decision.authorized:
        raise HTTPException(status_code=403, detail=decision.reason)

    def enqueue(signed_envelope):
        signed = signed_envelope["parameters"]
        if signed["prompt_sha256"] != hashlib.sha256(body.prompt.encode()).hexdigest():
            raise PermissionError("prompt does not match the signed envelope")
        return compute_queue_api.queue.submit(
            agent=actor,
            prompt=body.prompt,
            priority=signed["priority"],
            model_role=signed["model_role"],
            ram_mb=signed["ram_mb"],
            vram_mb=signed["vram_mb"],
            timeout_seconds=signed["timeout_seconds"],
            max_retries=signed["max_retries"],
            max_cost_usd=0,
            allow_cloud=False,
            external_execution=False,
        )

    try:
        job = HarnessedExecutor(harness, enqueue).execute(envelope, now=now)
    except HarnessUnavailable as exc:
        raise HTTPException(status_code=503, detail="Harness ledger unavailable") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "job": {key: job[key] for key in ("id", "agent", "status", "priority", "model_role", "created_at")},
        "harness": {
            "status": "EXECUTION_PERMITTED",
            "lease_id": decision.lease_id,
            "decision_id": decision_id,
            "policy_version": harness.policy_version,
        },
        "correlation_id": body.correlation_id,
        "cloud_allowed": False,
    }
