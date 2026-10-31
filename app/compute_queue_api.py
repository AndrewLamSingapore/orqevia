"""Protected API and executors for ORQEVIA's governed shared job queue."""
from __future__ import annotations

from asyncio import CancelledError
import os
import json
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import replace
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict, model_validator

from .job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from .agent_registry import registered_agent_ids
from .observability import record_counter, record_duration, span
from .settings import SETTINGS
from .compute_profile import validate_configuration, require_compute_capacity, generation_options, runtime_compute_profile
from . import open_access

router = APIRouter(prefix="/api/compute-queue", tags=["governed-compute"])
DATA = Path(os.getenv("ORQEVIA_DATA_DIR", "/data"))
def candidate_global_concurrency(environment: dict[str, str], profile: dict | None) -> int:
    """Allow at most three slots with explicit backend and measured-envelope support.

    The production default stays at one; unsupported or malformed overrides
    fail closed to one. Per-agent concurrency is separately fixed at one.
    """
    if environment.get('ORQEVIA_LOCAL_ADMISSION_MODE', 'golden_n1') != 'measured':
        return 1
    requested = environment.get("ORQEVIA_QUEUE_CONCURRENCY")
    if requested not in {"2", "3"}:
        return 1
    try:
        backend_parallel = int(environment.get("OLLAMA_NUM_PARALLEL", ""))
    except ValueError:
        return 1
    if backend_parallel < int(requested) or not isinstance(profile, dict):
        return 1
    measured = profile.get("normal_concurrency")
    if isinstance(measured, bool) or not isinstance(measured, int) or measured < int(requested):
        return 1
    return int(requested)


POLICY = QueuePolicy.from_env()
# Additional slots are candidates only, requiring explicit backend and hash-pinned
# measured-profile support. It is never inferred merely from spare host CPU.
_candidate_slots = candidate_global_concurrency(os.environ, runtime_compute_profile())
POLICY = replace(POLICY, global_concurrency=(1 if POLICY.coordinated else _candidate_slots),
                 per_agent_concurrency=1,
                 background_concurrency=(_candidate_slots - 1 if _candidate_slots > 1 else 0))
validate_configuration(SETTINGS,POLICY)
queue = JobQueue(os.getenv("ORQEVIA_COMPUTE_QUEUE_DB", str(DATA / "compute-queue.db")), POLICY)


def _int(name: str, default: int) -> int:
    try: return max(0, int(os.getenv(name, str(default))))
    except ValueError: return default


def providers() -> list[Provider]:
    local_ram,local_vram=_int("ORQEVIA_LOCAL_RAM_MB",32768),_int("ORQEVIA_LOCAL_VRAM_MB",0)
    result=[]
    for role,model in (("fast",SETTINGS.fast_model),("deep",SETTINGS.deep_model),
                       ("evaluator",SETTINGS.evaluator_model),("embedding",SETTINGS.embedding_model)):
        if model and not any(p.model==model for p in result):
            result.append(Provider(f"ollama-{role}","local",model,local_ram,local_vram,
                                   _int("OLLAMA_NUM_PARALLEL",2) or 1))
    from .compute_catalog import load_catalog,model_spec
    for entry in load_catalog():
        if not entry.get('enabled') or entry['location']!='cloud':continue
        spec=model_spec(entry)
        # Unpriced external calls cannot enter automatic budgeted execution.
        if spec.input_usd_million is None or spec.output_usd_million is None:continue
        result.append(Provider(entry['id'],'cloud',entry['model'],0,0,int(entry.get('concurrency',1)),float(spec.input_usd_million),float(spec.output_usd_million),spec.output_tokens,
                               explicit_selection_required=entry.get('provider_kind')=='huggingface'))
    return result


def _validate_job_lease(job: dict) -> None:
    """Compatibility only; never called by the candidate executor."""
    if open_access.enabled():
        return
    from .action_harness import HarnessPolicy
    guarded = registered_agent_ids() if os.getenv('ORQEVIA_REGISTRY_V1_ENABLED','0') == '1' else HarnessPolicy().pilot_agents
    if job['agent'] not in guarded:
        return
    from .harness_api import _runtime
    raw=job.get('harness_envelope')
    if not raw:
        raise PermissionError('Pilot job is missing its signed lease')
    envelope=json.loads(raw)
    signed=envelope.get('parameters',{})
    if envelope.get('actor_id')!=job['agent'] or signed.get('prompt_sha256')!=hashlib.sha256(job['prompt'].encode()).hexdigest():
        raise PermissionError('Queued job does not match its signed lease')
    for field in ('model_role','ram_mb','vram_mb','timeout_seconds','max_retries'):
        if signed.get(field)!=job[field]:
            raise PermissionError('Queued execution parameters changed after authorization')
    if job.get('allow_cloud') or job.get('external_execution'):
        raise PermissionError('Pilot lease does not permit cloud or external execution')
    harness,_=_runtime();decision=harness.validate_active_execution(envelope)
    if not decision.authorized:
        raise PermissionError(decision.reason)


def _execute(job: dict, provider: Provider) -> dict:
    import asyncio
    from .direct_stream import infer
    from .action_records import ActionRecord,DirectExecutor,action_ledger
    if provider.kind!='local':
        from .cloud_execution import execute_cloud
        return execute_cloud(job,provider,DATA,lambda:queue.get(job['id'])['status']=='cancelled')
    record=ActionRecord(job['id'],job['agent'],'inference.run','ollama',
        classification=job.get('classification','R0'),model_backend=provider.model)
    # Persist actual local usage before the queue exposes completion. A later
    # peer read must not create/change the subject's accounting projection.
    from .outcome_metrics import OutcomeMetrics
    from .agent_dispatch_api import local_model_backends
    import uuid
    tier=next((backend.tier.name for backend in local_model_backends()
               if backend.name==provider.name and backend.model==provider.model),None)
    if tier is None:
        raise PermissionError('Local provider is not an existing configured role')
    metrics=OutcomeMetrics(DATA/'compute-ledger.db')
    started=time.monotonic();answer=None;failure='LOCAL_INFERENCE_FAILED'
    capacity=(lambda model:require_compute_capacity(model,already_admitted=True)
              if job.get('lifecycle_state')=='ADMITTED' and queue.guardian is not None
              else require_compute_capacity(model))
    try:
        answer=DirectExecutor(action_ledger()).execute(record,lambda:asyncio.run(infer(job,provider,
            settings=SETTINGS,capacity=capacity,
            options=generation_options,
            cancelled=lambda:queue.get(job['id'])['status']=='cancelled',
            progress=lambda text:queue.update_progress(job['id'],text),
            stage=lambda phase:queue.transition(job['id'],phase))))
        failure='STRICT_JSON_CONTRACT_FAILED' if answer.get('error')=='STRICT_JSON_CONTRACT_FAILED' else None
        return answer
    finally:
        metrics.record(attempt_id=uuid.uuid4().hex,task_id=job['id'],task_class=job.get('task_class','auto'),
            tier=tier,seconds=time.monotonic()-started,
            input_tokens=answer.get('input_tokens') if answer else None,
            output_tokens=answer.get('output_tokens') if answer else None,cost=0,
            agent_id=job['agent'],provider=provider.name,model=provider.model,retries=0,
            requested_tier=tier,requested_provider=provider.name,requested_model=provider.model,
            fallback_route=[],error_classifications=[failure] if failure else [],
            success=answer is not None and failure is None,failure_kind=failure)


def _publish_completed_job(job_id: str) -> None:
    if os.getenv('ORQEVIA_COLLECTIVE_ENABLED') == '1':
        from .collective_runtime import publish_job
        publish_job(job_id)


pool=WorkerPool(queue,providers(),_execute,on_complete=_publish_completed_job)

# Direct mode remains compatible with the 26 October posture. The Owner's
# 28 October patient-operation directive authorizes the explicit home_eco
# mode, which reuses the durable queue and existing shared worker pool.
OUTPUT_QUEUE_MODE = os.getenv("ORQEVIA_OUTPUT_QUEUE_MODE", "direct").strip().lower()
if OUTPUT_QUEUE_MODE not in {"direct", "queued", "home_eco"}:
    raise RuntimeError("ORQEVIA_OUTPUT_QUEUE_MODE must be 'direct', 'queued' or 'home_eco'")
_direct_stop = threading.Event()
_reaper_thread: threading.Thread | None = None


def _run_direct(job_id: str) -> None:
    claimed = queue.claim_direct(job_id, providers())
    if not claimed:
        return
    provider = next(p for p in providers() if p.name == claimed["provider"])
    started = time.perf_counter()
    outcome = "ERROR"
    with span('agent.job.execute', {'component': 'compute-queue', 'provider': provider.name,
                                    'job_type': claimed.get('task_class', 'auto')}) as current:
        try:
            deadline = max(30, int(claimed.get("timeout_seconds") or 300))
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_execute, claimed, provider)
                try:
                    result = future.result(timeout=deadline + 30)
                except FutureTimeout as exc:
                    queue.record_execution_failure(claimed['id'], exc, provider.kind)
                    queue.abort(claimed["id"], "LOCAL_EXECUTION_TIMEOUT")
                    outcome = "TIMEOUT"
                    current.set_attribute('status', 'TIMEOUT')
                    return
            try:
                queue.finish(claimed["id"], **result)
            except ValueError:
                if queue.get(claimed['id'])['status'] == 'running':
                    raise
                outcome = 'ALREADY_TERMINAL'
            else:
                outcome = 'OK'
            current.set_attribute('status', outcome)
        except (Exception, CancelledError) as exc:
            current.set_attribute('status', 'ERROR')
            queue.record_execution_failure(claimed['id'], exc, provider.kind)
            if provider.kind == 'cloud':
                from .provider_runtime import ProviderFailure
                code = exc.code if isinstance(exc, ProviderFailure) else 'EXTERNAL_EXECUTION_FAILED'
                try:
                    queue.finish(claimed['id'], error=code, retryable=False,
                                 actual_cost_usd=None, input_tokens=None, output_tokens=None)
                except ValueError:
                    pass
            else:
                try:
                    queue.finish(claimed["id"],
                                 error='LOCAL_EXECUTION_TIMEOUT' if isinstance(exc, TimeoutError) else 'LOCAL_EXECUTION_FAILED',
                                 retryable=not isinstance(exc, (PermissionError, TimeoutError, CancelledError)))
                except ValueError:
                    pass
        finally:
            attributes = {'component': 'compute-queue', 'provider': provider.name,
                          'job_type': claimed.get('task_class', 'auto'), 'status': outcome}
            record_counter('orqevia.agent.jobs', 1, attributes)
            record_duration('orqevia.agent.job.duration', (time.perf_counter() - started) * 1000, attributes)
    try:
        from .agent_coaching import record_execution_gap
        record_execution_gap(DATA, queue.get(claimed['id']), os.getenv('ORQEVIA_RUNTIME_REVISION',''))
    except (OSError, ValueError, KeyError):
        record_counter('orqevia.coaching.observation_failures', 1, {'component':'coaching'})
    except Exception:
        # Coaching observations cannot turn a completed Owner operation into
        # a failed execution or disclose exception contents in telemetry.
        record_counter('orqevia.coaching.observation_failures', 1, {'component':'coaching'})
    if _publish_completed_job is not None:
        try:
            if queue.get(claimed['id'])['status'] == 'completed':
                _publish_completed_job(claimed['id'])
        except Exception:
            record_counter('orqevia.collective.publication_failures', 1, {'component': 'collective-board'})


def dispatch(job_id: str) -> None:
    """Execute a submitted job immediately; there is no output queue."""
    if OUTPUT_QUEUE_MODE != 'direct':
        queue.wake.set()
        return
    threading.Thread(target=_run_direct, args=(job_id,), daemon=True,
                     name="direct-" + job_id[:8]).start()


def _direct_reap_loop() -> None:
    while not _direct_stop.is_set():
        queue.wake.clear()
        try:
            queue.recover_expired()
            for row in queue.list(status="queued", limit=500):
                dispatch(row["id"])
        except Exception:
            pass
        queue.wake.wait(15)


def authorize(authorization: str | None) -> None:
    from .client_auth import authenticate_owner
    authenticate_owner(authorization)


class SubmitJob(BaseModel):
    response_format: Literal['text', 'strict_json'] = 'text'
    response_schema: dict | None = None
    response_schema_order: Literal['canonical', 'declared'] = 'canonical'
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
    data_classification: str='LOCAL_ONLY'
    task_class: Literal[
        'auto',
        'classification',
        'question_answering',
        'conversation',
        'research',
        'planning',
        'writing',
        'coding',
        'architecture',
        'complex_reasoning',
    ]='auto'
    preferred_provider: str|None=None
    idempotency_key: str|None=Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:-]+$')

    @model_validator(mode='after')
    def validate_response_schema(self):
        if self.response_schema is not None:
            from .response_schema import canonicalize_schema, validated_wire_schema
            if self.response_format != 'strict_json' or (
                (self.allow_cloud or self.external_execution) and not open_access.enabled()
            ):
                raise ValueError('Response schema requires local strict_json execution')
            self.response_schema = (validated_wire_schema(self.response_schema) if self.response_schema_order == 'declared'
                                    else canonicalize_schema(self.response_schema))
        elif self.response_schema_order != 'canonical':
            raise ValueError('Declared schema order requires a response schema')
        return self


class Approval(BaseModel):
    decision: str
    reason: str=""


class SubmitHFQA(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='before')
    @classmethod
    def require_finite_json(cls, value):
        # FastAPI's standard error renderer cannot serialize NaN or lone
        # surrogates echoed in Pydantic error details. Deny invalid JSON/UTF-8
        # with a sanitized response before those details are constructed.
        try:
            if not isinstance(value, dict):
                raise ValueError()
            json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, 'INVALID_QA_REQUEST') from None
        return value

    agent_id: str = Field(min_length=1, max_length=80)
    task_id: str
    provider_id: str = Field(min_length=1, max_length=100)
    context: str = Field(min_length=1, max_length=2048)
    question: str = Field(min_length=1, max_length=256)
    data_classification: str
    max_cost_usd: str
    route: Literal['DIRECT_HF', 'HF_ROUTER'] = 'DIRECT_HF'
    timeout_seconds: float = Field(default=30, gt=0, le=30, strict=True)
    primary_timeout_seconds: float = Field(default=15, gt=0, le=30, strict=True)


@router.post('/hf/qa')
def submit_hf_qa(body: SubmitHFQA, authorization: str | None = Header(None)):
    authorize(authorization)
    from .hf_qa_server import execute_governed_qa, execute_governed_router_qa
    from .provider_runtime import ProviderFailure
    try:
        request = body.model_dump()
        execute = execute_governed_router_qa if request.pop('route') == 'HF_ROUTER' else execute_governed_qa
        return execute(authorization=authorization, queue=queue, data=DATA,
                       available_providers=providers(), **request)
    except ProviderFailure as exc:
        raise HTTPException(503 if exc.pre_execution else 502, exc.code) from None


@router.post("/jobs",status_code=202)
def submit_job(body: SubmitJob,authorization: str|None=Header(None)):
    authorize(authorization)
    if open_access.enabled():
        try:
            row = queue.submit(**body.model_dump())
            if OUTPUT_QUEUE_MODE == "direct": dispatch(row["id"])
            return row
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    if body.external_execution:raise HTTPException(503,'External native job execution is not configured')
    if body.allow_cloud:
        from .tier_router import classify_for_cloud
        if not classify_for_cloud(body.data_classification,body.prompt):raise HTTPException(422,'Data locality excludes cloud')
        if not any(p.kind=='cloud' for p in providers()):raise HTTPException(503,'No configured cloud provider')
    if body.preferred_provider:
        from .compute_catalog import load_catalog
        candidate=next((x for x in load_catalog() if x['id']==body.preferred_provider),None)
        if candidate and candidate.get('provider_kind')=='huggingface' and (
            not body.allow_cloud or body.data_classification!='CLOUD_PERMITTED' or body.max_cost_usd<=0
        ):
            raise HTTPException(422,'Hugging Face requires explicit cloud, disclosure, and cost opt-in')
    try:
        row = queue.submit(**body.model_dump())
        if OUTPUT_QUEUE_MODE == "direct": dispatch(row["id"])
        return row
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.get("/jobs")
def list_jobs(status: str|None=None,limit: int=100,authorization: str|None=Header(None)):
    authorize(authorization);return {"jobs":queue.list(status,max(1,min(500,limit)))}


@router.get("/jobs/{job_id}")
def get_job(job_id: str,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return queue.get(job_id)
    except KeyError:raise HTTPException(404,"Job not found")


def decide_job(job_id: str,body: Approval,authorization: str|None=Header(None)):
    authorize(authorization)
    try:return queue.approve(job_id,body.decision,"owner",body.reason)
    except KeyError:raise HTTPException(404,"Job not found")
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


@router.get("/metrics")
def metrics(authorization: str|None=Header(None)):
    authorize(authorization);return {**queue.metrics(),"providers":[p.__dict__ for p in providers()]}


@router.get('/providers/health')
def provider_health(authorization: str|None=Header(None)):
    authorize(authorization)
    from .cloud_execution import configured_provider_health
    return configured_provider_health()


@router.get('/providers/usage')
def provider_usage(authorization: str|None=Header(None)):
    authorize(authorization)
    from .provider_usage import usage_projection
    return usage_projection(DATA/'compute-ledger.db',POLICY)


def start_compute_queue() -> None:
    global _reaper_thread
    if OUTPUT_QUEUE_MODE == "direct":
        if _reaper_thread and _reaper_thread.is_alive(): return
        _direct_stop.clear()
        _reaper_thread = threading.Thread(target=_direct_reap_loop, name="direct-reaper", daemon=True)
        _reaper_thread.start()
        return
    pool.start()


def stop_compute_queue() -> None:
    if OUTPUT_QUEUE_MODE == "direct":
        _direct_stop.set()
        queue.wake.set()
        if _reaper_thread: _reaper_thread.join(timeout=3)
        return
    pool.stop()
