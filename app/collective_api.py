"""Authenticated Core and task-bound agent workspace operations."""
from pathlib import Path
import os
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .client_auth import authenticate_owner
from .collective_workspace import CollectiveWorkspace,Conflict
from .compute_queue_api import queue
from .action_records import ActionRecord,DirectExecutor,action_ledger
from .capability_broker import bounded_service,ServiceBusy

router=APIRouter(prefix='/api/collective',tags=['durable-workspaces'])
OPERATIONS={
 'sketch.write':'write_sketch','sketch.read':'read_sketch','sketch.search':'search_sketch',
 'board.subscribe':'subscribe','board.post':'post','board.read':'messages','board.pending':'pending',
 'board.ack':'acknowledge','board.archive':'archive_message','task.assign':'assign','task.read':'task',
 'task.claim':'claim','task.transition':'transition','task.shutdown':'shutdown','task.history':'task_history',
 'audit.read':'audit'}

class WorkspaceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    actor: str=Field(min_length=3,max_length=5)
    job_id: str|None=Field(default=None,min_length=36,max_length=36)
    operation: str=Field(min_length=1,max_length=64)
    parameters: dict=Field(default_factory=dict)

@bounded_service
def execute_workspace(body,*,job_queue=queue,store=None,ledger=None):
    if body.actor=='prime':
        if body.job_id is not None:raise PermissionError('Core has a separate workspace principal')
    else:
        if body.job_id is None or job_queue.get(body.job_id)['agent']!=body.actor:
            raise PermissionError('Workspace actor must match authenticated task')
    method=OPERATIONS.get(body.operation)
    if method is None:raise PermissionError('Unknown workspace operation')
    if 'actor' in body.parameters or 'principal' in body.parameters:raise PermissionError('Principal cannot be overridden')
    store=store or CollectiveWorkspace(Path(os.getenv('PRIME_DATA_DIR','/data'))/'collective-workspace.db')
    audit=ledger or action_ledger()
    if not audit.status()['healthy']:raise RuntimeError('Workspace action audit unavailable')
    record=ActionRecord(body.job_id or 'core-workspace',body.actor,body.operation,'collective-workspace')
    try:result=DirectExecutor(audit).execute(record,lambda:getattr(store,method)(body.actor,**body.parameters))
    except Exception:
        if not audit.flush():raise RuntimeError('Workspace failure audit unavailable') from None
        raise
    if not audit.flush():raise RuntimeError('Workspace operation audit unavailable')
    return {'actor':body.actor,'operation':body.operation,'result':result,'action_id':record.action_id,
            'audit_persisted':True,'claims_are_not_certification':True}

@router.post('/request')
def request(body:WorkspaceRequest,authorization: str|None=Header(None)):
    authenticate_owner(authorization)
    try:return execute_workspace(body)
    except ServiceBusy:raise HTTPException(429,'Bounded workspace capacity occupied') from None
    except PermissionError:raise HTTPException(403,'Workspace scope denied') from None
    except Conflict:raise HTTPException(409,'Workspace revision, lease or idempotency conflict') from None
    except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid bounded workspace operation') from None
    except Exception:raise HTTPException(503,'Workspace dependency or audit unavailable') from None
