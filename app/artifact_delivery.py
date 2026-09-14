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
        for folder in factory.root.iterdir():
            try:
                metadata,raw=factory.retrieve(folder.name)
            except (ValueError,KeyError,FileNotFoundError,OSError):
                continue
            if metadata.get('task_id')==task_id and metadata.get('type')=='json':
                try:existing=json.loads(raw)
                except (ValueError,UnicodeError):continue
                if existing==task:return metadata
        payload={'kind':'json','content':json.dumps(task,indent=2,sort_keys=True),'task_id':task_id,
                 'creator':'a09','provenance':'Source-labelled governed objective results'}
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
