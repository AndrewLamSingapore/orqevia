"""Dell wire contract over the existing task/ownership store; no new executor.

TLS must terminate at an explicitly configured trusted server. This module never
trusts a caller-supplied Forwarded header to turn HTTP into HTTPS.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError, BaseModel, ConfigDict, Field

from . import interface_node as node
from .artifact_factory import ArtifactFactory

router = APIRouter(prefix='/interface/v1', tags=['dell-contract'])


def authorize(request: Request, capability: str):
    if request.url.scheme != 'https':
        raise HTTPException(426, 'HTTPS required')
    client = request.headers.get('x-client-id')
    dell_client = request.headers.get('x-jarvis-client-id')
    if client is not None and dell_client is not None and client != dell_client:
        raise HTTPException(400, 'Conflicting client identity headers')
    client = dell_client if dell_client is not None else client
    authorization = request.headers.get('authorization')
    client = node.client_identity(client, authorization, capability)
    try:
        policy = node.client_policy(client)
        expiry = float(policy['expires_at'])
        valid = expiry > time.time() and capability in policy['capabilities']
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise HTTPException(403, 'Client scope expired or unavailable')
    return client, authorization


@router.get('/identity')
def identity(request: Request):
    authorize(request, 'identity.read')
    host_id = os.getenv('PRIME_INTERFACE_HOST_ID', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', host_id):
        raise HTTPException(503, 'Host identity is not configured')
    pin = os.getenv('PRIME_INTERFACE_SPKI_SHA256', '')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', pin):
        raise HTTPException(503, 'Host certificate pin is not configured')
    version = os.getenv('PRIME_INTERFACE_RUNTIME_VERSION', 'UNKNOWN')
    if not re.fullmatch(r'[A-Za-z0-9._+-]{1,96}', version):
        version = 'UNKNOWN'
    candidate_status = os.getenv('PRIME_INTERFACE_CANDIDATE_STATUS', 'UNKNOWN')
    if candidate_status not in {'UNKNOWN', 'ISOLATED_CANDIDATE', 'QUALIFICATION_RUNTIME', 'PRODUCTION'}:
        candidate_status = 'UNKNOWN'
    revision = os.getenv('PRIME_INTERFACE_RUNTIME_REVISION', 'UNKNOWN').strip().lower()
    if revision != 'UNKNOWN' and not re.fullmatch(r'[0-9a-f]{40}', revision):
        revision = 'UNKNOWN'
    result = {'contract': 'jarvis.interface.v1', 'host_id': host_id,
            'role': 'AUTHORITATIVE_PRIME_HOST', 'client_role': 'THIN_CLIENT',
            'runtime_version': version, 'runtime_revision': revision,
            'candidate_status': candidate_status,
            'tls_spki_sha256': pin.lower(), 'transport': 'HTTPS',
            'pin_verification': 'Client must independently verify the TLS peer against its adopted pin'}
    if request.headers.get('x-jarvis-client-id') is not None:
        public_key = os.getenv('PRIME_INTERFACE_PUBLIC_KEY', '')
        if not public_key or len(public_key) > 8192 or 'PRIVATE KEY' in public_key:
            raise HTTPException(503, 'Public identity key is not configured')
        canonical = {'hostname': result['host_id'], 'role': 'AUTHORITATIVE_PRIME',
                     'protocolVersion': '1', 'publicKey': public_key}
        result.update(canonical)
        result['identity_sha256'] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest().upper()
    return result


@router.get('/health')
def health(request: Request):
    client, auth = authorize(request, 'health.read')
    return node.health(client, auth)


def task_wire(value, request, task_id=None):
    if request.headers.get('x-jarvis-client-id') is None:
        return value
    result = dict(value)
    result['taskId'] = value.get('task_id', value.get('id', task_id or ''))
    # Preserve exact internal state separately; do not turn partial failure into success.
    result['internal_state'] = value.get('state')
    result['state'] = {'COMPLETED_WITH_FAILURES': 'FAILED', 'CANCELLED': 'FAILED',
        'CANCELLATION_REQUESTED': 'WAITING', 'INTERRUPTED': 'RECOVERING',
        'reconciliation_required': 'RECOVERING', 'WAITING FOR RESOURCE': 'WAITING',
        'QUEUED': 'WAITING'}.get(value.get('state'), value.get('state'))
    result['message'] = value.get('message', result['internal_state'] or '')
    result['updatedAt'] = value.get('updatedAt', value.get('updated_at', ''))
    metadata=value.get('execution_metadata')
    if metadata is not None:
        if metadata.get('task_id')!=result['taskId']:
            raise HTTPException(500,'Authoritative task metadata binding mismatch')
        result['executionMetadata']=metadata
    return result


@router.post('/objectives', status_code=202)
def submit(body: dict, request: Request):
    client, auth = authorize(request, 'objective.submit')
    body = dict(body)
    key = request.headers.get('idempotency-key')
    if key is not None:
        if 'idempotency_key' in body and body['idempotency_key'] != key:
            raise HTTPException(400, 'Conflicting idempotency keys')
        body['idempotency_key'] = key
    try:
        objective = node.Objective.model_validate(body)
    except ValidationError:
        raise HTTPException(422, 'Invalid objective payload')
    return task_wire(node.submit(objective, client, auth), request)




class Continuation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    objective: str=Field(min_length=1,max_length=20000)
    context: str=Field(default='',max_length=76000)
    expected_revision: int=Field(ge=0,strict=True)
    idempotency_key: str=Field(min_length=1,max_length=100)


@router.post('/tasks/{task_id}/continue',status_code=202)
def continue_task(task_id: str,body: dict,request: Request):
    client,auth=authorize(request,'objective.submit')
    node.own_task(task_id,client)
    body=dict(body)
    key=request.headers.get('idempotency-key')
    if key is not None:
        if 'idempotency_key' in body and body['idempotency_key']!=key:raise HTTPException(400,'Conflicting idempotency keys')
        body['idempotency_key']=key
    try:turn=Continuation.model_validate(body)
    except ValidationError:raise HTTPException(422,'Invalid continuation payload')
    policy=node.client_policy(client)
    objective=node.objective_api.ObjectiveRequest(objective=turn.objective,context=turn.context,
        data_classification=policy.get('data_classification','LOCAL_ONLY'),max_cost_usd=policy.get('max_cost_usd',0),
        priority=node.dispatch_priority(policy))
    return node.objective_api.continue_objective(task_id,objective,turn.expected_revision,turn.idempotency_key,node.owner_transport())


@router.get('/tasks/{task_id}')
def task(task_id: str, request: Request):
    client, auth = authorize(request, 'task.read')
    return task_wire(node.task_status(task_id, client, auth), request, task_id)


@router.post('/tasks/{task_id}/cancel')
def cancel(task_id: str, request: Request):
    client, auth = authorize(request, 'task.cancel')
    return task_wire(node.cancel(task_id, client, auth), request, task_id)


@router.get('/tasks/{task_id}/events')
def events(task_id: str, request: Request):
    # A bounded reconnectable SSE snapshot, not the process-wide audit ledger.
    # Ownership is checked before headers; the opaque digest permits deduplication
    # without persisting a second event/task database.
    client, auth = authorize(request, 'task.read')
    status = node.task_status(task_id, client, auth)
    payload = {'task_id': task_id, 'state': status['state'], 'revision':status.get('revision',0),
               'jobs': [{'id': step['job'].get('id'), 'status': step['job'].get('status')}
                        for step in status.get('steps', []) if 'job' in step]}
    payload = task_wire(payload, request, task_id)
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    cursor = hashlib.sha256(raw.encode()).hexdigest()
    event_type = '' if request.headers.get('x-jarvis-client-id') is not None else 'event: task.status\n'
    frame = '' if request.headers.get('last-event-id') == cursor else f'id: {cursor}\n{event_type}data: {raw}\n\n'
    return StreamingResponse(iter([frame]), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Event-Mode': 'bounded-snapshot'})


@router.get('/tasks/{task_id}/artifacts')
def artifacts(task_id: str, request: Request, offset: int = 0, limit: int = 100):
    client, _ = authorize(request, 'artifact.read')
    node.own_task(task_id, client)
    if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
        raise HTTPException(422, 'Invalid page bounds')
    # The adopted seven-route protocol has no separate materialization POST.
    # Resolve a terminal result to its stable ArtifactFactory snapshot here;
    # unfinished tasks remain readable and produce no placeholder artifact.
    status = node.objective_api.get(task_id, node.owner_transport())
    if status.get('state') in {'COMPLETED', 'COMPLETED_WITH_FAILURES'}:
        latest=node.create_task_artifact(task_id, node.owner_transport())
    else:latest=None
    factory = ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR', '/data')) / 'artifacts')
    items = []
    # Only application-owned, integrity-verified metadata is published. No paths,
    # raw prompts, other-client artifacts or process-wide records are returned.
    for folder in sorted(factory.root.iterdir()):
        try:
            metadata, raw = factory.retrieve(folder.name)
        except (ValueError, KeyError, FileNotFoundError, OSError):
            continue
        if metadata.get('task_id') == task_id:
            from .public_task_errors import publishable_task_artifact
            if not publishable_task_artifact(metadata,raw):continue
            items.append({key: metadata[key] for key in ('artifact_id', 'task_id', 'type', 'sha256', 'bytes', 'validation_state')}
                | {'runtime_revision':metadata.get('runtime_revision','UNKNOWN'),'provenance':'ARTIFACT_STORE'})
    if request.headers.get('x-jarvis-client-id') is not None:
        items = [dict(item, artifactId=item['artifact_id'], taskId=item['task_id'],
                      status=item['validation_state']) for item in items]
    artifact_metadata=None if latest is None else {
        'artifact_id':latest['artifact_id'],'sha256':latest['sha256'],'bytes':latest['bytes'],
        'provenance':'ARTIFACT_STORE'}
    return {'task_id': task_id, 'taskId': task_id, 'revision':status.get('revision',0),
            'latest_result_artifact_id':latest.get('artifact_id') if latest else None, 'artifacts': items[offset:offset + limit],
            'authoritative_artifact':artifact_metadata,
            'next_offset': offset + limit if offset + limit < len(items) else None}


@router.get('/artifacts/{artifact_id}')
def artifact(artifact_id: str, request: Request):
    client, auth = authorize(request, 'artifact.read')
    return node.artifact(artifact_id, client, auth)
