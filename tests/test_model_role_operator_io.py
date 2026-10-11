"""Offline framing/clock protocol tests; no sockets, providers or certification."""
from copy import deepcopy
import pytest
from scripts import agent_cert_operator_io as b
from app.agent_cert_role_review import canonical_case_spec
from tests.test_agent_cert_operator_io import FakeTransport,FakeResponse,FakeTimer,TOKEN,SOURCE,IMAGE,raw,TASK,REVIEW,ACTION,client as event

class Clock:
 def __init__(self):self.now=0
 def __call__(self):return self.now

def role(transport=None,clock=None,**kwargs):
 return b.ModelRoleOperatorIO(owner_token=TOKEN,spec=canonical_case_spec('a19','responsibility.a19','role:normal'),
  expected_source_revision=SOURCE,expected_runtime_image=IMAGE,connection_factory=transport or FakeTransport(),
  timer_factory=FakeTimer,monotonic=clock or Clock(),**kwargs)

def test_model_role_observation_at35_seconds_uses_same_fixed_deadline():
 clock=Clock();x=role(clock=clock);x.authorize();deadline=x._deadline;clock.now=35;x.runtime()
 assert x._deadline==deadline==60 and x._total_seconds==60
 clock.now=61
 with pytest.raises(ValueError,match='DEADLINE'):x.runtime()
 assert len(x.original_replies())==2

def test_zero_model_event31_rejected_and_model_role61_configuration_rejected():
 clock=Clock();x=event(monotonic=clock,total_timeout_seconds=30);x.authorize();clock.now=31
 with pytest.raises(ValueError,match='DEADLINE'):x.runtime()
 with pytest.raises(ValueError):role(total_timeout_seconds=61)
 with pytest.raises(ValueError):event(total_timeout_seconds=60)

@pytest.mark.parametrize('field,value',[('case','baseline:initialization'),('request',{}),('agent_id','a05')])
def test_foreign_or_mutated_canonical_role_cannot_construct(field,value):
 spec=canonical_case_spec('a19','responsibility.a19','role:normal');spec[field]=value
 with pytest.raises(ValueError):b.ModelRoleOperatorIO(owner_token=TOKEN,spec=spec,expected_source_revision=SOURCE,expected_runtime_image=IMAGE)

def test_stalled_clock_still_has_finite80_replies_and_request_timer2():
 FakeTimer.all=[];x=role();x.authorize()
 for _ in range(79):x.runtime()
 assert len(x.original_replies())==80 and all(0<t.seconds<=2 for t in FakeTimer.all)
 with pytest.raises(ValueError,match='CUSTODY'):x.runtime()

def test_eight_mib_custody_cannot_be_reset_or_overrun():
 x=role();x.authorize();x._response_bytes=8*1024*1024
 with pytest.raises(ValueError,match='CUSTODY'):x.runtime()
 assert x._custody_cap==8*1024*1024

def test_post_uncertainty_retains_original_and_never_retries():
 tr=FakeTransport(lambda method,path,body:FakeResponse(status=500,body=b'{"error":"PUBLIC_FAILURE"}') if method=='POST' else FakeResponse())
 x=role(tr);x.authorize();body=deepcopy(x._spec['request'])
 assert x.submit_objective(body)==(500,{"error":"PUBLIC_FAILURE"})
 with pytest.raises(ValueError):x.submit_objective(body)
 assert len([v for v in tr.calls if v[0]=='POST'])==1
 assert [r.raw for r in x.original_replies() if r.method=='POST']==[b'{"error":"PUBLIC_FAILURE"}']

def test_fixed_job_and_review_callback_cannot_borrow_foreign_task():
 x=role(review_action_reader=lambda task,action:['{}\n','{}\n']);x.authorize();x._job=TASK
 with pytest.raises(ValueError):x.io().read_job(REVIEW)
 x._review_task=REVIEW;x._review_action=ACTION
 assert x.read_review_actions(ACTION)==['{}\n','{}\n']
 with pytest.raises(ValueError):x.read_review_actions(TASK)
 with pytest.raises(ValueError):x.activate_execution_input('fresh_challenge:complete',{})

def test_rollback_clock_rejected_without_deadline_renewal():
 clock=Clock();x=role(clock=clock);x.authorize();clock.now=35;x.runtime();clock.now=34
 with pytest.raises(ValueError,match='CLOCK'):x.runtime()
 assert x._deadline==60

def test_actual_collector_fake_http_role_completes_after35_without_event_budget_reset():
 import json
 from tests.test_collect_agent_cert_case import SyntheticOperator,SOURCE as src,IMAGE as img,CODE,NOW,NONCE,JOB
 from scripts.collect_agent_cert_case import collect_role_case
 state=SyntheticOperator(agent='a18');clock=Clock();reads=[]
 def handler(method,path,body):
  if path==b.RUNTIME_PATH:return FakeResponse(body=raw(state.runtime()))
  if method=='POST' and path=='/api/agents/objectives':
   status,value=state.submit(json.loads(body));return FakeResponse(status=status,body=raw(value))
  if path=='/api/compute-queue/jobs/'+JOB:
   status,value=state.read_job(JOB)
   if clock.now<35:value.update(status='running',result=None,completed_at=None)
   return FakeResponse(status=status,body=raw(value))
  if path.startswith('/api/agents/objectives/'):
   status,value=state.read_objective(path.rsplit('/',1)[-1]);return FakeResponse(status=status,body=raw(value))
  if method=='POST' and path=='/api/agents/dispatch':
   status,value=state.dispatch_review(json.loads(body));return FakeResponse(status=status,body=raw(value))
  if path.startswith('/api/artifacts/'):
   status,value,digest=state.artifact(path.rsplit('/',1)[-1]);return FakeResponse(status=status,body=value,headers={"X-Artifact-SHA256":digest})
  raise AssertionError(path)
 def actions(task,action):
  reads.append((task,action));return [line+'\n' for line in state.actions(action)]
 transport=FakeTransport(handler)
 client=b.ModelRoleOperatorIO(owner_token=TOKEN,spec=state.spec,expected_source_revision=src,
  expected_runtime_image=img,connection_factory=transport,timer_factory=FakeTimer,monotonic=clock,
  review_action_reader=actions)
 result=collect_role_case(state.spec,io=client.io(),expected_source_revision=src,expected_runtime_image=img,
  reviewer_code_revision=CODE,review_run_id='offline-model-role35',timeout_seconds=60,poll_seconds=1,
  monotonic=clock,pause=lambda d:setattr(clock,'now',clock.now+d),wall_clock=lambda:NOW,nonce_factory=lambda:NONCE)
 assert result.summary['state']=='UNSIGNED_CASE_EVIDENCE',json.dumps(result.summary)
 assert clock.now==35 and client._deadline==60
 assert state.calls.count('submit')==state.calls.count('review')==1
 assert reads==[(client._review_task,client._review_action)]
 assert len(client.original_replies())<=80

