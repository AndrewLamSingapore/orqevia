"""Common service requests, authenticated task actors and scoped fulfillment.

Owner/scheduler credentials stay at this boundary. Agents receive facts/results,
never transport credentials. This does not grant authority from internet text.
"""
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from functools import wraps
from datetime import datetime,timezone
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from .agent_registry import agent_record,registered_agent_ids
from .client_auth import authenticate_owner
from .action_records import ActionRecord,DirectExecutor,action_ledger
from .compute_queue_api import queue
from .public_http import public_read

VERSION='orqevia.scoped-capability-broker.v1'
router=APIRouter(prefix='/api/capabilities',tags=['scoped-agent-services'])
slots=threading.BoundedSemaphore(2)
actor_lock=threading.Lock()
active_actors=set()
class ServiceBusy(RuntimeError):pass

@contextmanager
def service_admission(actor):
    if not slots.acquire(blocking=False):raise ServiceBusy('Bounded service capacity occupied')
    admitted=False
    try:
        with actor_lock:
            if actor in active_actors:raise ServiceBusy('Actor already has active service work')
            active_actors.add(actor);admitted=True
        yield
    finally:
        if admitted:
            with actor_lock:active_actors.remove(actor)
        slots.release()

def bounded_service(function):
    @wraps(function)
    def bounded(body,*args,**kwargs):
        actor=getattr(body,'agent',getattr(body,'actor','prime'))
        with service_admission(actor):return function(body,*args,**kwargs)
    return bounded
INFRA_READ={'a15','a16','a19','a26','a28','a29'}
HF_ACCOUNT_READ={'a15','a19','a20','a21','a26','a29'}
SERVICES=('internet.public.read','private.task.metadata.read','infrastructure.status.read',
          'sandbox.wasm.execute','huggingface.account.read','github.repository.read',
          'digitalocean.infrastructure.read','secrets.request','delegation.request',
          'infrastructure.apply','code.generate','engineering.debug')

def permissions(agent):
    record=agent_record(agent)
    return {service:(service in {'internet.public.read','private.task.metadata.read'} or
       service=='infrastructure.status.read' and agent in INFRA_READ or
       service=='huggingface.account.read' and agent in HF_ACCOUNT_READ or
       service=='sandbox.wasm.execute' and 'sandbox.wasm.execute' in record['tool_eligibility'] or
       service=='delegation.request' and bool(record['allowed_delegation_targets'])) for service in SERVICES}

class ServiceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    agent: str=Field(min_length=3,max_length=3)
    job_id: str=Field(min_length=36,max_length=36)
    service: str=Field(min_length=1,max_length=80)
    parameters: dict=Field(default_factory=dict)

class CoreRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: str=Field(min_length=1,max_length=128)
    service: str=Field(min_length=1,max_length=80)
    parameters: dict=Field(default_factory=dict)

@bounded_service
def execute_core_request(body,*,reader=public_read,ledger=None):
    """Core's own path, with no specialist job or active-agent dependency."""
    from .collective_workspace import identifier
    identifier(body.request_id)
    audit=ledger or action_ledger()
    if not audit.status()['healthy']:raise RuntimeError('Action audit unavailable')
    record=ActionRecord(body.request_id,'prime',body.service,'core-capability-broker')
    def operation():
        if body.service=='internet.public.read':
            if set(body.parameters)!={'url'}:raise ValueError('Exact public read parameters required')
            return reader(body.parameters['url'])
        if body.service=='infrastructure.status.read' and not body.parameters:
            metrics=queue.metrics()
            return {'source_revision':os.getenv('PRIME_RUNTIME_REVISION','UNKNOWN'),
                    'queue_statuses':metrics['statuses'],'policy':metrics['policy'],
                    'scope':'OWNED_CORE_STATUS_ONLY','management_authority_granted':False}
        raise PermissionError('Core request needs approved scoped implementation')
    try:result=DirectExecutor(audit).execute(record,operation)
    except Exception:
        if not audit.flush():raise RuntimeError('Core failure audit unavailable') from None
        raise
    if not audit.flush():raise RuntimeError('Core operation audit unavailable')
    return {'schema':VERSION,'actor':'prime','request_id':body.request_id,'service':body.service,
            'action_id':record.action_id,'result':result,'observed_at':datetime.now(timezone.utc).isoformat(),
            'independent_of_specialist_jobs':True,'audit_persisted':True,'full_acceptance_awarded':False}

@router.post('/core/request')
def core_request(body:CoreRequest,authorization: str|None=Header(None)):
    authenticate_owner(authorization)
    try:
        try:return execute_core_request(body)
        except ServiceBusy:raise HTTPException(429,'Bounded Core service capacity occupied') from None
        except PermissionError:raise HTTPException(403,'Core scoped fulfillment denied') from None
        except (ValueError,KeyError):raise HTTPException(422,'Invalid Core service request') from None
        except Exception:raise HTTPException(503,'Core service dependency unavailable') from None
    finally:pass

@bounded_service
def execute_request(body,*,job_queue=queue,reader=public_read,ledger=None):
    if body.agent not in registered_agent_ids(include_orchestrator=False):raise PermissionError('Canonical registered actor required')
    if len(json.dumps(body.parameters,allow_nan=False).encode())>262144:raise ValueError('Bounded parameters required')
    audit=ledger or action_ledger()
    if not audit.status()['healthy']:raise RuntimeError('Action audit unavailable')
    record=ActionRecord(body.job_id,body.agent,body.service,'scoped-capability-broker',
        parameters_summary={'service':body.service,'parameters_sha256':hashlib.sha256(json.dumps(body.parameters,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
    def operation():
        job=job_queue.get(body.job_id)
        if not job or job['agent']!=body.agent:raise PermissionError('Authenticated task actor binding mismatch')
        if not permissions(body.agent).get(body.service,False):
            raise PermissionError('Role service fulfillment denied; request may be escalated without authority transfer')
        p=body.parameters
        if body.service=='internet.public.read':
            if job.get('data_classification')!='CLOUD_PERMITTED':raise PermissionError('Explicit public-egress task classification required')
            if set(p)!={'url'}:raise ValueError('Exact public read parameters required')
            return reader(p['url'])
        if body.service=='private.task.metadata.read':
            if p:raise ValueError('No alternate task/source selector permitted')
            prompt=job['prompt']
            if len(prompt.encode())>65536:raise ValueError('Task context exceeds read limit')
            return {'source_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'source_bytes':len(prompt.encode()),
                    'job_id':job['id'],'actor':body.agent,'scope':'OWN_AUTHENTICATED_TASK_METADATA_ONLY',
                    'prompt_or_credential_content_returned':False}
        if body.service=='infrastructure.status.read':
            if p:raise ValueError('Only approved local status path supported')
            metrics=job_queue.metrics()
            return {'source_revision':os.getenv('PRIME_RUNTIME_REVISION','UNKNOWN'),'queue_statuses':metrics['statuses'],
                    'policy':metrics['policy'],'scope':'OWNED_ORQEVIA_RUNTIME_READ_ONLY','management_authority_granted':False}
        if body.service=='sandbox.wasm.execute':
            if set(p)!={'source','export','args'}:raise ValueError('Exact sandbox parameters required')
            from .compute_profile import require_bounded_work_capacity
            from .wasm_sandbox import WasmSandbox
            require_bounded_work_capacity()
            return WasmSandbox().run(**p)
        if body.service=='huggingface.account.read':
            if p:raise ValueError('Fixed authenticated endpoint only')
            from .secret_refs import resolve_secret
            from .public_http import fixed_private_json
            status,data=fixed_private_json('https://huggingface.co/api/whoami-v2',{'Authorization':'Bearer '+resolve_secret('file:HF_TOKEN')})
            return {'status':status,'authenticated_account_name':data.get('name'),
                    'credentials_exposed':False,'scope':'OWNER_APPROVED_PROVIDER_ACCOUNT_METADATA_ONLY'}
        if body.service=='delegation.request':
            if set(p)!={'target'} or p['target'] not in agent_record(body.agent)['allowed_delegation_targets']:
                raise PermissionError('Registry delegation edge denied')
            return {'state':'PERMITTED_EDGE_REQUEST','source':body.agent,'target':p['target'],
                    'execution_completed':False,'authority_transferred':False}
        raise RuntimeError('Configured approved service implementation required')
    try:result=DirectExecutor(audit).execute(record,operation)
    except Exception:
        if not audit.flush():raise RuntimeError('Denied or failed operation audit flush unavailable') from None
        raise
    if not audit.flush():raise RuntimeError('Operation occurred but durable audit flush failed')
    return {'schema':VERSION,'actor':body.agent,'job_id':body.job_id,'service':body.service,
            'action_id':record.action_id,'observed_at':datetime.now(timezone.utc).isoformat(),
            'audit_persisted':True,'result':result,'full_role_acceptance_awarded':False}

@router.get('/permissions')
def catalog(authorization: str|None=Header(None)):
    authenticate_owner(authorization)
    return {'schema':VERSION,'agents':[{'agent':a,'role':agent_record(a)['name'],'fulfillment':permissions(a),
          'request_interface_available':True,'secrets_distributed':False} for a in sorted(registered_agent_ids(include_orchestrator=False))],
          'unsupported_requests':'DENIED_OR_UNCONFIGURED_NOT_EXECUTED','sensitive_irreversible_execution':'NO_AUTHORITY_FROM_MODEL_REQUEST'}

@router.post('/request')
def request(body:ServiceRequest,authorization: str|None=Header(None)):
    authenticate_owner(authorization)
    try:
        try:return execute_request(body)
        except ServiceBusy:raise HTTPException(429,'Bounded service capacity occupied') from None
        except PermissionError:raise HTTPException(403,'Actor, role, scope or sensitive-action approval denied') from None
        except (ValueError,KeyError):raise HTTPException(422,'Invalid bounded service request') from None
        except Exception:raise HTTPException(503,'Approved service dependency or audit unavailable') from None
    finally:pass
