"""Guarded cognitive endpoints for ORQEVIA."""
from __future__ import annotations
import hmac, os
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .meta_review import MetaReviewer
from .evaluation import evaluate
from .release_gate import release_gates
from .runtime import memory, ledger, events, orchestrator, multi, authority
from .multi_invocation import Depth, InvocationBudget, MultiInvocationRuntime, local_gateway_invoker

router=APIRouter(prefix="/api/cognitive",tags=["cognitive"])
reviewer=MetaReviewer()

class StrictRequest(BaseModel): model_config=ConfigDict(extra="forbid")
class EpisodeRequest(StrictRequest):
    event_type:str; content:dict[str,Any]; source:str; salience:float=Field(default=0.0,ge=0.0,le=1.0); durable_kind:str|None=None; durable_key:str|None=None
class PlanRequest(StrictRequest): intent:str; department:str=""; context:str=""; allow_frontier:bool=False
class ExecuteRequest(PlanRequest): deep:bool=False
class EventRequest(StrictRequest):
    schema_version:str=Field(pattern=r"^1\.0\.0$"); event_id:str; event_type:str; source:str; occurred_at:str; evidence_level:str; correlation_id:str; subject_id:str|None=None; provenance:list[str]=Field(min_length=1); payload:dict[str,Any]
class MultiRequest(StrictRequest): intent:str; context:str=""; evidence:str=""; deep:bool=False
class MultiInvocationRequest(StrictRequest):
    objective:str=Field(min_length=1,max_length=12000)
    depth:Depth=Depth.STANDARD
class EvalRequest(StrictRequest): answer:str; evidence_terms:list[str]=Field(default_factory=list); required_terms:list[str]=Field(default_factory=list); executed_external_action:bool=False

def require_token(authorization:str|None)->None:
    expected=os.getenv("ORQEVIA_SPINE_TOKEN","").strip(); supplied=authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not expected: raise HTTPException(status_code=503,detail="Cognitive authentication is not configured")
    if not supplied or not hmac.compare_digest(supplied,expected): raise HTTPException(status_code=401,detail="Cognitive authorization required")

@router.post("/episodes")
def record_episode(request:EpisodeRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    try:return {"ok":True,"episode":memory.record_episode(**request.model_dump())}
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e
@router.post("/consolidate")
def consolidate(authorization:str|None=Header(default=None)): require_token(authorization); return {"ok":True,**memory.consolidate()}
@router.get("/episodes")
def recent_episodes(limit:int=50,authorization:str|None=Header(default=None)): require_token(authorization); return {"episodes":memory.recent_episodes(limit)}
@router.get("/memory/search")
def search_memory(q:str,limit:int=10,authorization:str|None=Header(default=None)):
    require_token(authorization);results=orchestrator.hybrid_memory.search(q,limit=limit);return {"query":q,"results":results,"retrieval":orchestrator.hybrid_memory.last_status}
@router.post("/plan")
def cognitive_plan(request:PlanRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    try:return {"ok":True,"plan":orchestrator.plan(**request.model_dump()).as_dict()}
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e
@router.post("/reason")
def cognitive_reason(request:ExecuteRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    try:return {"ok":True,**orchestrator.execute(**request.model_dump())}
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e
    except RuntimeError as e:raise HTTPException(status_code=503,detail=str(e)) from e
@router.post("/multi-reason")
def multi_reason(request:MultiRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    try:return {"ok":True,**multi.run(**request.model_dump())}
    except RuntimeError as e:raise HTTPException(status_code=503,detail=str(e)) from e
@router.post("/multi-invoke")
def multi_invoke(request:MultiInvocationRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    # Explicit experimental opt-in. No frontend exposure, cloud routing or
    # production behavior change until normal admission and promotion gates.
    if os.getenv("ORQEVIA_MULTI_INVOCATION_ENABLED", "") != "1":
        raise HTTPException(status_code=503,detail="Multi-invocation candidate is disabled")
    try:
        max_calls=min(64,max(5,int(os.getenv("ORQEVIA_MULTI_INVOCATION_MAX_CALLS","8"))))
        budget=InvocationBudget(max_calls=max_calls,max_parallel=1,max_elapsed_seconds=180)
        runtime=MultiInvocationRuntime(local_gateway_invoker(orchestrator.gateway))
        return {"ok":True,**runtime.run(objective=request.objective,depth=request.depth,
                                       budget=budget,permitted_parallel=1)}
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e
    except RuntimeError as e:raise HTTPException(status_code=503,detail=str(e)) from e
@router.post("/events")
def ingest_event(request:EventRequest,authorization:str|None=Header(default=None)):
    require_token(authorization)
    try:return {"ok":True,**events.ingest(request.model_dump())}
    except ValueError as e:raise HTTPException(status_code=422,detail=str(e)) from e
@router.get("/events")
def recent_events(limit:int=50,authorization:str|None=Header(default=None)): require_token(authorization); return {"events":events.recent(limit)}
@router.get("/event-reviews")
def event_reviews(limit:int=50,authorization:str|None=Header(default=None)): require_token(authorization); return {"reviews":events.reviews(limit)}
@router.get("/semantic-graph")
def semantic_graph(limit:int=100,authorization:str|None=Header(default=None)): require_token(authorization); return {"nodes":events.graph(limit)}
@router.post("/evaluate")
def evaluate_run(request:EvalRequest,authorization:str|None=Header(default=None)): require_token(authorization); return {"ok":True,"evaluation":evaluate(**request.model_dump())}
@router.get("/models")
def model_manifest(authorization:str|None=Header(default=None)): require_token(authorization); return orchestrator.gateway.manifest()
@router.get("/compute")
def compute_events(limit:int=100,authorization:str|None=Header(default=None)): require_token(authorization); return {"events":ledger.recent(limit),"summary":ledger.summary(),"scorecard":ledger.scorecard(limit)}
@router.get("/agent-runtime")
def agent_runtime(limit:int=100,authorization:str|None=Header(default=None)):
    require_token(authorization); return release_gates.enrich_snapshot(authority.public_snapshot(max(1,min(limit,500))))
@router.get("/meta-review")
def meta_review(authorization:str|None=Header(default=None)): require_token(authorization); return reviewer.review()
