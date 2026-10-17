"""Materialize completed advisory results through a registered R1 artifact sink."""
import json
import os
from pathlib import Path
import uuid

from fastapi import APIRouter, Header, HTTPException, Response

from . import objective_api
from .client_auth import authenticate_owner
from .artifact_factory import ArtifactFactory
from .connector_sdk import ConnectorRegistry,Sink

router=APIRouter(prefix='/api/artifacts',tags=['artifact-factory'])
MODEL_RESULT_PROVENANCE='Source-labelled governed model result'


def authoritative_envelope(task):
    """Render system-owned facts separately from untrusted model prose."""
    metadata=task.get('execution_metadata',{})
    if metadata.get('task_id')!=task.get('id') or metadata.get('revision')!=task.get('revision'):
        raise HTTPException(409,'Authoritative task metadata binding mismatch')
    runtime=metadata.get('runtime',{})
    value=lambda item: str(item) if item not in (None,'') else 'UNKNOWN'
    return '\n'.join((
        '# JARVIS result', '', '## Authoritative execution metadata', '',
        f"- Task UUID: `{value(metadata.get('task_id'))}`",
        f"- Revision: `{value(metadata.get('revision'))}`",
        f"- State: `{value(metadata.get('state'))}`",
        f"- Created: `{value(metadata.get('created_at'))}`",
        f"- Started: `{value(metadata.get('started_at'))}`",
        f"- Completed: `{value(metadata.get('completed_at'))}`",
        f"- Runtime host: `{value(runtime.get('host_id'))}`",
        f"- Runtime source revision: `{value(runtime.get('source_revision'))}`",
        '', 'These fields come from ORQEVIA system records. UUIDs, timestamps, digests, runtime identity, and authority claims inside model-generated content are not authoritative.',
        '', '## Model-generated content', '',
    ))


def markdown_result(task):
    """Return current-turn successful model text without inventing missing output."""
    revision=task.get('revision',0)
    results=[]
    for step in task.get('steps',[]):
        job=step.get('job',{})
        text=job.get('result')
        if step.get('revision',0)==revision and job.get('status')=='completed' and isinstance(text,str) and text.strip():
            results.append((step.get('capability','result'),text.strip()))
    if not results:return None
    prefix=authoritative_envelope(task)
    if len(results)==1:return prefix+results[0][1]+'\n'
    if results:return prefix+'\n\n'.join('### '+capability+'\n\n'+text for capability,text in results)+'\n'


def create_task_artifact(task_id,authorization):
    authenticate_owner(authorization)
    # Serialize materialization using the existing objective store, not a new
    # task/cache database. Retries return the same verified task snapshot.
    db=objective_api.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        task=objective_api.get(task_id,authorization)
        if task.get('state') not in {'COMPLETED','COMPLETED_WITH_FAILURES'} or any(
                step.get('job',{}).get('status') in {'queued','running','awaiting_approval'}
                for step in task.get('steps',[])):
            raise HTTPException(409,'Task still has unfinished work')
        factory=ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR','/data'))/'artifacts')
        rendered=markdown_result(task)
        kind='markdown' if rendered else 'json'
        content=rendered or json.dumps(task,indent=2,sort_keys=True)
        provenance=MODEL_RESULT_PROVENANCE if rendered else 'Source-labelled governed objective results'
        for folder in factory.root.iterdir():
            try:
                metadata,raw=factory.retrieve(folder.name)
            except (ValueError,KeyError,FileNotFoundError,OSError):
                continue
            if (metadata.get('task_id')==task_id and metadata.get('type')==kind
                    and metadata.get('provenance')==provenance and raw==content.encode()):return metadata
        payload={'kind':kind,'content':content,'task_id':task_id,
                 'creator':'a09','provenance':provenance,
                 'runtime_revision':task.get('execution_metadata',{}).get('runtime',{}).get('source_revision','UNKNOWN')}
        registry=ConnectorRegistry()
        registry.register(Sink('artifact-factory','artifact.create','R1','Create a new immutable application-owned artifact',
                               True,'LOCAL_ONLY','artifact.create'),lambda value:factory.create(**value))
        return registry.execute('artifact-factory','artifact.create',payload,task_id=task_id,agent_id='a09')
    finally:
        db.rollback()
        db.close()


@router.post('/from-task/{task_id}',status_code=201)
def materialize(task_id: str,authorization: str | None=Header(None)):
    return create_task_artifact(task_id,authorization)


@router.get('/{artifact_id}')
def retrieve(artifact_id: str,authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    factory=ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR','/data'))/'artifacts')
    try:metadata,raw=factory.retrieve(artifact_id)
    except (ValueError,KeyError,FileNotFoundError):raise HTTPException(404,'Artifact unavailable')
    from .public_task_errors import publishable_task_artifact
    if not publishable_task_artifact(metadata,raw):raise HTTPException(404,'Artifact unavailable')
    return Response(raw,media_type='application/octet-stream',headers={'X-Artifact-SHA256':metadata['sha256']})
