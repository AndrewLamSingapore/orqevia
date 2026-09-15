"""Bounded Builder/Test Engineer execution; no native shell or host imports."""
import uuid
import threading
from typing import Literal
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field

from .client_auth import authenticate_owner
from .connector_sdk import ConnectorRegistry,Sink
from .wasm_sandbox import WasmSandbox
from .compute_profile import require_compute_capacity
from .settings import SETTINGS

router=APIRouter(prefix='/api/agents/engineering',tags=['bounded-engineering'])
slots=threading.BoundedSemaphore(2)


class WasmRequest(BaseModel):
    role: Literal['A12 Builder','A13 Test Engineer']
    source: str=Field(min_length=1,max_length=256000)
    export: str=Field(min_length=1,max_length=100)
    args: list[int]=Field(default_factory=list,max_length=16)


@router.post('/wasm')
def execute(body: WasmRequest,authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    if not slots.acquire(blocking=False):raise HTTPException(429,'Bounded engineering capacity is occupied')
    try:
        require_compute_capacity(SETTINGS.fast_model)
        return _execute(body,authorization)
    finally:slots.release()


def _execute(body,authorization):
    actor={'A12 Builder':'a17','A13 Test Engineer':'a18'}[body.role]
    try:sandbox=WasmSandbox()
    except ImportError:raise HTTPException(503,'WebAssembly runtime unavailable')
    payload=body.model_dump(exclude={'role'})
    sinks=ConnectorRegistry()
    sinks.register(Sink('wasm-sandbox','sandbox.wasm.execute','R1','Bounded guest computation only',True,
                        'LOCAL_ONLY','sandbox.wasm.execute'),lambda value:sandbox.run(**value))
    task_id=str(uuid.uuid4())
    try:return {'actor':actor,'result':sinks.execute('wasm-sandbox','sandbox.wasm.execute',payload,
        task_id=task_id,agent_id=actor),'correlation_id':task_id,'execution_model':'DIRECT_OBSERVED'}
    except Exception as exc:raise HTTPException(422,{'state':'GUEST_FAILED','type':type(exc).__name__}) from exc
