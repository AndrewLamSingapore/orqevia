"""Disposable native queue/ledger with mocked inference; no backend qualification."""
import json,sqlite3,pytest
from tests import test_harness_api
from app import compute_queue_api as api,direct_stream,action_records,objective_api,compute_catalog
from app.job_queue import JobQueue,QueuePolicy,Provider
from app.outcome_metrics import OutcomeMetrics

@pytest.fixture
def domain(tmp_path,monkeypatch):
 monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path));monkeypatch.setattr(api,'DATA',tmp_path)
 q=JobQueue(tmp_path/'queue.db',QueuePolicy());monkeypatch.setattr(api,'queue',q)
 ledger=action_records.ActionLedger(tmp_path/'actions.jsonl');monkeypatch.setattr(action_records,'action_ledger',lambda:ledger)
 monkeypatch.setattr(compute_catalog,'load_catalog',lambda:[])
 from app.agent_dispatch_api import local_model_backends
 backend=local_model_backends(api.SETTINGS)[-1]
 provider=Provider(backend.name,'local',backend.model,32768,0,1)
 job=q.submit(agent='a05',prompt='PUBLIC_FIXTURE',model_role='deep',model=provider.model,allow_cloud=False,max_cost_usd=0,max_retries=0)
 job=dict(job,provider=provider.name,status='running',task_class='planning')
 yield tmp_path,q,job,provider
 assert ledger.close()

def install(monkeypatch,value):
 calls=[]
 async def infer(*args,**kwargs):
  calls.append(1)
  if isinstance(value,Exception):raise value
  return value
 monkeypatch.setattr(direct_stream,'infer',infer);return calls

def rows(root):
 with sqlite3.connect(root/'compute-ledger.db') as d:return d.execute('select task_id,tier,tokens,cost,verified,details from reasoning_attempts').fetchall()

@pytest.mark.parametrize('error',[None,'STRICT_JSON_CONTRACT_FAILED'])
def test_actual_usage_accounted_before_return_and_review_cannot_change_projection(domain,monkeypatch,error):
 root,q,job,p=domain;answer=dict(result='ORIGINAL',input_tokens=11,output_tokens=7,actual_cost_usd=0)
 if error:answer.update(error=error,retryable=False)
 calls=install(monkeypatch,answer);assert api._execute(job,p) is answer and calls==[1]
 row=rows(root)[0];detail=json.loads(row[5]);assert row[:5]==(job['id'],('MINI' if p.name=='ollama-deep' else 'NANO'),18,0.0,0)
 assert detail['success'] is (error is None) and detail['retries']==0 and detail['requested_provider']==p.name
 before=objective_api.inference_attempt_projection([job]);assert before['status']=='OBSERVED'
 OutcomeMetrics(root/'compute-ledger.db').record(attempt_id='a'*32,task_id='distinct-zero-model-review',task_class='classification',tier='NANO',seconds=.01,cost=0)
 assert objective_api.inference_attempt_projection([job])==before

def test_exception_accounted_without_retry_or_private_error_text(domain,monkeypatch):
 root,q,job,p=domain;calls=install(monkeypatch,RuntimeError('PRIVATE_PROMPT'))
 with pytest.raises(RuntimeError,match='PRIVATE_PROMPT'):api._execute(job,p)
 assert calls==[1];row=rows(root)[0];detail=json.loads(row[5]);assert row[2] is None and row[3] is None and detail['failure_kind']=='LOCAL_INFERENCE_FAILED'
 assert 'PRIVATE_PROMPT' not in row[5] and objective_api.inference_attempt_projection([job])['status']=='OBSERVED'

def test_accounting_failure_does_not_drop_original_result_or_retry(domain,monkeypatch,caplog):
 root,q,job,p=domain;answer=dict(result='ORIGINAL',input_tokens=1,output_tokens=2,actual_cost_usd=0);calls=install(monkeypatch,answer)
 def broken(*args,**kwargs):raise RuntimeError('PRIVATE_LEDGER_ERROR')
 monkeypatch.setattr(OutcomeMetrics,'record',broken)
 assert api._execute(job,p) is answer and calls==[1]
 assert 'Local inference attempt evidence unavailable' in caplog.text and 'PRIVATE_LEDGER_ERROR' not in caplog.text

def test_unconfigured_provider_is_not_promoted_to_known_tier(domain,monkeypatch):
 root,q,job,p=domain;p=Provider('unconfigured','local','unknown:4b',32768,0,1)
 answer=dict(result='ORIGINAL',input_tokens=1,output_tokens=2,actual_cost_usd=0);calls=install(monkeypatch,answer)
 assert api._execute(job,p) is answer and calls==[1] and not (root/'compute-ledger.db').exists()

@pytest.mark.parametrize('value',[RuntimeError('ORIGINAL_MODEL_ERROR'),dict(result='ORIGINAL',input_tokens=-1,output_tokens=2,actual_cost_usd=0)])
def test_unavailable_or_invalid_accounting_preserves_original_outcome(domain,monkeypatch,caplog,value):
 root,q,job,p=domain;calls=install(monkeypatch,value)
 if isinstance(value,Exception):
  def broken(*args,**kwargs):raise RuntimeError('PRIVATE_LEDGER_ERROR')
  monkeypatch.setattr(OutcomeMetrics,'record',broken)
  with pytest.raises(RuntimeError,match='ORIGINAL_MODEL_ERROR'):api._execute(job,p)
 else:assert api._execute(job,p) is value
 assert calls==[1] and rows(root)==[]
 assert 'Local inference attempt evidence unavailable' in caplog.text and 'PRIVATE_LEDGER_ERROR' not in caplog.text
