"""Exact benign status intent, deterministic reads, explicit unavailable fields."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.request import build_opener, ProxyHandler

OBJECTIVE = 'Produce a JARVIS runtime-status report artifact containing current PRIME health, available qualified compute backends, and current task count.'
PHYSICAL_OBJECTIVE = 'Produce a JARVIS runtime status artifact containing current PRIME health, current qualified compute backends, current active task count, current JARVIS protocol version, and timestamp.'
DELL_OBJECTIVE = 'Produce a JARVIS runtime status artifact containing current PRIME health, qualified compute backends, active task count, JARVIS protocol version, and timestamp.'
BRANDED_OBJECTIVES = tuple(value.replace('JARVIS', 'ORQEVIA').replace('PRIME', 'ORQEVIA Core') for value in (OBJECTIVE, PHYSICAL_OBJECTIVE, DELL_OBJECTIVE))
SCHEMA = 'jarvis.runtime-status.v1'


def is_runtime_status(objective, context=''):
    if context.strip():return False
    # Exact allowlist, not keyword matching: additional actions are not swallowed.
    normalize=lambda x:' '.join(x.split()).casefold().rstrip('.')
    return normalize(objective) in {normalize(value) for value in (OBJECTIVE, PHYSICAL_OBJECTIVE, DELL_OBJECTIVE, *BRANDED_OBJECTIVES)}


def production_health():
    try:
        # No proxy, configurable URL, credential, redirect or external request.
        from urllib.request import HTTPRedirectHandler
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        with build_opener(ProxyHandler({}),NoRedirect()).open('http://127.0.0.1:8000/health',timeout=3) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('oversized')
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('shape')
            # Health response is projected, not copied wholesale to artifacts.
            status=value.get('status')
            ok=value.get('ok')
            return {'observation':'OBSERVED','http_status':response.status,
                    'status':status if isinstance(status,str) and len(status)<128 else 'UNKNOWN',
                    'ok':ok if type(ok) is bool else None,
                    'source':'http://127.0.0.1:8000/health'}
    except Exception:
        return {'observation':'UNAVAILABLE','status':'UNKNOWN','ok':None,'http_status':None,
                'source':'http://127.0.0.1:8000/health'}


def qualified_profile():
    path=os.getenv('PRIME_QUALIFIED_PROFILE_PATH','')
    expected=os.getenv('PRIME_QUALIFIED_PROFILE_SHA256','').lower()
    unknown={'status':'UNAVAILABLE','profile_sha256':None,'execution_backends':{},
             'current_backend_availability':'UNMEASURED'}
    if not path or not re.fullmatch('[0-9a-f]{64}',expected):return unknown
    try:
        with Path(path).open('rb') as source:raw=source.read(2_000_001)
        digest=hashlib.sha256(raw).hexdigest()
        if len(raw)>2_000_000 or digest!=expected:return {**unknown,'status':'INTEGRITY_FAILURE'}
        value=json.loads(raw)
        if value.get('identifier')!='abex.compute-profile.v1':raise ValueError('identity')
        backends=value['execution_backends']
        if not isinstance(backends,dict) or any(not isinstance(k,str) or not isinstance(v,str) or len(v)>1024 for k,v in backends.items()):raise ValueError('backends')
        return {'status':'HASH_VERIFIED','profile_sha256':digest,'profile_identifier':value['identifier'],
                'revision':value.get('revision','UNKNOWN'),'profile_host':value.get('host','UNKNOWN'),
                'execution_backends':backends,'normal_workers':value.get('normal_workers'),
                'burst_workers':value.get('burst_workers'),'current_backend_availability':'UNMEASURED',
                'scope':'Historical qualified limits, not a new execution test or activation claim'}
    except Exception:return unknown


def objective_count(root, current_task_id=None):
    path=Path(root)/'objectives.db'
    base={'status':'UNAVAILABLE','count':None,'scope':'candidate parent objectives including this parent when submitted',
          'active_count':None,'active_count_status':'UNAVAILABLE','active_count_scope':'candidate parent objectives, not total historical task count'}
    if not path.is_file():return base
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            count=db.execute('SELECT COUNT(*) FROM objectives').fetchone()[0]
        base.update(status='OBSERVED',count=count)
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            rows=db.execute('SELECT id,state,steps_json FROM objectives').fetchall()
        queue_path=Path(os.getenv('PRIME_COMPUTE_QUEUE_DB',str(Path(root)/'compute-queue.db'))).resolve()
        jobs={}
        if queue_path.is_relative_to(Path(root).resolve()) and queue_path.is_file():
            with sqlite3.connect(queue_path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                jobs=dict(db.execute('SELECT id,status FROM compute_jobs').fetchall())
        active=0;unknown=0
        for task_id,state,encoded in rows:
            if state=='dispatching':
                # The currently executing parent is demonstrated active. An old
                # dispatching row can be an interruption, not necessarily live work.
                if task_id==current_task_id:active+=1
                else:unknown+=1
                continue
            steps=json.loads(encoded)
            if not isinstance(steps,list) or not steps:
                unknown+=1;continue
            states=[]
            for step in steps:
                dispatch=step.get('dispatch',{})
                if dispatch.get('state')=='COMPLETED':states.append('completed')
                elif 'job' in dispatch:states.append(jobs.get(dispatch['job'].get('id'),'unknown'))
                else:states.append(step.get('state','unknown'))
            if any(s in {'running','queued','awaiting_approval'} for s in states):active+=1
            elif any(s not in {'completed','failed','cancelled','budget_blocked','blocked'} for s in states):unknown+=1
        base.update(active_count=active if unknown==0 else None,
                    active_count_status='OBSERVED' if unknown==0 else 'PARTIALLY_OBSERVED',
                    known_active_count=active,unresolved_objective_count=unknown,
                    observation_consistency='Sequential read-only database snapshots; concurrent state changes remain possible')
        return base
    except Exception:return base


def build_report(task_id,root):
    from .agent_registry import load_agent_registry,REGISTRY_PATH
    try:
        registry=load_agent_registry()
        canonical={'status':'OBSERVED','agent_count':len(registry['agents']),
                   'registry_version':registry.get('registry_version','UNKNOWN'),
                   'source_sha256':hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()}
    except Exception:canonical={'status':'UNAVAILABLE','agent_count':None,'registry_version':'UNKNOWN','source_sha256':None}
    result={'schema_version':SCHEMA,'task_id':task_id,'captured_at':datetime.now(timezone.utc).isoformat(),
            'prime_health':production_health(),'registry':canonical,'tasks':objective_count(root,task_id),
            'protocol':{'interface_contract':'jarvis.interface.v1','report_schema':SCHEMA,
                        'source':'app/interface_contract.py /interface/v1 identity contract',
                        'broader_governance_protocol_version':'UNKNOWN'},
            'qualified_compute':qualified_profile(),'execution':{'model_calls':0,'input_tokens':0,'output_tokens':0,
            'method':'DETERMINISTIC_READ_ONLY','fresh_inference_performed':False}}
    validate_report(result)
    return result


def validate_report(value):
    keys={'schema_version','task_id','captured_at','prime_health','registry','tasks','qualified_compute','execution','protocol'}
    if not isinstance(value,dict) or set(value)!=keys or value['schema_version']!=SCHEMA:
        raise ValueError('Invalid runtime report schema')
    if not isinstance(value['task_id'],str) or not value['task_id']:raise ValueError('Missing parent task')
    datetime.fromisoformat(value['captured_at'])
    if any(not isinstance(value[k],dict) for k in keys-{'schema_version','task_id','captured_at'}):raise ValueError('Invalid report section')
    if value['execution'].get('model_calls')!=0:raise ValueError('Not deterministic')
    if value['tasks'].get('count') is not None and (type(value['tasks']['count']) is not int or value['tasks']['count']<0):raise ValueError('Invalid task count')
    if value['tasks'].get('active_count') is not None and (type(value['tasks']['active_count']) is not int or value['tasks']['active_count']<0):raise ValueError('Invalid active task count')
    json.dumps(value,allow_nan=False)
