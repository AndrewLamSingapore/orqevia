"""Protected API and executors for PRIME's governed shared job queue."""
from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from .agent_registry import RegistryError, canonical_agent_id
from .action_harness import HarnessPolicy
from .settings import SETTINGS
from .compute_ledger import ComputeLedger
from .deterministic_compute import assess

router = APIRouter(prefix="/api/compute-queue", tags=["governed-compute"])
DATA = Path(os.getenv("PRIME_DATA_DIR", "/data"))
POLICY = QueuePolicy.from_env()
if os.getenv("PRIME_HARNESS_PILOT_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
    # The pilot is deliberately single-slot even if an older host Compose file
    # still injects the pre-pilot concurrency value.
    POLICY = replace(POLICY, global_concurrency=1, per_agent_concurrency=1)
queue = JobQueue(os.getenv("PRIME_COMPUTE_QUEUE_DB", str(DATA / "compute-queue.db")), POLICY)


def _int(name: str, default: int) -> int:
    try: return max(0, int(os.getenv(name, str(default))))
    except ValueError: return default


def providers() -> list[Provider]:
    local_ram,local_vram=_int("PRIME_LOCAL_RAM_MB",32768),_int("PRIME_LOCAL_VRAM_MB",0)
    result=[]
    for role,model in (("fast",SETTINGS.fast_model),("deep",SETTINGS.deep_model),
                       ("evaluator",SETTINGS.evaluator_model),("embedding",SETTINGS.embedding_model)):
        if model and not any(p.model==model for p in result):
            result.append(Provider(f"ollama-{role}","local",model,local_ram,local_vram,
                                   1))
    return result


def _execute(job: dict, provider: Provider) -> dict:
    # The production worker has no inference path around this boundary.
    from .harness_execution import execute_job
    from . import harness_api, spine_api
    harness, _ = harness_api._runtime()
    return execute_job(job, provider, harness, spine_api.spine, _infer, queue=queue)


def _infer(job: dict, provider: Provider) -> dict:
    from .inference_boundary import require_worker_call, InferenceBoundaryError
    require_worker_call(job)
    if provider.kind != "local":
        raise InferenceBoundaryError("cloud overflow is disabled")
    if SETTINGS.ollama_base_url != "http://ollama:11434":
        raise InferenceBoundaryError("inference requires the isolated Docker Ollama endpoint")
    route = assess(job["prompt"])
    if route.resolution_path != "local_inference":
        raise InferenceBoundaryError("deterministic feasibility forbids inference for this contract")
    timeout=httpx.Timeout(float(job["timeout_seconds"]))
    started = time.monotonic()
    ledger = ComputeLedger()  # Establish the telemetry store before transport.
    usage = {"input_tokens": None, "output_tokens": None}
    success = False
    error_type = None
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            r=client.post(f"{SETTINGS.ollama_base_url}/api/chat",json={"model":provider.model,
                "messages":[{"role":"user","content":job["prompt"]}],"stream":False,
                "keep_alive":SETTINGS.keep_alive,"options":{"num_ctx":SETTINGS.context_tokens,
                "num_predict":SETTINGS.max_output_tokens}})
            r.raise_for_status(); payload=r.json()
        usage = {"input_tokens": _token_count(payload.get("prompt_eval_count")),
                 "output_tokens": _token_count(payload.get("eval_count"))}
        result = payload.get("message", {}).get("content")
        if not isinstance(result, str) or not result.strip():
            raise ValueError("provider returned no answer")
        success = True
        return {"result": result, **usage, "actual_cost_usd": 0}
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        ledger.record(
            task_id=job["id"], stage="harness_inference", provider="ollama", model=provider.model,
            latency_ms=int((time.monotonic() - started) * 1000), success=success,
            input_units=usage["input_tokens"], output_units=usage["output_tokens"],
            metadata={"event_kind": "model_invocation", "agent_id": job["agent"],
                      "inference_tier": provider.name.removeprefix("ollama-"), "cached_tokens": None,
                      "resolution_path": "local_inference", "routing_reason": route.reason_code,
                      "provider_route_reason": job.get("route_reason"),
                      "model_invocations": 1 if success else None, "model_attempts": 1,
                      "agent_invocations": 1, "error_type": error_type},
        )


def _token_count(value):
    # Missing, fractional, negative and malformed usage is unavailable, not 0.
    return value if type(value) is int and value >= 0 else None



pool=WorkerPool(queue,providers(),_execute)


def authorize(authorization: str | None) -> None:
    expected=os.getenv("PRIME_SPINE_TOKEN","").strip()
    if not expected or authorization != f"Bearer {expected}": raise HTTPException(401,"Owner token required")


class SubmitJob(BaseModel):
    agent: str=Field(min_length=1,max_length=80)
    prompt: str=Field(min_length=1,max_length=120000)
    priority: str|int="normal"
    model_role: str="auto"
    model: str=""
    ram_mb: int=Field(default=1024,ge=0,le=1048576)
    vram_mb: int=Field(default=0,ge=0,le=1048576)
    timeout_seconds: int=Field(default=300,ge=1,le=86400)
    max_retries: int=Field(default=2,ge=0,le=10)
    max_cost_usd: float=Field(default=0,ge=0)
    allow_cloud: bool=False
    external_execution: bool=False


class Approval(BaseModel):
    decision: str
    reason: str=""


@router.post("/jobs",status_code=202)
def submit_job(body: SubmitJob,authorization: str|None=Header(None)):
    authorize(authorization)
    if os.getenv("PRIME_HARNESS_PILOT_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
        raise HTTPException(409, "Direct dispatch is disabled during the three-agent Harness pilot")
    try:
        canonical = canonical_agent_id(body.agent)
    except RegistryError:
        canonical = body.agent.strip().lower()
    if canonical in HarnessPolicy().pilot_agents:
        raise HTTPException(409,"Pilot agents must dispatch through /api/harness/pilot/dispatch")
    try:return queue.submit(**body.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.get("/jobs")
def list_jobs(status: str|None=None,limit: int=100,authorization: str|None=Header(None)):
    authorize(authorization);return {"jobs":[_public_job(job) for job in queue.list(status,max(1,min(500,limit)))]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return _public_job(queue.get(job_id))
    except KeyError:raise HTTPException(404,"Job not found")


@router.post("/jobs/{job_id}/approval")
def decide_job(job_id: str,body: Approval,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return queue.approve(job_id,body.decision,"owner",body.reason)
    except KeyError:raise HTTPException(404,"Job not found")
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.get("/metrics")
def metrics(authorization: str|None=Header(None)):
    authorize(authorization);return {**queue.metrics(),"providers":[p.__dict__ for p in providers()],
                                   "worker_health": pool.health()}


def _public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key != "authorization_envelope"}


def start_compute_queue() -> None: pool.start()
def stop_compute_queue() -> None: pool.stop()
