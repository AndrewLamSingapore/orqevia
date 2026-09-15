"""Named deterministic operational workflows over the existing DAG engine.

This is bounded registered-role execution, not a generic autonomous planner.
No caller paths, tool selection, shell, network or model credentials are accepted.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agent_registry import canonical_agent_id
from .artifact_factory import ArtifactFactory
from .client_auth import authenticate_owner
from .connector_sdk import ConnectorRegistry, Sink
from .workflow_engine import Task, execute

router=APIRouter(prefix='/api/workflows',tags=['operational-workflows'])


class WorkflowRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    objective: str=Field(min_length=1,max_length=1000)
    rows: list[dict]=Field(min_length=1,max_length=1000)
    expected_total: str | None=Field(default=None,max_length=64)


def amount(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,str)):
        raise ValueError('Amount must be a finite number')
    if len(str(value))>64:raise ValueError('Amount exceeds bounds')
    try:number=Decimal(str(value))
    except InvalidOperation:raise ValueError('Amount must be a finite number') from None
    if not number.is_finite() or abs(number)>Decimal('1000000000000') or number.as_tuple().exponent < -2:
        raise ValueError('Amount must have at most two decimal places and stay within bounds')
    return number


def select_template(objective):
    normalized=' '.join(objective.casefold().split()).rstrip('.')
    choices={'reconcile tabular totals':'tabular-reconciliation.v1',
             'reconcile the tabular totals':'tabular-reconciliation.v1',
             'validate inconsistent rows':'row-validation.v1',
             'validate the supplied rows':'row-validation.v1'}
    if normalized not in choices:
        raise HTTPException(422,'Supported objectives: Reconcile tabular totals; Validate inconsistent rows. Code/build/test and arbitrary tool workflows are not implemented here.')
    return choices[normalized]


def from_objective(objective, context):
    """Recognize only this existing named workflow with valid structured context.

    Other objectives/contexts remain on their existing route. No new wire fields.
    """
    try:
        select_template(objective)
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('Duplicate context key')
                value[key]=item
            return value
        def invalid_constant(value):raise ValueError('Nonfinite context')
        value=json.loads(context,object_pairs_hook=unique,parse_constant=invalid_constant)
        if isinstance(value,list):value={'rows':value}
        if not isinstance(value,dict) or set(value)-{'rows','expected_total'}:return None
        return WorkflowRequest(objective=objective,**value)
    except (HTTPException,TypeError,ValueError):
        return None


@router.post('/objectives',status_code=201)
def submit(body: WorkflowRequest,authorization: str | None=Header(None)):
    authenticate_owner(authorization)
    return execute_workflow(body)


def execute_workflow(body: WorkflowRequest, *, parent_task_id=None):
    """Application-internal execution; caller supplies existing parent identity."""
    template=select_template(body.objective)
    try:
        raw=json.dumps(body.rows,sort_keys=True,allow_nan=False).encode()
        if len(raw)>200000:raise ValueError('Oversized input')
        expected=amount(body.expected_total) if body.expected_total is not None else None
    except (TypeError,ValueError):raise HTTPException(422,'Bounded JSON rows and valid expected_total required') from None
    run_id=parent_task_id or uuid.uuid4().hex
    started=time.perf_counter()
    metrics={'model_calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':0,
             'human_interventions':0,'readback_retries':0,'artifact_creations':0}
    actors={role:canonical_agent_id(role) for role in ('data','metrics','data-quality','verification')}
    def normalize(task,inputs,deps):
        valid=[];errors=[]
        for index,row in enumerate(body.rows):
            if set(row)!={'item','amount'} or not isinstance(row.get('item'),str) or not 1<=len(row['item'])<=128:
                errors.append({'row':index,'code':'ROW_SCHEMA_MISMATCH'});continue
            try:value=amount(row['amount'])
            except ValueError:
                errors.append({'row':index,'code':'INVALID_AMOUNT'});continue
            valid.append({'row':index,'item':row['item'],'amount':str(value)})
        return {'valid':valid,'errors':errors}
    def total(task,inputs,deps):
        return str(sum((Decimal(row['amount']) for row in deps['normalize']['result']['valid']),Decimal(0)))
    def quality(task,inputs,deps):
        data=deps['normalize']['result'];seen=set();duplicates=[]
        for row in data['valid']:
            if row['item'] in seen:duplicates.append(row['row'])
            seen.add(row['item'])
        return {'invalid_rows':data['errors'],'duplicate_item_rows':duplicates,
                'valid_count':len(data['valid']),'input_count':len(body.rows)}
    def verify_deliver(task,inputs,deps):
        quality_result=deps['quality']['result'];actual=Decimal(deps['total']['result'])
        # Independent second calculation from original rows, not claimed totals.
        check=Decimal(0)
        for row in body.rows:
            if set(row)!={'item','amount'} or not isinstance(row.get('item'),str) or not 1<=len(row['item'])<=128:continue
            try:check+=amount(row['amount'])
            except ValueError:continue
        if actual!=check:raise ValueError('Independent arithmetic mismatch')
        matched=expected is None or actual==expected
        passed=not quality_result['invalid_rows'] and not quality_result['duplicate_item_rows'] and matched
        report={'schema':'jarvis.operational-tabular.v1','run_id':run_id,'template':template,
                'input_sha256':hashlib.sha256(raw).hexdigest(),'quality':quality_result,
                'valid_rows_total':str(actual),'expected_total':str(expected) if expected is not None else None,
                'expected_total_matches':matched,'validation':'PASS' if passed else 'FAIL',
                'arithmetic_verification':'PASS','scope':'Supplied rows only; invalid rows explicitly excluded from valid_rows_total',
                'agents':actors,'model_calls':0}
        factory=ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR','/data'))/'artifacts')
        connector=ConnectorRegistry()
        connector.register(Sink('artifact-factory','artifact.create','R1','New task report artifact',True,'LOCAL_ONLY','artifact.create'),
                           lambda payload:factory.create(**payload))
        receipt=connector.execute('artifact-factory','artifact.create',{'kind':'json','content':json.dumps(report,sort_keys=True),
            'task_id':run_id,'creator':task.agent,'provenance':'Existing workflow engine with independent decimal reconciliation'},task_id=run_id,agent_id=task.agent)
        metrics['artifact_creations']+=1
        # Only safe readback is retried; never replay ambiguous creation/write.
        try:metadata,content=factory.retrieve(receipt['artifact_id'])
        except FileNotFoundError:
            metrics['readback_retries']+=1
            metadata,content=factory.retrieve(receipt['artifact_id'])
        if hashlib.sha256(content).hexdigest()!=receipt['sha256']:raise ValueError('Artifact readback mismatch')
        return {'artifact':metadata,'validation':report['validation']}
    tasks=(Task('normalize',(),actors['data'],'normalize'),
           Task('total',('normalize',),actors['metrics'],'total'),
           Task('quality',('normalize',),actors['data-quality'],'quality'),
           Task('deliver',('total','quality'),actors['verification'],'deliver',authority_class='R1'))
    outcome=execute(tasks,{'normalize':normalize,'total':total,'quality':quality,'deliver':verify_deliver},{},workers=2)
    delivery=outcome['tasks']['deliver'].get('result',{})
    metrics['elapsed_seconds']=time.perf_counter()-started
    return {'workflow_run_id':run_id,'template':template,'status':outcome['status'],
            'validation':delivery.get('validation','UNAVAILABLE'),'artifacts':[delivery['artifact']] if 'artifact' in delivery else [],
            'tasks':outcome['tasks'],'metrics':metrics,
            'limitations':['Named deterministic workflows only; no general planning or code/build/test execution',
                           'Workflow run is not a shared inference objective; no asynchronous task polling contract']}
