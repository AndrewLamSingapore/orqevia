"""Driver custody, retry bounds and unchanged-oracle tests; not live acceptance."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from app import normal_role_followups as follow
from app.agent_coaching import digest, effective_prompt


def sample(agent='a01',passed=False):
    return follow.plan_for_agent(agent,0,'original-job',['field_contract_mismatch'],passed)


def state(agent):
    return {'version':follow.VERSION,'wave':follow.WAVE,'runtime_revision':'a'*40,
            'agents':[agent],'jobs_submitted':0,'maximum_jobs':27,'last_activity_at':None}


class Queue:
    def __init__(self):self.jobs={};self.calls=[]
    def list(self,status,limit=100):return [j for j in self.jobs.values() if j['status']==status]
    def get(self,key):return self.jobs[key]
    def submit(self,**body):
        self.calls.append(body)
        job={'id':'job-'+str(len(self.calls)),'status':'queued',**body}
        self.jobs[job['id']]=job
        return job


def test_coaching_preserves_original_request_and_supplies_types_only():
    from app.agent_registry import registered_agent_ids
    for index,agent in enumerate(registered_agent_ids(include_orchestrator=False)):
        plan=follow.plan_for_agent(agent,index,'retained',[],False)
        request,original=effective_prompt(agent,'baseline',1001)
        assert plan['normal_request_sha256']==digest(request)
        assert plan['reassessment_prompt'].startswith(original)
        contract=follow.normal_role_response_contract(agent)
        assert not any(key in json.dumps(contract['schema']) for key in ['"const"','"default"','"enum"'])
        assert plan['full_role_acceptance_status']=='NOT_ESTABLISHED'


def test_atomic_state_roundtrip_and_exclusive_lock(tmp_path):
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(sample()))
        assert json.loads((tmp_path/'state.json').read_text())==state(sample())
        assert not (tmp_path/'state.next.json').exists()
        with follow.ownership() as first:
            with follow.ownership() as second:assert first and not second
        with follow.ownership() as recovered:assert recovered


def test_contending_driver_cannot_read_state_or_submit_jobs(tmp_path):
    queue=Queue()
    with patch.object(follow,'ROOT',tmp_path):
        # Missing state is intentional: contention must return before reading it.
        with follow.ownership() as acquired:
            assert acquired
            assert follow.prepare(queue)=={'state':'COACH_ALREADY_RUNNING'}
            assert follow.tick(queue)=={'state':'COACH_ALREADY_RUNNING'}
            assert follow.recover_context_budget_failures(queue,catalog_sha256='c'*64)=={'state':'COACH_ALREADY_RUNNING'}
            assert follow.coach_identifier_casing(queue)=={'state':'COACH_ALREADY_RUNNING'}
        assert not queue.calls and not queue.jobs
        assert not (tmp_path/'state.json').exists()


def test_changed_executor_blocks_submission(tmp_path,monkeypatch):
    queue=Queue();monkeypatch.setenv('PRIME_COACHING_EXECUTOR_REVISION','b'*40)
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(sample()))
        assert follow.tick(queue)['state']=='RUNTIME_SOURCE_CHANGED_RECONCILIATION_REQUIRED'
        assert not queue.calls


def test_restart_readback_never_resubmits_waiting_job(tmp_path,monkeypatch):
    queue=Queue();monkeypatch.setenv('PRIME_COACHING_EXECUTOR_REVISION','a'*40)
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(sample()))
        follow.tick(queue);follow.tick(queue)
        assert len(queue.calls)==1
        assert queue.calls[0]['max_retries']==0
        assert queue.calls[0]['max_cost_usd']==follow.CAP
        assert 'idempotency_key' in queue.calls[0]


def test_original_binding_rejects_prompt_or_actor_or_provider_change():
    request,prompt=effective_prompt('a01','baseline',1001)
    expected={'agent':'a01','model':follow.MODEL,'requested_provider':follow.PROVIDER,
              'request_sha256':digest(request),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
    job={'agent':'a01','prompt':prompt,'model':follow.MODEL,'preferred_provider':follow.PROVIDER,
         'provider':follow.PROVIDER,'allow_cloud':1,'external_execution':0,
         'data_classification':'CLOUD_PERMITTED','max_cost_usd':follow.CAP}
    assert follow.baseline_bound(job,expected)
    for key,value in [('prompt','tampered'),('agent','a02'),('provider','other')]:
        changed={**job,key:value};assert not follow.baseline_bound(changed,expected)


def test_failed_reassessment_retains_output_and_stops_without_retry(tmp_path,monkeypatch):
    queue=Queue();monkeypatch.setenv('PRIME_COACHING_EXECUTOR_REVISION','a'*40)
    agent=sample(passed=True)
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(agent));follow.tick(queue)
        job=next(iter(queue.jobs.values()))
        job.update(status='completed',provider=follow.PROVIDER,result='{}',started_at='start',completed_at='finish',
                   input_tokens=1,output_tokens=1,actual_cost_usd=.000001,error=None)
        outcome=follow.tick(queue);follow.tick(queue)
        saved=json.loads((tmp_path/'state.json').read_text())
        assert outcome['reassessed']==1 and outcome['normal_failed']==1
        assert outcome['full_role_accepted_count']==0
        assert saved['agents'][0]['assessments'][0]['original_output']=='{}'
        assert len(queue.calls)==1


def test_context_recovery_is_explicit_once_and_preserves_failure(tmp_path):
    queue=Queue();agent=sample(passed=True)
    attempt={'phase':'REASSESSMENT','job_id':'failed','outcome':'FAIL',
             'execution_error':'CONTEXT_BUDGET_EXCEEDED','actual_cost_usd':None}
    agent.update(state='DONE',phase='REASSESSMENT',assessments=[attempt])
    queue.jobs['failed']={'status':'failed','error':'CONTEXT_BUDGET_EXCEEDED','result':'','id':'failed'}
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(agent))
        assert follow.recover_context_budget_failures(queue,catalog_sha256='c'*64)['agents']==['a01']
        assert follow.recover_context_budget_failures(queue,catalog_sha256='c'*64)['agents']==[]
        saved=json.loads((tmp_path/'state.json').read_text())
        assert saved['agents'][0]['assessments']==[attempt]
        assert saved['maximum_jobs']==28 and saved['agents'][0]['submission_attempt']==2


def test_summary_counts_latest_per_agent_and_keeps_attempt_denominator():
    agent=sample();agent['assessments']=[{'phase':'REASSESSMENT','outcome':'FAIL','actual_cost_usd':None},
                                      {'phase':'REASSESSMENT','outcome':'PASS','actual_cost_usd':.001}]
    result=follow.summary(state(agent))
    assert result['reassessed']==1 and result['normal_passed']==1
    assert result['retained_reassessment_attempts']==2 and result['normal_denominator']==21


def test_identifier_coaching_requires_retained_failure_and_runs_once(tmp_path):
    queue=Queue();agent=sample()
    attempt={'phase':'REASSESSMENT','job_id':'prior','status':'completed','execution_bound':True,
             'original_output':'retained','errors':['chosen_project_under_three_day_limit','higher_efficiency_project','higher_total_project']}
    agent.update(state='DONE',phase='REASSESSMENT',assessments=[attempt])
    queue.jobs['prior']={'result':'retained'}
    with patch.object(follow,'ROOT',tmp_path):
        follow.write_state(state(agent));result=follow.coach_identifier_casing(queue)
        assert result['maximum_jobs']==28
        assert follow.coach_identifier_casing(queue)['state']=='ALREADY_APPLIED'
        saved=json.loads((tmp_path/'state.json').read_text())['agents'][0]
        assert saved['assessments']==[attempt] and saved['submission_attempt']==3
        assert saved['normal_request_sha256']==agent['normal_request_sha256']
        assert 'Alpha' not in saved['identifier_coaching_applied']['instruction']
        assert 'Beta' not in saved['identifier_coaching_applied']['instruction']
