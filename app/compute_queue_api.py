"""Protected API and executors for PRIME's governed shared job queue."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from .agent_registry import RegistryError, canonical_agent_id
from .action_harness import HarnessPolicy
from .settings import SETTINGS

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
                                   _int("OLLAMA_NUM_PARALLEL",2) or 1))
    url=os.getenv("PRIME_CLOUD_GPU_URL","").strip()
    key=os.getenv("PRIME_CLOUD_GPU_API_KEY","").strip()
    model=os.getenv("PRIME_CLOUD_GPU_MODEL","").strip()
    if url and key and model:
        result.append(Provider("cloud-gpu","cloud",model,_int("PRIME_CLOUD_GPU_RAM_MB",131072),
            _int("PRIME_CLOUD_GPU_VRAM_MB",81920),_int("PRIME_CLOUD_GPU_CONCURRENCY",2) or 1,
            float(os.getenv("PRIME_CLOUD_INPUT_USD_MTOK","0") or 0),
            float(os.getenv("PRIME_CLOUD_OUTPUT_USD_MTOK","0") or 0)))
    return result


def _execute(job: dict, provider: Provider) -> dict:
    timeout=httpx.Timeout(float(job["timeout_seconds"]))
    if provider.kind=="local":
        with httpx.Client(timeout=timeout) as client:
            r=client.post(f"{SETTINGS.ollama_base_url}/api/chat",json={"model":provider.model,
                "messages":[{"role":"user","content":job["prompt"]}],"stream":False,
                "keep_alive":SETTINGS.keep_alive,"options":{"num_ctx":SETTINGS.context_tokens,
                "num_predict":SETTINGS.max_output_tokens}})
            r.raise_for_status(); payload=r.json()
        return {"result":payload.get("message",{}).get("content",""),
                "input_tokens":int(payload.get("prompt_eval_count",0) or 0),
                "output_tokens":int(payload.get("eval_count",0) or 0),"actual_cost_usd":0}
    # Cloud is OpenAI-chat-compatible and is impossible to reach unless the queue
    # has already recorded explicit approval and a deterministic fallback reason.
    base=os.environ["PRIME_CLOUD_GPU_URL"].rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        r=client.post(f"{base}/chat/completions",headers={"Authorization":f"Bearer {os.environ['PRIME_CLOUD_GPU_API_KEY']}"},
                      json={"model":provider.model,"messages":[{"role":"user","content":job["prompt"]}],
                            "max_tokens":SETTINGS.max_output_tokens})
        r.raise_for_status();payload=r.json()
    usage=payload.get("usage",{});inp=int(usage.get("prompt_tokens",0) or 0);out=int(usage.get("completion_tokens",0) or 0)
    cost=(inp*provider.input_cost_per_mtok+out*provider.output_cost_per_mtok)/1_000_000
    return {"result":payload.get("choices",[{}])[0].get("message",{}).get("content",""),
            "input_tokens":inp,"output_tokens":out,"actual_cost_usd":cost}


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
    authorize(authorization);return {"jobs":queue.list(status,max(1,min(500,limit)))}


@router.get("/jobs/{job_id}")
def get_job(job_id: str,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return queue.get(job_id)
    except KeyError:raise HTTPException(404,"Job not found")


@router.post("/jobs/{job_id}/approval")
def decide_job(job_id: str,body: Approval,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return queue.approve(job_id,body.decision,"owner",body.reason)
    except KeyError:raise HTTPException(404,"Job not found")
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.get("/metrics")
def metrics(authorization: str|None=Header(None)):
    authorize(authorization);return {**queue.metrics(),"providers":[p.__dict__ for p in providers()]}


def start_compute_queue() -> None: pool.start()
def stop_compute_queue() -> None: pool.stop()
