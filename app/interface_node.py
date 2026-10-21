"""Shared client protocol. Client credentials never become tool authority."""
import hashlib
import hmac
import json
import os
import math
import time
import re
from pathlib import Path
import sqlite3

from fastapi import APIRouter,Header,HTTPException,Response
from pydantic import BaseModel,Field
from typing import Literal

from . import objective_api,compute_queue_api
from .action_records import action_ledger
from .artifact_factory import ArtifactFactory
from .artifact_delivery import create_task_artifact
from .agent_registry import load_agent_registry, registered_agent_ids
from . import open_access

router=APIRouter(prefix='/api/interface/v1',tags=['interface-node'])


def _observed_count(path: Path, query: str, parameters=()):
    if not path.is_file():
        return {'status':'UNAVAILABLE','count':None}
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            return {'status':'OBSERVED','count':db.execute(query,parameters).fetchone()[0]}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        return {'status':'UNAVAILABLE','count':None}


def evidence_aggregates():
    """Safe aggregate evidence from the active direct-execution stores only."""
    root=Path(os.getenv('ORQEVIA_DATA_DIR','/data')).resolve()
    registry=load_agent_registry()
    objectives=_observed_count(root/'objectives.db','SELECT COUNT(*) FROM objectives')
    jobs=_observed_count(root/'compute-queue.db','SELECT COUNT(*) FROM compute_jobs')
    sessions={'status':'UNAVAILABLE','stored_count':None,'non_revoked_count':None,'active_count':None}
    try:
        path=root/'pwa-sessions.db'
        if path.is_file():
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                stored,non_revoked,active=db.execute(
                    'SELECT COUNT(*),SUM(CASE WHEN revoked=0 THEN 1 ELSE 0 END),'
                    'SUM(CASE WHEN revoked=0 AND expires>? THEN 1 ELSE 0 END) FROM sessions',
                    (time.time(),)).fetchone()
            sessions={'status':'OBSERVED','stored_count':stored,
                'non_revoked_count':non_revoked or 0,'active_count':active or 0,
                'active_scope':'Non-revoked sessions whose expiry is in the future'}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        pass

    job_states={'status':'UNAVAILABLE','counts':{}}
    try:
        path=root/'compute-queue.db'
        if path.is_file():
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                rows=db.execute('SELECT status,COUNT(*) FROM compute_jobs GROUP BY status').fetchall()
            job_states={'status':'OBSERVED','counts':{str(state):count for state,count in rows}}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        pass

    artifacts={'status':'UNAVAILABLE','count':None}
    try:
        store=root/'artifacts'
        if store.is_dir():
            count=0
            for folder in store.iterdir():
                if not folder.is_dir() or not re.fullmatch(r'[0-9a-f]{32}',folder.name):continue
                metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
                if metadata.get('artifact_id')==folder.name:count+=1
            artifacts={'status':'OBSERVED','count':count}
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        artifacts={'status':'UNAVAILABLE','count':None}

    actions={'status':'UNAVAILABLE','count':None}
    try:
        path=root/'action-records.jsonl'
        if path.is_file():
            count=0
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    value=json.loads(line)
                    if isinstance(value,dict) and isinstance(value.get('sequence'),int):count+=1
            actions={'status':'OBSERVED','count':count}
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        actions={'status':'UNAVAILABLE','count':None}

    revision=os.getenv('ORQEVIA_INTERFACE_RUNTIME_REVISION','UNKNOWN').strip().lower()
    if revision!='UNKNOWN' and not re.fullmatch(r'[0-9a-f]{40}',revision):revision='UNKNOWN'
    return {
        'schema_version':'jarvis.evidence-summary.v1','runtime_revision':revision,
        'read_only':True,'physical_actuation':False,
        'agents':{'status':'OBSERVED','canonical_agent_count':len(registry['agents']),
            'historical_responsibility_count':sum(len(agent['responsibilities']) for agent in registry['agents']),
            'historical_responsibility_scope':'Migrated responsibility identifiers; not runtime agent identities'},
        'current_stores':{'objectives':objectives,
            'compute_jobs':{**jobs,'status_counts':job_states['counts'] if job_states['status']=='OBSERVED' else None},
            'pwa_sessions':sessions,'artifacts':artifacts,'action_records':actions},
        'legacy_metrics':{
            'agent_count':{'status':'RETIRED_AMBIGUOUS','replacement':'agents.canonical_agent_count'},
            'objectives':{'status':'REPLACED','replacement':'current_stores.objectives.count'},
            'artifacts':{'status':'REPLACED','replacement':'current_stores.artifacts.count'},
            'agent_jobs':{'status':'REPLACED','replacement':'current_stores.compute_jobs.count'},
            'facts':{'status':'NOT_APPLICABLE','reason':'retired app.main store is not the production authority'},
            'memories':{'status':'NOT_APPLICABLE','reason':'retired app.main store is not the production authority'},
            'projects':{'status':'NOT_APPLICABLE','reason':'no equivalent authoritative direct-execution metric'},
            'orchestration_runs':{'status':'NOT_APPLICABLE','reason':'no equivalent authoritative direct-execution metric'}},
        'privacy':{'aggregate_only':True,'record_contents_exposed':False,
            'objective_contents_exposed':False,'artifact_contents_exposed':False,
            'session_credentials_exposed':False}}


def client_policy(client_id):
    """Only server configuration sets disclosure and per-dispatch spend limits."""
    if open_access.enabled():
        return open_access.owner_policy()
    if isinstance(client_id,str) and client_id.startswith('pwa:'):
        from .pwa_sessions import client_policy as pwa_policy
        return pwa_policy(client_id)
    try:
        clients=json.loads(os.getenv('ORQEVIA_INTERFACE_CLIENTS_JSON','{}'))
        if not isinstance(clients,dict):raise ValueError()
        policy=clients.get(client_id or '',{})
        if not isinstance(policy,dict):raise ValueError()
        classification=policy.get('data_classification','LOCAL_ONLY')
        ceiling=policy.get('max_cost_usd',0)
        from .tier_router import CLASSIFICATIONS
        if not isinstance(classification,str) or classification not in CLASSIFICATIONS:raise ValueError()
        if isinstance(ceiling,bool) or not isinstance(ceiling,(int,float)) or not math.isfinite(ceiling) or not 0<=ceiling<=100:raise ValueError()
        return policy
    except (TypeError,ValueError,OverflowError):
        raise HTTPException(503,'Client policy unavailable') from None


def dispatch_priority(policy):
    """Only a server-issued OWNER role receives the interactive queue lane."""
    return 'critical' if policy.get('role')=='OWNER' else 'normal'


def client_identity(client_id: str | None,authorization: str | None,capability: str) -> str:
    if open_access.enabled():
        return open_access.owner_identity(client_id)
    policy=client_policy(client_id)
    supplied=authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    digest=hashlib.sha256(supplied.encode()).hexdigest()
    if not supplied or not hmac.compare_digest(digest,str(policy.get('token_sha256',''))):
        raise HTTPException(401,'Client authentication required')
    # Bounded thin-client credentials retain their expiry and scope on legacy
    # aliases too. Pre-contract local policies remain compatibility-only and
    # must not be published by the external TLS listener.
    if 'expires_at' in policy:
        try:
            expiry=float(policy['expires_at'])
            scopes=policy.get('capabilities',[])
            valid=math.isfinite(expiry) and expiry>time.time() and isinstance(scopes,list) and capability in scopes
        except (TypeError,ValueError):valid=False
        if not valid:raise HTTPException(403,'Client scope expired or unavailable')
    # Authenticated client identity and task ownership remain; action labels are not permissions.
    return client_id


def owner_transport():
    # This credential stays inside ORQEVIA; only bounded advisory methods below
    # may use it. No caller-supplied URL, action, tool, approval, or model allowed.
    token=os.getenv('ORQEVIA_SPINE_TOKEN','')
    if not token:raise HTTPException(503,'Authority plane unavailable')
    return 'Bearer '+token


@router.get('/health')
def health(x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client_identity(x_client_id,authorization,'health.read')
    policy=client_policy(x_client_id)
    cloud_permitted=(policy.get('data_classification','LOCAL_ONLY')=='CLOUD_PERMITTED'
                     and policy.get('max_cost_usd',0)>0
                     and ('expires_at' not in policy or 'objective.submit' in policy.get('capabilities',[])))
    from .cloud_execution import configured_provider_health
    try:
        available={provider.name for provider in compute_queue_api.providers() if provider.kind=='cloud'}
        cloud_ready=any(row['provider_id'] in available and row['readiness']=='READY'
                        for row in configured_provider_health())
    except Exception:
        cloud_ready=False
    ledger=action_ledger()
    return {'state':'READY','canonical_agent_count':len(registered_agent_ids(include_orchestrator=False)),
            'execution_model':'DIRECT_OBSERVED','cloud_enabled':cloud_permitted and cloud_ready,
            'cloud_client_permitted':cloud_permitted,'cloud_configuration_ready':cloud_ready,
            'cloud_provider_health':'UNMEASURED','cloud_network_probe_performed':False,'logging':ledger.status(),
            'client_identity_grants_tool_authority':False,'evidence':evidence_aggregates()}


def db_connect():
    root=Path(os.getenv('ORQEVIA_DATA_DIR','/data'))
    root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'interface.db',timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS requests(client TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL, task TEXT, PRIMARY KEY(client,key))')
    db.execute('CREATE TABLE IF NOT EXISTS client_accounts(client TEXT PRIMARY KEY,account TEXT NOT NULL)')
    db.commit()
    return db


class Objective(BaseModel):
    objective: str=Field(min_length=1,max_length=20000)
    context: str=Field(default='',max_length=80000)
    idempotency_key: str=Field(min_length=1,max_length=100)
    deterministic_operation: Literal['sha256','json_format','json_validate'] | None = None


@router.post('/objectives',status_code=202)
def submit(body: Objective,x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client=client_identity(x_client_id,authorization,'objective.submit')
    policy=client_policy(client)
    digest=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    db=db_connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        account_binding(db,client,current_required=True)
        prior=db.execute('SELECT digest,task FROM requests WHERE client=? AND key=?',(client,body.idempotency_key)).fetchone()
        if prior:
            db.rollback()
            if prior[0]!=digest:raise HTTPException(409,'Idempotency payload mismatch')
            if not prior[1]:raise HTTPException(409,'Dispatch outcome requires reconciliation; no automatic replay')
            return {'task_id':prior[1],'state':'RECEIVED','idempotent_replay':True}
        db.execute('INSERT INTO requests VALUES(?,?,?,NULL)',(client,body.idempotency_key,digest))
        db.commit()
        # The shared dispatcher and cloud executor still apply secret filtering,
        # tier selection, queue limits and cost reservation. No client overrides.
        result=objective_api.submit(objective_api.ObjectiveRequest(objective=body.objective,context=body.context,
            deterministic_operation=body.deterministic_operation,
            data_classification=policy.get('data_classification','LOCAL_ONLY'),
            max_cost_usd=policy.get('max_cost_usd',0),
            priority=dispatch_priority(policy)),owner_transport())
        db.execute('UPDATE requests SET task=? WHERE client=? AND key=?',(result['id'],client,body.idempotency_key))
        db.commit()
        return {'task_id':result['id'],'state':'ROUTED','idempotent_replay':False}
    finally:db.close()


def account_binding(db,client,*,current_required=False):
    account=client_policy(client).get('owner_account_id')
    prior=db.execute('SELECT account FROM client_accounts WHERE client=?',(client,)).fetchone()
    if account is not None:
        if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}',account):raise HTTPException(503,'Owner linkage unavailable')
        if prior and prior[0]!=account:raise HTTPException(503,'Owner linkage conflicts with preserved binding')
        db.execute('INSERT OR IGNORE INTO client_accounts VALUES(?,?)',(client,account))
        return account
    return None if current_required or not prior else prior[0]

def own_task(task_id,client):
    db=db_connect()
    try:
        found=db.execute('SELECT 1 FROM requests WHERE client=? AND task=?',(client,task_id)).fetchone()
        if found:
            account_binding(db,client,current_required=True)
            db.commit();return
        # Only server-assigned account membership joins explicitly owner-enrolled
        # clients. Headers, objective payloads and task IDs cannot assign membership.
        caller_account=account_binding(db,client,current_required=True)
        if caller_account:
            owners=[row[0] for row in db.execute('SELECT DISTINCT client FROM requests WHERE task=?',(task_id,))]
            found=any(account_binding(db,owner)==caller_account for owner in owners)
        db.commit()
        if not found:raise HTTPException(404,'Task not found')
    finally:db.close()


@router.get('/tasks/{task_id}')
def task_status(task_id: str,x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client=client_identity(x_client_id,authorization,'task.read')
    own_task(task_id,client)
    return objective_api.get(task_id,owner_transport())


@router.post('/tasks/{task_id}/cancel')
def cancel(task_id: str,x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client=client_identity(x_client_id,authorization,'task.cancel')
    own_task(task_id,client)
    task=objective_api.get(task_id,owner_transport())
    cancelled=[]
    for step in task.get('steps',[]):
        if step.get('revision',0)!=task.get('revision',0):continue
        if step.get('job',{}).get('status') not in {'queued','running','awaiting_authority'}:continue
        if 'job' not in step.get('dispatch',{}):continue
        job_id=step['dispatch']['job']['id']
        compute_queue_api.queue.cancel(job_id)
        cancelled.append(job_id)
    return {'task_id':task_id,'state':'CANCELLATION_REQUESTED','jobs':cancelled}


@router.get('/artifacts/{artifact_id}')
def artifact(artifact_id: str,x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client=client_identity(x_client_id,authorization,'artifact.read')
    factory=ArtifactFactory(Path(os.getenv('ORQEVIA_DATA_DIR','/data'))/'artifacts')
    try:metadata,raw=factory.retrieve(artifact_id)
    except (ValueError,KeyError,FileNotFoundError):raise HTTPException(404,'Artifact unavailable')
    own_task(metadata['task_id'],client)
    from .public_task_errors import publishable_task_artifact
    if not publishable_task_artifact(metadata,raw):raise HTTPException(404,'Artifact unavailable')
    return Response(raw,media_type='application/octet-stream',headers={
        'Content-Disposition':'attachment; filename="'+metadata['location']+'"',
        'X-Artifact-SHA256':metadata['sha256']})


@router.post('/tasks/{task_id}/artifact',status_code=201)
def materialize(task_id: str,x_client_id: str | None=Header(None),authorization: str | None=Header(None)):
    client=client_identity(x_client_id,authorization,'artifact.create_from_task')
    own_task(task_id,client)
    return create_task_artifact(task_id,owner_transport())
