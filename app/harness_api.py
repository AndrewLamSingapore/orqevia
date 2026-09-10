"""Live, owner-authenticated Harness v0 pilot dispatch surface."""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.compute_ledger import ComputeLedger
from app.deterministic_compute import assess

from app import compute_queue_api, spine_api
from app.action_harness import (
    ActionEnvelopeIssuer,
    ActionHarness,
    HarnessPolicy,
    HarnessUnavailable,
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
    max_retries: int = Field(default=0, ge=0, le=0)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)


@router.get("/status")
def status(authorization: str | None = Header(default=None)):
    spine_api.require_token(authorization)
    harness, _ = _runtime()
    with harness.connect() as db:
        counts = {
            "authorized": db.execute("select count(*) from harness_decisions").fetchone()[0],
            "started": db.execute("select count(*) from harness_jobs where state in ('started','completed','verified','uncertain')").fetchone()[0],
            "queued": db.execute("select count(*) from harness_jobs where state='queued'").fetchone()[0],
            "claimed": db.execute("select count(*) from harness_jobs where state='claimed'").fetchone()[0],
            "failed": db.execute("select count(*) from harness_jobs where state='failed'").fetchone()[0],
            "completed": db.execute("select count(*) from harness_jobs where state in ('completed','verified')").fetchone()[0],
            "verified": db.execute("select count(*) from harness_jobs where state='verified'").fetchone()[0],
            "uncertain": db.execute("select count(*) from harness_jobs where state='uncertain'").fetchone()[0],
            "legacy_consumed": db.execute("select count(*) from harness_executions where lease_id not in (select lease_id from harness_jobs)").fetchone()[0],
            "revoked": db.execute("select count(*) from harness_revocations").fetchone()[0],
        }
    return {
        "ready": True,
        "acceptance_ready": False,
        "acceptance_status": "operator_pilot_acceptance_pending",
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
    if body.actor_id.strip().lower() not in HarnessPolicy().pilot_agents:
        raise HTTPException(status_code=403, detail="Actor is outside the Harness v0 pilot")
    started = time.monotonic()
    route = assess(body.prompt)
    if route.resolution_path in {"deterministic", "reject"}:
        # Pure computation has no privileged side effect and needs no inference
        # lease. Record hashes only; do not retain the request/result payload.
        try:
            ComputeLedger().record(
                task_id=body.correlation_id, stage="feasibility", provider="deterministic",
                model="none", latency_ms=int((time.monotonic() - started) * 1000), success=route.resolution_path == "deterministic",
                input_units=0, output_units=0, estimated_cost_usd=0,
                metadata={**route.as_dict(), "result": None, "event_kind": "routing_decision",
                          "model_invocations": 0, "agent_invocations": 0,
                          "input_sha256": hashlib.sha256(body.prompt.encode()).hexdigest(),
                          "result_sha256": hashlib.sha256((route.result or "").encode()).hexdigest()},
            )
        except Exception as exc:
            raise HTTPException(503, "Routing ledger unavailable") from exc
        return JSONResponse(status_code=200 if route.result is not None else 422, content={
            "ok": route.result is not None, "routing": route.as_dict(),
            "result": route.result, "correlation_id": body.correlation_id,
            "model_invocations": 0, "input_tokens": 0, "output_tokens": 0,
            "action_authority": False,
        })
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
        # A consumed authorization is never retried automatically.
        "max_retries": 0,
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
    decision = harness.authorize(envelope)
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
            authorization_envelope=signed_envelope,
            on_queued=harness.bind_queued,
        )

    try:
        job = enqueue(envelope)
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
            "status": "QUEUED",
            "lease_id": decision.lease_id,
            "decision_id": decision_id,
            "policy_version": harness.policy_version,
        },
        "correlation_id": body.correlation_id,
        "cloud_allowed": False,
        "routing": route.as_dict(),
    }


class IntentRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=120000)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200)


@router.post("/intent", status_code=202)
def submit_intent(body: IntentRequest, authorization: str | None = Header(default=None)):
    """Select one admitted pilot role; the existing PDP/PEP still govern dispatch."""
    spine_api.require_token(authorization)
    normalized = body.intent.strip().lower().rstrip(".?!")
    continue_requests = {"continue my highest-priority work", "continue my highest priority work",
                         "continue the highest-priority work", "continue the highest priority work"}
    if normalized in {"check prime", "what needs my attention", "show me what was completed",
                      "fix the problem"} | continue_requests:
        from .operator_health import snapshot
        result = snapshot()
        result.pop("diagnostics", None)
        continuation = {}
        if normalized in continue_requests:
            work = result.get("work", {})
            if not result.get("work_available"):
                message = "I could not verify the recorded work. Nothing has been resubmitted."
                next_action = "WAIT_FOR_VERIFIED_WORK_STATE"
            elif not result.get("ready_for_local_work"):
                message = "Recorded work remains in place. PRIME must pass its readiness checks before it can continue safely."
                next_action = "WAIT_FOR_READINESS"
            elif work.get("running", 0) or work.get("queued", 0):
                message = "The existing scheduler is handling eligible recorded work in priority order. I have not created duplicate work."
                next_action = "EXISTING_SCHEDULER"
            else:
                message = "There is no eligible recorded work to continue. You can give me a new bounded goal or question."
                next_action = "NO_ELIGIBLE_WORK"
            continuation = {"result": message, "next_automatic_action": next_action,
                            "priority_order": ["Work", "Web3", "VELYQUA"],
                            "resubmitted": False}
        return JSONResponse(status_code=200, content={"ok": True, "status": result,
            **continuation,
            "resolution_path": "deterministic", "reason_code": "READ_ONLY_OPERATING_STATUS",
            "model_invocations": 0, "action_authority": False,
            "note": "Existing authorized work is managed by the scheduler. This check does not retry uncertain work or grant new authority."})
    if normalized in {"work on web3", "continue velyqua"}:
        return JSONResponse(status_code=409, content={"ok": False, "resolution_path": "reject",
            "reason_code": "DEPENDENT_PHASE_EVIDENCE_REQUIRED", "model_invocations": 0,
            "action_authority": False,
            "required": "Web3 model-tier policy artifact" if "web3" in normalized else "VELYQUA current gate evidence and bounded workload",
            "note": "This work remains gated; no policy, evidence or authorization has been invented."})
    import re
    words = set(re.findall(r"[a-z]+", body.intent.lower()))
    actor = "a21" if words & {"cost", "costs", "budget", "pricing"} else (
        "a14" if words & {"dataset", "duplicates", "duplicate", "missing", "quality"} else "a16"
    )
    return dispatch(PilotDispatch(actor_id=actor, prompt=body.intent,
                                 correlation_id=body.correlation_id,
                                 idempotency_key=body.idempotency_key), authorization)
