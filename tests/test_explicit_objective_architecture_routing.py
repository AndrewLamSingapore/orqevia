"""Actual disposable Objective route and queued job; no workers/inference."""
import json,pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests import test_harness_api  # Existing disposable source environment before imports.
from app import objective_api,agent_dispatch_api,compute_queue_api
from app.job_queue import JobQueue,QueuePolicy
from app.agent_cert_role_review import canonical_case_spec
from app.tier_router import Backend,Tier

@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path));monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'));monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED','1')
 queue=JobQueue(tmp_path/'queue.db',QueuePolicy(global_concurrency=1));monkeypatch.setattr(compute_queue_api,'queue',queue)
 monkeypatch.setattr(agent_dispatch_api,'local_model_backends',lambda:(Backend('ollama-deep','existing:4b',Tier.MINI,'local'),))
 app=FastAPI();app.include_router(objective_api.router)
 with TestClient(app) as c:yield c,queue

HEADERS={'Authorization':'Bearer test-owner-token'}
def test_exact_canonical_a29_enqueues_owned_role_instead_of_system_fact(client):
 c,q=client;spec=canonical_case_spec('a29','responsibility.a29','role:normal');assert 'runtime identity' in spec['request']['objective'].lower()
 result=c.post('/api/agents/objectives',json=spec['request'],headers=HEADERS);assert result.status_code==202,result.text
 step=result.json()['steps'][0];assert step['capability']=='responsibility.a29'
 job=q.get(step['dispatch']['job']['id']);assert job['agent']=='a29' and job['status']=='queued' and job['response_format']=='strict_json' and not job['allow_cloud']
 assert spec['request']['objective'] in job['prompt'] and spec['request']['context'] in job['prompt']
 assert len(q.list())==1 and 'system_fact' not in step['dispatch']

@pytest.mark.parametrize('body',[{'capability':'responsibility.a29'},{'capabilities':['responsibility.a29']}])
def test_explicit_forms_preserve_owning_route(client,body):
 c,q=client;r=c.post('/api/agents/objectives',json=dict(objective='What is your source identity?',task_class='planning',**body),headers=HEADERS);assert r.status_code==202,r.text
 assert r.json()['steps'][0]['capability']=='responsibility.a29' and len(q.list())==1

@pytest.mark.parametrize('body',[{'capability':'invented'},{'capabilities':['invented']}])
def test_explicit_invalid_capability_not_laundered_into_system_fact(client,body):
 c,q=client;r=c.post('/api/agents/objectives',json=dict(objective='What is your source identity?',**body),headers=HEADERS);assert r.status_code==202,r.text
 assert r.json()['steps'][0]['state']=='blocked' and q.list()==[]
 assert 'system_fact' not in json.dumps(r.json())

def test_auto_unscoped_remains_zero_model_system_fact(client):
 c,q=client;r=c.post('/api/agents/objectives',json={'objective':'What is your source identity?'},headers=HEADERS);assert r.status_code==202,r.text
 assert r.json()['steps'][0]['capability']=='system.architecture' and r.json()['steps'][0]['dispatch']['model_backend']=='none' and q.list()==[]

def test_unauthenticated_canonical_role_cannot_enqueue(client):
 c,q=client;r=c.post('/api/agents/objectives',json=canonical_case_spec('a29','responsibility.a29','role:normal')['request']);assert r.status_code==401 and q.list()==[]
