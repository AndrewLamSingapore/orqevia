"""Bounded logical orchestration over the single shared inference scheduler."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from .agent_dispatch_api import AgentRequest, dispatch_request
from .agent_registry import RegistryError, agent_record, canonical_agent_id, responsibility_owner
from .agent_runtime import DOMAIN_CHILDREN
from . import compute_queue_api
from .client_auth import authenticate_owner
from .ready_work import WorkItem, run_ready_work

router=APIRouter(prefix='/api/agents/objectives',tags=['governed-objectives'])


def utcnow():
    return datetime.now(timezone.utc).isoformat()


_INFERENCE_CODES = frozenset('''AUTHENTICATION CANCELLED CAPACITY CIRCUIT_CLOCK_INVALID
CIRCUIT_INFLIGHT_LIMIT CIRCUIT_PROVIDER_INVALID CIRCUIT_REGISTRY_FULL
CONTEXT_BUDGET_EXCEEDED CREDENTIAL_UNAVAILABLE DATA_LOCALITY
EMPTY_OR_INCOMPLETE_RESPONSE FALLBACK_CONFIGURATION_INVALID FALLBACK_EXHAUSTED
FALLBACK_POLICY_DENIED FALLBACK_UNQUALIFIED HF_BUDGET_NOT_RESERVED
HF_CREDENTIAL_SCOPE_DENIED HF_EXPLICIT_SELECTION_REQUIRED HF_FALLBACK_NOT_PERMITTED
HF_FALLBACK_POLICY_INVALID HF_NON_HF_FALLBACK_NOT_PERMITTED INCOMPLETE_STREAM
INVALID_MESSAGES INVALID_QA_ANSWER_SPAN INVALID_QA_INPUT INVALID_RETRY_LIMIT
INVALID_TIMEOUT INVALID_USAGE MALFORMED_QA_RESPONSE MALFORMED_STREAM
MODEL_PROVIDER_UNPINNED OUTPUT_BUDGET_EXHAUSTED OUTPUT_BUDGET_INVALID
PROVIDER_ADAPTER_FAILURE PROVIDER_CIRCUIT_OPEN PROVIDER_HTTP_FAILURE
PROVIDER_STREAM_FAILURE PROVIDER_TIMEOUT PROVIDER_TRANSPORT_FAILURE
PROVIDER_UNAVAILABLE PROVIDER_UNQUALIFIED QA_INPUT_BUDGET_EXCEEDED
QA_RESPONSE_SIZE_EXCEEDED RATE_LIMIT REASONING_BUDGET_CONFIG_INVALID
REASONING_BUDGET_COST_EXCEEDED REASONING_BUDGET_EXTENSION_DENIED
REASONING_BUDGET_PRICE_UNAVAILABLE STREAM_SIZE_EXCEEDED TASK_TIMEOUT
LOCAL_INFERENCE_FAILED STRICT_JSON_CONTRACT_FAILED UNSUPPORTED_COMPLETION'''.split())
_INFERENCE_DETAILS = frozenset(('agent_id', 'provider', 'model', 'cached_tokens',
    'retries', 'success', 'failure_kind', 'requested_tier', 'requested_provider',
    'requested_model', 'fallback_route', 'error_classifications'))


def inference_attempt_projection(jobs):
    """Bounded read-only projection of owned compute attempts, not attestation.

    Attempt task_id is the QUEUE JOB id, not the enclosing objective UUID.
    Missing/malformed evidence never affects execution or becomes a PASS.
    Arbitrary model text, error bodies and credential references are excluded.
    Provider/model names must also match an owned catalog/configuration pair.
    """
    result={'schema_version':'jarvis.inference-attempts.v1', 'source':'COMPUTE_LEDGER',
        'status':'NOT_APPLICABLE', 'attempts':[], 'missing_job_ids':[],
        'verification':'UNVERIFIED', 'timestamp_source':'QUEUE_JOB_LIFECYCLE',
        'attempt_timestamp':'NOT_RECORDED', 'digest_scope':'SANITIZED_PROJECTION_NOT_SIGNATURE'}
    if not jobs:return result

    def reject(reason):
        return {**result, 'status':'INVALID', 'reason':reason, 'attempts':[]}

    def timestamp(value):
        if value is None:return None
        if not isinstance(value,str) or len(value)>40:raise ValueError()
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None or not 2000<=parsed.year<=2100:raise ValueError()
        return parsed.isoformat()

    def integer(value,maximum):
        if value is not None and (type(value) is not int or not 0<=value<=maximum):raise ValueError()
        return value

    def number(value,maximum):
        if value is not None and (type(value) not in (int,float) or
            not math.isfinite(value) or not 0<=value<=maximum):raise ValueError()
        return value

    def unique_json(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError()
            value[key]=item
        return value

    try:
        if len(jobs)>6:raise ValueError()
        bound={}
        for job in jobs:
            jid=job['id']
            if str(uuid.UUID(jid))!=jid or jid in bound:raise ValueError()
            if job.get('status') not in {'queued','running','completed','failed','cancelled'}:raise ValueError()
            agent_record(job['agent'])
            bound[jid]=job
    except (KeyError,TypeError,ValueError,RegistryError):
        return reject('INVALID_QUEUE_BINDING')
    result['missing_job_ids']=sorted(bound)
    path=Path(os.getenv('PRIME_DATA_DIR','/data'))/'compute-ledger.db'
    if not path.is_file():return {**result, 'status':'UNAVAILABLE', 'reason':'COMPUTE_LEDGER_UNAVAILABLE'}
    try:
        from .compute_catalog import load_catalog
        from .agent_dispatch_api import local_model_backends
        pairs={(entry['id'],entry['model']) for entry in load_catalog()}
        pairs.update((entry.name,entry.model) for entry in local_model_backends())
        placeholders=','.join('?' for _ in bound)
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            rows=db.execute('SELECT id,task_id,tier,seconds,tokens,cost,length(details),'
                'substr(details,1,32769) FROM reasoning_attempts WHERE task_id IN ('+
                placeholders+') ORDER BY task_id,id LIMIT 65',tuple(bound)).fetchall()
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        return {**result, 'status':'UNAVAILABLE', 'reason':'COMPUTE_LEDGER_OR_REGISTRY_UNAVAILABLE'}
    try:
        if len(rows)>64:raise ValueError()
        seen=set();covered=set();attempts=[]
        for aid,jid,tier,seconds,tokens,cost,detail_size,raw in rows:
            if not isinstance(aid,str) or not re.fullmatch('[0-9a-f]{32}',aid) or aid in seen:raise ValueError()
            seen.add(aid)
            if jid not in bound or tier not in {'NANO','MINI','FLAGSHIP'}:raise ValueError()
            if type(detail_size) is not int or not 2<=detail_size<=32768:raise ValueError()
            detail=json.loads(raw,object_pairs_hook=unique_json,
                parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(detail,dict) or set(detail)-_INFERENCE_DETAILS:raise ValueError()
            job=bound[jid]
            requested=(detail['requested_provider'],detail['requested_model'])
            selected=(detail['provider'],detail['model'])
            if (detail['agent_id']!=job['agent'] or requested!=(job['provider'],job['model']) or
                requested not in pairs or selected not in pairs or detail['requested_tier']!=tier):raise ValueError()
            if type(detail['success']) is not bool:raise ValueError()
            failure=detail.get('failure_kind')
            if failure is not None and failure not in _INFERENCE_CODES:raise ValueError()
            if detail['success'] and failure is not None:raise ValueError()
            if not detail['success'] and failure is None:raise ValueError()
            routes=detail.get('fallback_route',[]);codes=detail.get('error_classifications',[])
            if not isinstance(routes,list) or len(routes)>4 or not isinstance(codes,list) or len(codes)>16:raise ValueError()
            if any(not isinstance(code,str) or code not in _INFERENCE_CODES for code in codes) or len(set(codes))!=len(codes):raise ValueError()
            if failure is not None and failure not in codes:raise ValueError()
            providers_seen=set()
            for route in routes:
                if not isinstance(route,dict) or set(route)!={'provider','code'}:raise ValueError()
                provider=route['provider']
                if (not isinstance(provider,str) or provider in providers_seen or
                    provider not in {pair[0] for pair in pairs} or route['code'] not in _INFERENCE_CODES):raise ValueError()
                if route['code'] not in codes:raise ValueError()
                providers_seen.add(provider)
            if (not routes and selected!=requested or routes and routes[0]['provider']!=requested[0] or
                detail['success'] and selected[0] in providers_seen):raise ValueError()
            if seconds is None or detail.get('retries') is None:raise ValueError()
            retry_count=integer(detail['retries'],10)
            cached=integer(detail.get('cached_tokens'),10**9)
            total=integer(tokens,10**9)
            if cached is not None and total is not None and cached>total:raise ValueError()
            receipt={'attempt_id':aid,'queue_job_id':jid,'agent_id':job['agent'],
                'requested_provider':requested[0],'requested_model':requested[1],
                'selected_provider':selected[0],'selected_model':selected[1],
                'tier':tier,'success':detail['success'],'failure_code':failure,
                'fallback_route':routes,'error_classifications':codes,'retries':retry_count,
                'total_tokens':total,'cached_tokens':cached,'cost_usd':number(cost,100),
                'elapsed_seconds':number(seconds,86400),
                'job_started_at':timestamp(job.get('started_at')),
                'job_completed_at':timestamp(job.get('completed_at'))}
            receipt['evidence_sha256']=hashlib.sha256(json.dumps(receipt,sort_keys=True,
                separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
            attempts.append(receipt);covered.add(jid)
        result['missing_job_ids']=sorted(set(bound)-covered)
        return {**result,'status':'OBSERVED' if not result['missing_job_ids'] else 'MISSING' if not attempts else 'PARTIAL',
            'attempts':attempts}
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):
        return reject('INVALID_INFERENCE_EVIDENCE')


def model_content(steps,revision):
    values=[]
    for step in steps:
        job=step.get('job',{})
        if step.get('revision',0)==revision and job.get('status')=='completed' and isinstance(job.get('result'),str) and job['result'].strip():
            values.append(job['result'].strip())
    return '\n\n'.join(values)


def system_content(steps,revision):
    values=[]
    for step in steps:
        dispatch=step.get('dispatch',{})
        if step.get('revision',0)==revision and dispatch.get('state')=='COMPLETED' and dispatch.get('model_backend')=='none' and isinstance(dispatch.get('result'),str):
            values.append(dispatch['result'].strip())
    return '\n\n'.join(filter(None,values))


def system_result(steps,revision):
    """Keep system execution separate from verification of its claims."""
    text=system_content(steps,revision)
    if not text:return None
    assessments=[]
    for step in steps:
        dispatch=step.get('dispatch',{})
        if (step.get('revision',0)!=revision or dispatch.get('state')!='COMPLETED'
                or dispatch.get('model_backend')!='none'
                or not isinstance(dispatch.get('result'),str) or not dispatch['result'].strip()):continue
        fact=dispatch.get('system_fact')
        bound=(isinstance(fact,dict) and fact.get('text')==dispatch['result']
               and fact.get('status') in {'VERIFIED','PARTIAL','UNVERIFIED','UNAVAILABLE','STALE','CONTRADICTED'}
               and isinstance(fact.get('provenance'),str)
               and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',fact['provenance']))
        assessments.append({'verification_status':fact['status'] if bound else 'UNVERIFIED',
                            'provenance':fact['provenance'] if bound else 'UNAVAILABLE'})
    states={item['verification_status'] for item in assessments}
    provenance={item['provenance'] for item in assessments}
    status=next(iter(states)) if len(states)==1 else 'PARTIAL' if states & {'VERIFIED','PARTIAL'} else 'UNVERIFIED'
    return {'type':'SYSTEM_FACT','text':text,'authoritative':states=={'VERIFIED'},
            'verification_status':status,
            'provenance':next(iter(provenance)) if len(provenance)==1 else 'MULTIPLE_SYSTEM_SOURCES',
            'source_assessments':assessments,'may_update_truth_plane':False}


def metadata_contradictions(text,metadata):
    """Detect claims that resemble authoritative facts without promoting them."""
    if not text:return []
    findings=[]
    task_id=metadata['task_id'].lower()
    for value in sorted(set(re.findall(r'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b',text))):
        if value.lower()!=task_id:findings.append({'kind':'TASK_ID_CONTRADICTION','claim':value,'authoritative':metadata['task_id'],'provenance':'MODEL_CONTENT'})
    authoritative_times={value for value in (metadata.get('created_at'),metadata.get('started_at'),metadata.get('completed_at')) if value}
    for value in sorted(set(re.findall(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b',text))):
        if value not in authoritative_times:findings.append({'kind':'TIMESTAMP_CONTRADICTION','claim':value,'authoritative':sorted(authoritative_times),'provenance':'MODEL_CONTENT'})
    revision=metadata.get('runtime',{}).get('source_revision')
    for value in sorted(set(re.findall(r'(?i)(?:(?:production|source|runtime)\s+(?:sha|revision)\s*[:=]?\s*)([0-9a-f]{40,64})',text))):
        if revision=='UNKNOWN' or value.lower()!=revision:findings.append({'kind':'RUNTIME_IDENTITY_CONTRADICTION','claim':value,'authoritative':revision,'provenance':'MODEL_CONTENT'})
    if re.search(r'(?i)\b(?:runtime|prime\.state)\s+(?:is\s+)?(?:independently\s+)?verified\b',text):
        findings.append({'kind':'UNSUPPORTED_VERIFICATION_CLAIM','claim':'VERIFIED','authoritative':'NOT_ESTABLISHED_BY_MODEL_CONTENT','provenance':'MODEL_CONTENT'})
    for value in sorted(set(re.findall(r'(?i)\b(?:execution\s+)?status\s*[:=]\s*(COMPLETED_WITH_FAILURES|COMPLETED|FAILED|RUNNING|QUEUED|VERIFIED)\b',text))):
        if value.upper()!=metadata.get('state'):findings.append({'kind':'EXECUTION_STATE_CONTRADICTION','claim':value.upper(),'authoritative':metadata.get('state'),'provenance':'MODEL_CONTENT'})
    for value in sorted(set(re.findall(r'(?i)\b(?:artifact\s+)?sha-?256\s*[:=]\s*([0-9a-f]{64})\b',text))):
        findings.append({'kind':'UNSUPPORTED_ARTIFACT_DIGEST_CLAIM','claim':value.lower(),'authoritative':'ARTIFACT_STORE_ONLY','provenance':'MODEL_CONTENT'})
    selected={item.get('selected_agent_id') for item in metadata.get('agent_execution',[]) if item.get('selected_agent_id')}
    for value in sorted(set(re.findall(r'(?i)\bI\s+am\s+(a\d{2})\b',text))):
        if value.lower() not in selected:findings.append({'kind':'AGENT_IDENTITY_CONTRADICTION','claim':value.lower(),'authoritative':sorted(selected),'provenance':'MODEL_CONTENT'})
    if re.search(r'(?i)\b(?:I\s+am|I\s+have|my\s+role\s+is)\s+(?:the\s+)?(?:Owner|Administrator)\b',text):
        findings.append({'kind':'UNSUPPORTED_AUTHORITY_CLAIM','claim':'OWNER_OR_ADMINISTRATOR','authoritative':'IDENTITY_SERVICE_AND_REGISTRY_ONLY','provenance':'MODEL_CONTENT'})
    return findings


def agent_execution_metadata(step):
    job=step.get('job',{})
    selected=job.get('agent')
    capability=step.get('capability')
    result={'task_binding':'OBJECTIVE_STORE','selected_agent_id':selected,'capability_used':capability,
        'model':job.get('model'),'provider':job.get('provider'),'selection_reason_code':'CANONICAL_RESPONSIBILITY_OWNER',
        'provenance':{'selected_agent_id':'QUEUE','capability_used':'SYSTEM','role':'REGISTRY',
            'tool_policy':'REGISTRY','model':'RUNTIME','authority_scope':'REGISTRY'}}
    try:
        record=agent_record(selected)
        owner=responsibility_owner(capability)
        if owner!=selected:raise RegistryError('selected agent does not own capability')
        result.update({'canonical_role':record.get('role'),'allowed_tools':record.get('tool_eligibility',[]),
            'authority_scope':record.get('tap_relationship',{}),'delegation_targets':record.get('allowed_delegation_targets',[]),
            'verification_requirements':record.get('observability',{}),'registry_binding':'VERIFIED'})
    except (RegistryError,TypeError):
        result.update({'canonical_role':'UNKNOWN','allowed_tools':[],'authority_scope':'UNKNOWN',
            'delegation_targets':[],'verification_requirements':'UNKNOWN','registry_binding':'NO_AUTHORIZED_ROUTE'})
    return result


class ObjectiveRequest(AgentRequest):
    capability: str = 'auto'
    capabilities: list[str] = Field(default_factory=list,max_length=6)


READY_PRIORITY = {
    'critical': 'P0',
    'high': 'P1',
    'normal': 'P2',
    'low': 'P3',
    'background': 'P3',
}


def dispatch_ready_capabilities(capabilities, run, *, priority='normal'):
    """Schedule independent objective dispatches without occupying inference slots.

    This is only the submission stage: model jobs remain governed by the
    compute queue, and a submitted contribution is not an accepted objective.
    The per-request ready-work lane reflects the authenticated request priority;
    it is not a global priority scheduler across objective requests.
    """
    if priority not in READY_PRIORITY:
        raise ValueError('invalid ready-work priority')
    if not capabilities:
        return []
    items = [WorkItem(f"dispatch-{index}", lambda capability=capability: run(capability),
                      owner=priority == 'critical', priority=READY_PRIORITY[priority])
             for index, capability in enumerate(capabilities)]
    outcomes = run_ready_work(items, max_parallel=min(3, len(items)))
    return [outcomes[item.id].value if outcomes[item.id].status == "completed" else
            {"capability": capability, "state": "indeterminate", "reason": "STEP_DISPATCH_FAILED"}
            for item, capability in zip(items, capabilities)]


def select_capabilities(objective: str) -> list[str]:
    text=objective.lower()
    scored=[]
    for domain,children in DOMAIN_CHILDREN.items():
        for actor,keywords in children:
            score=sum(keyword in text for keyword in keywords)
            if score:
                scored.append((score,domain,actor))
    scored.sort(key=lambda row:(-row[0],row[1],row[2]))
    selected=[]
    owners=set()
    for _,_,actor in scored:
        owner=canonical_agent_id(actor)
        if owner not in owners:
            owners.add(owner)
            selected.append('responsibility.'+actor)
        if len(selected)==3:
            break
    return selected or ['responsibility.a02']


def connect(*, read_only=False):
    path=Path(os.getenv('PRIME_DATA_DIR','/data'))/'objectives.db'
    if read_only:
        if not path.is_file():raise HTTPException(404,'Objective not found')
        return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',timeout=15,uri=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15)
    # Keep the original tables byte-for-byte compatible with the rollback image.
    # New system timestamps live in an additive side table old runtimes ignore.
    db.execute('CREATE TABLE IF NOT EXISTS objectives (id TEXT PRIMARY KEY, objective_hash TEXT NOT NULL, state TEXT NOT NULL, steps_json TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS objective_turns (task TEXT NOT NULL, revision INTEGER NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, steps_json TEXT NOT NULL, PRIMARY KEY(task,revision), UNIQUE(task,idempotency_key))')
    db.execute('CREATE TABLE IF NOT EXISTS objective_metadata (task TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(task,revision))')
    db.execute('CREATE TABLE IF NOT EXISTS objective_runtime (task TEXT NOT NULL, revision INTEGER NOT NULL, host_id TEXT NOT NULL, source_revision TEXT NOT NULL, version TEXT NOT NULL, image_digest TEXT, PRIMARY KEY(task,revision))')
    db.commit()
    return db


def runtime_snapshot():
    source=os.getenv('PRIME_RUNTIME_REVISION',os.getenv('PRIME_INTERFACE_RUNTIME_REVISION','')).strip().lower()
    host=os.getenv('PRIME_INTERFACE_HOST_ID','').strip()
    version=os.getenv('PRIME_INTERFACE_RUNTIME_VERSION','').strip()
    image=os.getenv('PRIME_RUNTIME_IMAGE_DIGEST','').strip() or None
    return {
        'host_id':host if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}',host) else 'UNKNOWN',
        'source_revision':source if re.fullmatch(r'[0-9a-f]{40}',source) else 'UNKNOWN',
        'version':version if version else 'UNKNOWN',
        'image_digest':image if image and re.fullmatch(r'sha256:[0-9a-f]{64}',image) else None,
    }


def store_runtime(db,task,revision):
    value=runtime_snapshot()
    db.execute('INSERT INTO objective_runtime VALUES(?,?,?,?,?,?)',(task,revision,value['host_id'],value['source_revision'],value['version'],value['image_digest']))


@router.post('',status_code=202)
def submit(body: ObjectiveRequest,authorization: str | None=Header(default=None)):
    authenticate_owner(authorization)
    from .operational_workflows import from_objective, execute_workflow
    from .system_architecture import architecture_answer,is_architecture_question
    architecture=architecture_answer(body.objective) if (not body.deterministic_operation
        and body.capability=='auto' and not body.capabilities and is_architecture_question(body.objective)) else None
    workflow_body=from_objective(body.objective,body.context) if architecture is None and not body.deterministic_operation and body.capability=='auto' and not body.capabilities else None
    capabilities=list(dict.fromkeys(body.capabilities or ([body.capability] if body.capability!='auto' else select_capabilities(body.objective))))
    from .runtime_status import is_runtime_status
    if not body.deterministic_operation and is_runtime_status(body.objective,body.context):
        capabilities=['responsibility.a19']
    if body.deterministic_operation:
        capabilities=capabilities[:1]
    task_id=str(uuid.uuid4())
    db=connect()
    try:
        created=utcnow()
        db.execute('INSERT INTO objectives VALUES(?,?,?,?)',(task_id,hashlib.sha256(body.objective.encode()).hexdigest(),'dispatching',json.dumps(capabilities)))
        db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',(task_id,0,created,created))
        store_runtime(db,task_id,0)
        db.commit()
        if architecture is not None:
            steps=[{'capability':'system.architecture','dispatch':{'state':'COMPLETED','task_id':task_id,
                'result':architecture['text'],'system_fact':architecture,'model_backend':'none'}}]
            db.execute('UPDATE objectives SET state=?,steps_json=? WHERE id=?',('submitted',json.dumps(steps),task_id))
            db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=0',(utcnow(),task_id));db.commit()
            from .public_task_errors import public_task
            return public_task({'id':task_id,'steps':steps,'physical_inference_limit':compute_queue_api.queue.policy.global_concurrency,
                'semantics':'Canonical system-owned architecture lookup; no model self-description'})
        if workflow_body is not None:
            try:
                outcome=execute_workflow(workflow_body,parent_task_id=task_id)
                if outcome['status']=='COMPLETED':
                    steps=[{'capability':'workflow.'+outcome['template'],'dispatch':{
                        'state':'COMPLETED','task_id':task_id,'workflow':outcome,
                        'artifacts':outcome['artifacts'],'model_backend':'deterministic'}}]
                else:
                    steps=[{'capability':'workflow.'+outcome['template'],'state':'failed',
                            'reason':'WORKFLOW_EXECUTION_FAILED','workflow':outcome}]
            except Exception as exc:
                steps=[{'capability':'workflow.operational','state':'failed','reason':type(exc).__name__}]
            db.execute('UPDATE objectives SET state=?,steps_json=? WHERE id=?',('submitted',json.dumps(steps),task_id))
            db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=0',(utcnow(),task_id))
            db.commit()
            from .public_task_errors import public_task
            return public_task({'id':task_id,'steps':steps,'physical_inference_limit':compute_queue_api.queue.policy.global_concurrency,
                                'semantics':'Named deterministic operational workflow; artifact validation reported separately from execution completion'})
        def run(capability):
            try:
                request=AgentRequest(**{**body.transport_dump(exclude={'capabilities'}),'capability':capability})
                return {'capability':capability,'dispatch':dispatch_request(request,authorization,parent_task_id=task_id)}
            except HTTPException as exc:
                return {'capability':capability,'state':'blocked','reason':exc.detail}
            except Exception as exc:
                # No automatic retry: the authority/queue may already have accepted
                # this step. Preserve an indeterminate result for reconciliation.
                return {'capability':capability,'state':'indeterminate','reason':type(exc).__name__}
        steps=dispatch_ready_capabilities(capabilities,run,priority=body.priority)
        db.execute('UPDATE objectives SET state=?,steps_json=? WHERE id=?',('submitted',json.dumps(steps),task_id))
        db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=0',(utcnow(),task_id))
        db.commit()
        from .public_task_errors import public_task
        return public_task({'id':task_id,'steps':steps,'physical_inference_limit':compute_queue_api.queue.policy.global_concurrency,
                'semantics':'Independent advisory contributions; no delegated execution authority'})
    finally:
        db.close()


def _timestamp_provenance(recorded,jobs,*,created_at,started_at,completed_at,updated_at,
                          completed_from_queue):
    """Label the selected stored values without changing times or verifying claims."""
    queue_updates=[job.get('completed_at') or job.get('started_at') or job.get('created_at') for job in jobs]
    update_sources=set()
    if updated_at is not None:
        if recorded[1] and updated_at==recorded[1]:update_sources.add('OBJECTIVE_METADATA')
        if updated_at in queue_updates:update_sources.add('QUEUE')
    def label(sources):
        return '_AND_'.join(source for source in ('OBJECTIVE_METADATA','QUEUE') if source in sources) or 'UNAVAILABLE'
    fields={
        'created_at':'UNAVAILABLE' if created_at is None else 'OBJECTIVE_METADATA' if recorded[0] else 'QUEUE',
        'started_at':'UNAVAILABLE' if started_at is None else 'QUEUE',
        'completed_at':'UNAVAILABLE' if completed_at is None else 'QUEUE' if completed_from_queue else label(update_sources),
        'updated_at':label(update_sources),
    }
    sources=set()
    for value in fields.values():
        if value in {'OBJECTIVE_METADATA','OBJECTIVE_METADATA_AND_QUEUE'}:sources.add('OBJECTIVE_METADATA')
        if value in {'QUEUE','OBJECTIVE_METADATA_AND_QUEUE'}:sources.add('QUEUE')
    return label(sources),fields


def _get(task_id: str,authorization: str | None,*,read_only=False):
    authenticate_owner(authorization)
    db=connect(read_only=True) if read_only else connect()
    try:
        row=db.execute('SELECT state,steps_json FROM objectives WHERE id=?',(task_id,)).fetchone()
        turns=db.execute('SELECT revision,state,steps_json FROM objective_turns WHERE task=? ORDER BY revision',(task_id,)).fetchall()
        timing={item[0]:(item[1],item[2]) for item in db.execute(
            'SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=?',(task_id,)).fetchall()}
        runtime_rows={item[0]:{'host_id':item[1],'source_revision':item[2],'version':item[3],'image_digest':item[4]}
            for item in db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=?',(task_id,)).fetchall()}
    finally:
        db.close()
    if row is None:
        raise HTTPException(404,'Objective not found')
    if row[0]=='dispatching':
        return {'id':task_id,'state':'reconciliation_required','reason':'Dispatch was interrupted; do not automatically replay'}
    revision=turns[-1][0] if turns else 0
    steps=json.loads(row[1])
    for step in steps:step['revision']=0
    for turn_revision,turn_state,turn_steps in turns:
        for step in json.loads(turn_steps):
            step['revision']=turn_revision
            steps.append(step)
    for step in steps:
        if 'dispatch' in step and step['dispatch'].get('state')=='COMPLETED':
            step['state']='completed'
        elif 'job' in step.get('dispatch',{}):
            job=compute_queue_api.queue.get(step['dispatch']['job']['id'])
            step['job']={key:job.get(key) for key in ('id','agent','model','provider','status','result','error','created_at','started_at','completed_at')}
    states=[step.get('job',{}).get('status',step.get('state','unknown')) for step in steps if step['revision']==revision]
    state='RUNNING' if 'running' in states else 'WAITING FOR RESOURCE' if 'queued' in states else 'COMPLETED' if states and all(value=='completed' for value in states) else 'COMPLETED_WITH_FAILURES'
    if turns and turns[-1][1]=='dispatching':state='reconciliation_required'
    current_steps=[step for step in steps if step.get('revision',0)==revision]
    jobs=[step.get('job',{}) for step in current_steps if step.get('job')]
    recorded=timing.get(revision,(None,None))
    created_at=recorded[0] or min((job.get('created_at') for job in jobs if job.get('created_at')),default=None)
    observed_updates=[value for value in [recorded[1],*(job.get('completed_at') or job.get('started_at') or job.get('created_at') for job in jobs)] if value]
    updated_at=max(observed_updates,default=None)
    started_at=min((job.get('started_at') for job in jobs if job.get('started_at')),default=None)
    completed_at=max((job.get('completed_at') for job in jobs if job.get('completed_at')),default=None) if state in {'COMPLETED','COMPLETED_WITH_FAILURES'} else None
    completed_from_queue=completed_at is not None
    deterministic=system_content(steps,revision)
    if state=='COMPLETED' and deterministic and completed_at is None:completed_at=updated_at
    lifecycle={}
    if state in {'COMPLETED','COMPLETED_WITH_FAILURES'} and started_at is None:
        lifecycle['started_at_reason']='NO_EXECUTION_STARTED_DISPATCH_BLOCKED' if any(step.get('state')=='blocked' for step in current_steps) else 'NO_EXECUTION_START_RECORDED'
    if state in {'COMPLETED','COMPLETED_WITH_FAILURES'} and completed_at is None:
        completed_at=updated_at;lifecycle['completed_at_source']='TERMINAL_STATE_OBSERVED_AT_OBJECTIVE_UPDATE'
    state_provenance=('OBJECTIVE_DISPATCH' if not jobs or state=='reconciliation_required' else
        'QUEUE' if len(jobs)==len(current_steps) else 'QUEUE_AND_OBJECTIVE_DISPATCH')
    timestamps_provenance,timestamp_fields=_timestamp_provenance(recorded,jobs,
        created_at=created_at,started_at=started_at,completed_at=completed_at,updated_at=updated_at,
        completed_from_queue=completed_from_queue)
    runtime=runtime_rows.get(revision)
    runtime_provenance='IMMUTABLE_OBJECTIVE_RUNTIME' if runtime else 'UNAVAILABLE_LEGACY_TASK'
    if runtime is None:runtime={'host_id':'UNKNOWN','source_revision':'UNKNOWN','version':'UNKNOWN','image_digest':None}
    metadata={
        'schema_version':'jarvis.authoritative-execution.v1','authoritative':True,
        'task_id':task_id,'revision':revision,'state':state,
        'created_at':created_at,'started_at':started_at,'completed_at':completed_at,'updated_at':updated_at,
        'runtime':runtime,
        'jobs':[{'job_id':job.get('id'),'agent':job.get('agent'),'model':job.get('model'),'provider':job.get('provider'),
            'state':job.get('status'),'created_at':job.get('created_at'),
            'started_at':job.get('started_at'),'completed_at':job.get('completed_at')} for job in jobs],
        'agent_execution':[agent_execution_metadata(step) for step in current_steps if step.get('job')],
        'inference_attempts':inference_attempt_projection(jobs),
        'provenance':{'task_id':'DATABASE','state':state_provenance,'timestamps':timestamps_provenance,
            'timestamp_fields':timestamp_fields,'jobs':'QUEUE',
            'authority':'IDENTITY_SERVICE','artifact':'ARTIFACT_STORE','verification':'VERIFIER','runtime':runtime_provenance},
        'closed_world_policy':'UNKNOWN_WHEN_CANONICAL_SOURCE_HAS_NO_VALUE',
        'model_content_is_authoritative_metadata':False,
        'lifecycle':lifecycle,
    }
    content=model_content(steps,revision)
    contradictions=metadata_contradictions(content,metadata)
    from .public_task_errors import public_task
    return public_task({'id':task_id,'revision':revision,'state':state,'steps':steps,
        'execution_metadata':metadata,'updated_at':updated_at,
        'result':system_result(steps,revision) if deterministic else {'type':'MODEL_CONTENT','text':content,'authoritative':False,
            'epistemic_status':'GENERATED_CLAIM','verification_status':'VERIFY_REQUIRED',
            'may_update_truth_plane':False,'contradictions':contradictions} if content else None,
        'synthesis':'Source-labelled advisory contributions; model content is not execution metadata'})


@router.get('/{task_id}')
def get(task_id: str,authorization: str | None=Header(default=None)):
    return _get(task_id,authorization,read_only=False)


def get_read_only(task_id: str,authorization: str | None):
    return _get(task_id,authorization,read_only=True)


def continue_objective(task_id, body, expected_revision, idempotency_key, authorization):
    """Reserve once before dispatch; an interrupted reservation is never replayed."""
    authenticate_owner(authorization)
    digest=hashlib.sha256(json.dumps({'body':body.transport_dump(),'expected_revision':expected_revision},sort_keys=True).encode()).hexdigest()
    db=connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT revision,digest,state FROM objective_turns WHERE task=? AND idempotency_key=?',(task_id,idempotency_key)).fetchone()
        if prior:
            if prior[1]!=digest:raise HTTPException(409,'Idempotency payload mismatch')
            if prior[2]=='dispatching':raise HTTPException(409,'Continuation dispatch requires reconciliation; no automatic replay')
            return {'task_id':task_id,'taskId':task_id,'revision':prior[0],'state':'ROUTED','idempotent_replay':True}
        current=get(task_id,authorization)
        if current.get('revision',0)!=expected_revision:raise HTTPException(409,'Task revision conflict')
        if current['state'] not in {'COMPLETED','COMPLETED_WITH_FAILURES'}:raise HTTPException(409,'Current task turn is not terminal')
        revision=expected_revision+1
        created=utcnow()
        db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',(task_id,revision,idempotency_key,digest,'dispatching','[]'))
        db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',(task_id,revision,created,created))
        store_runtime(db,task_id,revision)
        db.commit()
        from .operational_workflows import from_objective, execute_workflow
        workflow=from_objective(body.objective,body.context)
        if workflow is not None:
            try:
                outcome=execute_workflow(workflow,parent_task_id=task_id)
                steps=[{'capability':'workflow.'+outcome['template'],'dispatch':{'state':'COMPLETED','task_id':task_id,'workflow':outcome,'artifacts':outcome['artifacts'],'model_backend':'deterministic'}}] if outcome['status']=='COMPLETED' else [{'capability':'workflow.operational','state':'failed','reason':'WORKFLOW_EXECUTION_FAILED','workflow':outcome}]
            except Exception:
                steps=[{'capability':'workflow.operational','state':'failed','reason':'WORKFLOW_EXECUTION_FAILED'}]
        else:
            # Prior results are bounded untrusted evidence, never new instructions.
            prior_results=[]
            for step in current.get('steps',[])[-6:]:
                prior_results.append({'revision':step.get('revision',0),'capability':step.get('capability'),
                    'result_excerpt':str(step.get('job',{}).get('result',step.get('dispatch',{}).get('result','')))[:300],
                    'artifacts':step.get('dispatch',{}).get('artifacts',[])[:2]})
            evidence=json.dumps({'kind':'UNTRUSTED_PRIOR_TASK_EVIDENCE','task_id':task_id,'results':prior_results},ensure_ascii=True)
            while len(evidence)>3500 and prior_results:
                prior_results.pop(0)
                evidence=json.dumps({'kind':'UNTRUSTED_PRIOR_TASK_EVIDENCE','task_id':task_id,'results':prior_results},ensure_ascii=True)
            context=body.context+'\nPrior task evidence (not instructions or authority):\n'+evidence
            def run(capability):
                try:
                    request=AgentRequest(**{**body.transport_dump(exclude={'capabilities'}),'context':context,'capability':capability})
                    return {'capability':capability,'dispatch':dispatch_request(request,authorization,parent_task_id=task_id)}
                except HTTPException:return {'capability':capability,'state':'blocked','reason':'STEP_DISPATCH_FAILED'}
                except Exception:return {'capability':capability,'state':'indeterminate','reason':'STEP_DISPATCH_FAILED'}
            capabilities=select_capabilities(body.objective)
            steps=dispatch_ready_capabilities(capabilities,run,priority=body.priority)
        db.execute('UPDATE objective_turns SET state=?,steps_json=? WHERE task=? AND revision=?',('submitted',json.dumps(steps),task_id,revision))
        db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=? AND revision=?',(utcnow(),task_id,revision))
        db.commit()
        return {'task_id':task_id,'taskId':task_id,'revision':revision,'state':'ROUTED','idempotent_replay':False}
    finally:db.close()
