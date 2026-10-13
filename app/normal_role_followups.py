"""Owner-authorized answer-free coaching after the retained normal-role batch.

Uses the existing queue and unchanged semantic oracles. It never awards full
role acceptance or Azure L7. Operator composition owns its narrow HF allowlist.
"""
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import time

from .agent_coaching import canonical,digest,effective_prompt
from .agent_cert_response_contracts import normal_role_response_contract
from .agent_cert_role_review import review_role_output
from .coaching_exercises import METHODS,practice_request,review_practice

WAVE='hf-normal-21-20261013-v1'
VERSION='normal-role-answer-free-coaching.v1'
ROOT=Path(os.getenv('PRIME_DATA_DIR','/data'))/'normal-role-followups'/WAVE
MODEL='Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra'
PROVIDER='hf-qwen-normal-deepinfra'
CAP=0.005

def response_guidance(schema):
    return ('\nResponse shape (field names and primitive types only; no answers): '+canonical(schema)+
      '\nReturn only the JSON object, without Markdown fences. Copy field names exactly. '
      'Keep integers, booleans, strings and arrays distinct. Do not invent quotations, records, observations, '
      'executed actions or certification. Derive answers from the supplied facts and check every required field.')

def plan_for_agent(agent,index,baseline_job,baseline_errors,baseline_pass):
    seed=5001+index
    practice=practice_request(agent,seed)
    _,practice_prompt=effective_prompt(agent,'practice',seed,baseline_errors)
    practice_prompt+=response_guidance(practice['response_schema'])
    request,normal_prompt=effective_prompt(agent,'baseline',1001)
    contract=normal_role_response_contract(agent)
    normal_prompt+=('\nReusable coaching method: '+METHODS[agent]+
       '\nContract clarification: '+contract['clarification']+response_guidance(contract['schema']))
    return {'agent':agent,'seed':seed,'baseline_job_id':baseline_job,'baseline_pass':bool(baseline_pass),
      'baseline_errors':list(baseline_errors),'normal_request_sha256':digest(request),
      'practice_prompt':practice_prompt,'reassessment_prompt':normal_prompt,
      'phase':'WAIT_REASSESSMENT' if baseline_pass else 'PRACTICE','state':'READY','job_id':None,
      'assessments':[],'full_role_acceptance_status':'NOT_ESTABLISHED'}

def write_state(state):
    ROOT.mkdir(parents=True,exist_ok=True)
    temporary=ROOT/'state.next.json'
    with temporary.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps(state,indent=2));handle.flush();os.fsync(handle.fileno())
    assert json.loads(temporary.read_text())==state
    os.replace(temporary,ROOT/'state.json')

def baseline_bound(job,expected):
    request,prompt=effective_prompt(expected['agent'],'baseline',1001)
    return (job['agent']==expected['agent'] and job['prompt']==prompt and
      digest(request)==expected['request_sha256'] and hashlib.sha256(prompt.encode()).hexdigest()==expected['prompt_sha256'] and
      job['model']==expected['model']==MODEL and job['preferred_provider']==expected['requested_provider']==PROVIDER and
      job['provider']==PROVIDER and job['allow_cloud']==1 and job['external_execution']==0 and
      job['data_classification']=='CLOUD_PERMITTED' and job['max_cost_usd']<=CAP)

@contextmanager
def ownership():
    import fcntl
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'driver.lock').open('a+b') as handle:
        try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            yield False;return
        try:yield True
        finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def prepare(queue):
    with ownership() as acquired:
        if not acquired:return {'state':'COACH_ALREADY_RUNNING'}
        if (ROOT/'state.json').exists():
            state=json.loads((ROOT/'state.json').read_text())
        else:
            manifest=json.loads((ROOT.parents[1]/'coaching-normal-tests'/WAVE/'manifest.json').read_text())
            agents=[]
            for index,expected in enumerate(manifest['jobs']):
                job=queue.get(expected['job_id'])
                if job['status']!='completed' or not baseline_bound(job,expected):
                    raise ValueError('Original normal execution binding must be verified before coaching')
                passed,errors=review_role_output(job['agent'],'responsibility.'+job['agent'],job['result'])
                agents.append(plan_for_agent(job['agent'],index,job['id'],errors,passed))
            from .agent_registry import registered_agent_ids
            assert sorted(a['agent'] for a in agents)==sorted(registered_agent_ids(include_orchestrator=False))
            state={'version':VERSION,'wave':WAVE,'runtime_revision':manifest['runtime_revision'],
              'prepared_at':time.time(),'last_activity_at':None,'agents':agents,'jobs_submitted':0,
              'maximum_jobs':27,'maximum_cost_per_job_usd':CAP,'full_role_accepted_count':0,
              'scope':'TARGETED_PRACTICE_AND_NORMAL_REASSESSMENT_NOT_FULL_ROLE_ACCEPTANCE'}
            write_state(state)
        bindings=[]
        for agent in state['agents']:
            if not agent['baseline_pass']:bindings.append({'agent':agent['agent'],'prompt_sha256':hashlib.sha256(agent['practice_prompt'].encode()).hexdigest()})
            bindings.append({'agent':agent['agent'],'prompt_sha256':hashlib.sha256(agent['reassessment_prompt'].encode()).hexdigest()})
        return {'state':'PREPARED','wave':WAVE,'targeted_practice_agents':[a['agent'] for a in state['agents'] if not a['baseline_pass']],
                'allowed_prompt_bindings':bindings,'allowed_task_classes':['classification','planning'],'maximum_jobs':state['maximum_jobs']}

def tick(queue):
    with ownership() as acquired:
        if not acquired:return {'state':'COACH_ALREADY_RUNNING'}
        state=json.loads((ROOT/'state.json').read_text())
        if os.getenv('PRIME_COACHING_EXECUTOR_REVISION',os.getenv('PRIME_RUNTIME_REVISION'))!=state['runtime_revision']:
            return {'state':'RUNTIME_SOURCE_CHANGED_RECONCILIATION_REQUIRED'}
        for agent in state['agents']:
            if agent['state']!='WAITING':continue
            job=queue.get(agent['job_id'])
            if job['status'] not in ('completed','failed','cancelled','budget_blocked'):continue
            prompt=agent['practice_prompt'] if agent['phase']=='PRACTICE' else agent['reassessment_prompt']
            bound=(job['agent']==agent['agent'] and job['prompt']==prompt and job['model']==MODEL and
              job['preferred_provider']==PROVIDER and job['allow_cloud']==1 and job['external_execution']==0 and
              job['data_classification']=='CLOUD_PERMITTED' and job['max_cost_usd']<=CAP)
            if job['status']=='completed':bound=bound and job['provider']==PROVIDER
            passed=False;errors=['execution_not_completed']
            if job['status']=='completed' and bound:
                if agent['phase']=='PRACTICE':passed,errors=review_practice(agent['agent'],agent['seed'],job['result'])
                else:
                    request,_=effective_prompt(agent['agent'],'baseline',1001)
                    if digest(request)!=agent['normal_request_sha256']:bound=False;errors=['normal_request_changed']
                    else:passed,errors=review_role_output(agent['agent'],'responsibility.'+agent['agent'],job['result'])
            agent['assessments'].append({'phase':agent['phase'],'job_id':job['id'],'outcome':'PASS' if passed else 'FAIL',
              'errors':list(errors),'execution_bound':bound,'status':job['status'],'model':job['model'],'provider':job['provider'],
              'started_at':job['started_at'],'completed_at':job['completed_at'],'input_tokens':job['input_tokens'],
              'output_tokens':job['output_tokens'],'actual_cost_usd':job['actual_cost_usd'],'original_output':job['result'],
              'output_sha256':hashlib.sha256((job['result'] or '').encode()).hexdigest(),'execution_error':job['error']})
            agent.update(state='READY' if agent['phase']=='PRACTICE' and bound else ('DONE' if bound else 'BLOCKED'),
                         phase='WAIT_REASSESSMENT' if agent['phase']=='PRACTICE' and bound else agent['phase'],job_id=None)
            state['last_activity_at']=time.time();write_state(state)
        practice_open=any(a['phase']=='PRACTICE' and a['state'] not in ('DONE','BLOCKED') for a in state['agents'])
        active=sum(j['preferred_provider']==PROVIDER for j in queue.list('running',limit=100))
        queued=sum(j['preferred_provider']==PROVIDER for j in queue.list('queued',limit=100))
        for agent in state['agents']:
            if agent['state']!='READY' or active+queued>=2:continue
            if agent['phase']=='WAIT_REASSESSMENT':
                if practice_open:continue
                agent['phase']='REASSESSMENT'
            if state['jobs_submitted']>=state['maximum_jobs']:return {'state':'JOB_LIMIT'}
            prompt=agent['practice_prompt'] if agent['phase']=='PRACTICE' else agent['reassessment_prompt']
            body={'agent':agent['agent'],'prompt':prompt,'priority':'normal','model_role':'deep','model':MODEL,
              'preferred_provider':PROVIDER,'ram_mb':0,'vram_mb':0,'timeout_seconds':60,'max_retries':0,
              'max_cost_usd':CAP,'allow_cloud':True,'external_execution':False,'data_classification':'CLOUD_PERMITTED',
              'task_class':'classification' if agent['phase']=='PRACTICE' else 'planning','response_format':'strict_json',
              'idempotency_key':'normal-followup-20261013:'+agent['agent']+':'+agent['phase'].lower()+':v'+str(agent.get('submission_attempt',1))}
            # Same guarded durable submission path as the existing controller.
            # The network-isolated sidecar submits; only the primary executes.
            job=queue.submit(**body)
            agent.update(state='WAITING',job_id=job['id']);state['jobs_submitted']+=1
            state['last_activity_at']=time.time();write_state(state);queued+=1
        return summary(state)

def recover_context_budget_failures(queue,*,catalog_sha256):
    """Explicit one-time repair after confirmed pre-HTTP context rejection.

    Never replay ambiguous network failures or hide the original assessment.
    Caller must install and record the corrected scoped catalog first.
    """
    if len(catalog_sha256)!=64 or any(c not in '0123456789abcdef' for c in catalog_sha256):
        raise ValueError('corrected catalog hash required')
    with ownership() as acquired:
        if not acquired:return {'state':'COACH_ALREADY_RUNNING'}
        state=json.loads((ROOT/'state.json').read_text());recovered=[]
        for agent in state['agents']:
            if agent['state']!='DONE' or agent.get('submission_attempt',1)!=1 or not agent['assessments']:continue
            attempt=agent['assessments'][-1]
            if attempt['phase']!='REASSESSMENT' or attempt['execution_error']!='CONTEXT_BUDGET_EXCEEDED':continue
            job=queue.get(attempt['job_id'])
            if job['status']!='failed' or job['error']!='CONTEXT_BUDGET_EXCEEDED' or job['result'] or job.get('inference_receipt'):
                raise ValueError('pre-execution rejection evidence required')
            agent.update(state='READY',job_id=None,submission_attempt=2)
            agent['infrastructure_recovery']={'reason':'CONTEXT_BUDGET_EXCEEDED_BEFORE_HTTP',
                'original_job_id':job['id'],'corrected_catalog_sha256':catalog_sha256,'at':time.time()}
            recovered.append(agent['agent'])
        state['maximum_jobs']+=len(recovered)
        state['last_activity_at']=time.time();write_state(state)
        return {'state':'RECOVERED','agents':recovered,'maximum_jobs':state['maximum_jobs']}

def summary(state):
    practice=[x for a in state['agents'] for x in a['assessments'] if x['phase']=='PRACTICE']
    reassessed=[next((x for x in reversed(a['assessments']) if x['phase']=='REASSESSMENT'),None) for a in state['agents']]
    reassessed=[x for x in reassessed if x is not None]
    return {'state':'DONE' if all(a['state']=='DONE' for a in state['agents']) else ('BLOCKED' if all(a['state'] in ('DONE','BLOCKED') for a in state['agents']) else 'IN_PROGRESS'),'wave':state['wave'],
      'practice_assessed':len(practice),'practice_passed':sum(x['outcome']=='PASS' for x in practice),
      'reassessed':len(reassessed),'normal_passed':sum(x['outcome']=='PASS' for x in reassessed),
      'normal_failed':sum(x['outcome']=='FAIL' for x in reassessed),'jobs_submitted':state['jobs_submitted'],
      'normal_denominator':21,'unknown_cost_count':sum(x['actual_cost_usd'] is None for a in state['agents'] for x in a['assessments']),
      'retained_reassessment_attempts':sum(x['phase']=='REASSESSMENT' for a in state['agents'] for x in a['assessments']),
      'known_cost_usd':sum(x['actual_cost_usd'] for a in state['agents'] for x in a['assessments'] if x['actual_cost_usd'] is not None),
      'full_role_accepted_count':0}
