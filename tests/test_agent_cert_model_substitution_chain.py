"""Genuine temporary owning records with simulated HTTP; never qualification."""
import json,uuid
from types import SimpleNamespace
import httpx,pytest
from app import agent_cert_model_substitution_events as events
from app.agent_cert_resident_model import canonical
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_operator_io import TOKEN

@pytest.fixture
def source_runtime(runtime,monkeypatch):
    from app import agent_dispatch_api,compute_queue_api
    from app.job_queue import JobQueue,QueuePolicy
    from app.objective_api import runtime_snapshot
    root=runtime.root;domain=str(uuid.uuid4())
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID','SOURCE_DOMAIN_'+domain)
    identity=runtime_snapshot()
    (root/'source-qualification-domain.json').write_bytes(canonical(dict(schema='prime.source-qualification-domain.v1',
        domain_id=domain,source_revision=identity['source_revision'],scope='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME')))
    endpoint='http://127.0.0.1:11435';monkeypatch.setenv('OLLAMA_BASE_URL',endpoint)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE','golden_n1')
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT','PRIME_MEASURED_COMPUTE_PROFILE','PRIME_MEASURED_COMPUTE_PROFILE_SHA256','PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name,raising=False)
    queue=JobQueue(root/'compute-queue.db',QueuePolicy());monkeypatch.setattr(compute_queue_api,'queue',queue)
    from app.settings import PrimeSettings
    monkeypatch.setattr(agent_dispatch_api,'SETTINGS',PrimeSettings(ollama_base_url=endpoint,
        fast_model='gemma3:1b',deep_model='gemma3:4b',embedding_model='embedding-unused',multi_specialist_workers=1,
        keep_alive='10m',context_tokens=2048,max_output_tokens=256))
    calls=[];original=httpx.AsyncClient
    def handler(request):
        from datetime import datetime,timezone,timedelta
        calls.append((request.method,request.url.path,request.content))
        if request.method=='GET':
            return httpx.Response(200,content=canonical(dict(models=[dict(name='gemma3:4b',model='gemma3:4b',
                digest=events.DEEP_DIGEST,expires_at=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat())])))
        return httpx.Response(200,content=canonical(dict(model='gemma3:4b',message={'content':'DEGRADED'},done=True,
            load_duration=0,prompt_eval_count=8,eval_count=3,eval_duration=100))+b'\n')
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    runtime.model_calls=calls;runtime.native_queue=queue;return runtime

def subject(source_runtime):
    body=events.canonical_request('subject')
    reply=source_runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    (source_runtime.root/'subject-response.raw.json').write_bytes(reply.content)
    (source_runtime.root/'subject-request.canonical.json').write_bytes(canonical(body))
    assert reply.status_code==202,reply.text
    view=reply.json();assert 'dispatch' in view['steps'][0],view
    dispatch=view['steps'][0]['dispatch']
    assert dispatch['state']=='COMPLETED',view
    return events.capture_original_execution(dispatch['task_id'],body)

def test_actual_owning_native_records_and_distinct_original_peer_mock_unready(source_runtime):
    execution=subject(source_runtime)
    (source_runtime.root/'execution.canonical.json').write_bytes(canonical(execution))
    body=events.canonical_request('review',execution)
    reply=source_runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    (source_runtime.root/'peer-response.raw.json').write_bytes(reply.content)
    (source_runtime.root/'peer-request.canonical.json').write_bytes(canonical(body))
    assert reply.status_code==202,reply.text
    view=reply.json();assert 'dispatch' in view['steps'][0],view
    peer=view['steps'][0]['dispatch'];assert peer['state']=='COMPLETED',view
    assert peer['task_id']!=execution['task_id'] and peer['agent_id']=='a26'
    assert peer['review_action_durable'] is True and peer['certification']=='UNVERIFIED'
    assert execution['native_result']['state']=='SOURCE_UNREADY'
    assert len([method for method,_,_ in source_runtime.model_calls if method=='POST'])==1

@pytest.mark.parametrize('authorization',[None,'Bearer wrong-source-token'])
def test_actual_owning_auth_denial_before_native_or_case_writes(source_runtime,authorization):
    headers={} if authorization is None else {'Authorization':authorization}
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('subject'),headers=headers)
    assert response.status_code==401 and not source_runtime.model_calls
    assert not (source_runtime.root/'source-model-substitution-producer.claim').exists()

def test_actual_source_domain_replay_stops_before_second_native_request(source_runtime):
    execution=subject(source_runtime);before=len(source_runtime.model_calls)
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('subject'),
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert len(source_runtime.model_calls)==before and len(source_runtime.native_queue.list())==2

@pytest.mark.parametrize('execution',[None,[],{},'not-an-original'])
def test_malformed_original_review_denied_without_peer_artifact(source_runtime,execution):
    body=events.canonical_request('subject');body.update(capability='responsibility.a26',
        objective=events.REVIEW_OBJECTIVE,deterministic_operation='certification_model_substitution_review')
    context=json.loads(body['context']);context.update(stage='review',execution=execution);body['context']=canonical(context).decode()
    response=source_runtime.client.post('/api/agents/objectives',json=body,headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert not source_runtime.model_calls and not list((source_runtime.root/'artifacts').glob('*/metadata.json'))

def test_actual_producer_corrupted_original_health_claim_rejected_by_persisted_peer(source_runtime,monkeypatch):
    original=events.canonical
    def faulty(value):
        if type(value) is dict and value.get('schema_version')==events.RESULT_SCHEMA:
            value={**value,'actual_service_health':'HEALTHY'}
        return original(value)
    monkeypatch.setattr(events,'canonical',faulty)
    execution=subject(source_runtime)
    assert json.loads(execution['producer_content_utf8'])['actual_service_health']=='HEALTHY'
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('review',execution),
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert len([method for method,_,_ in source_runtime.model_calls if method=='POST'])==1

def test_real_slow_first_action_fsync_uses_original_shared_budget(source_runtime,monkeypatch):
    import os,time,threading
    original=os.fsync;delayed=[]
    def slow(fd):
        if not delayed and threading.current_thread().name=='action-observability':
            delayed.append(fd);time.sleep(1.2)
        return original(fd)
    monkeypatch.setattr(os,'fsync',slow)
    execution=subject(source_runtime)
    assert delayed and execution['native_result']['contract']['generation']['effective_public_settings']['context_tokens']==512

def test_real_exhausted_first_durability_budget_never_starts_native_request(source_runtime,monkeypatch):
    import os,time,threading
    original=os.fsync;delayed=[]
    def slow(fd):
        if not delayed and threading.current_thread().name=='action-observability':
            delayed.append(fd);time.sleep(5.05)
        return original(fd)
    monkeypatch.setattr(os,'fsync',slow)
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('subject'),
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert delayed and not source_runtime.model_calls and not source_runtime.native_queue.list()

def test_real_failed_writer_stops_before_native_and_retains_failure(source_runtime,monkeypatch):
    import os,threading
    original=os.fsync;failed=[]
    def broken(fd):
        if not failed and threading.current_thread().name=='action-observability':
            failed.append(fd);raise OSError('Disposable original model-case writer failure')
        return original(fd)
    monkeypatch.setattr(os,'fsync',broken)
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('subject'),
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert failed and source_runtime.ledger.dropped>0 and not source_runtime.model_calls
    assert source_runtime.ledger.close() is False and not source_runtime.ledger.worker.is_alive()
    # Acknowledge this already-closed unhealthy disposable writer only for the
    # shared fixture's teardown; the original failure/status above stays intact.
    monkeypatch.setattr(source_runtime.ledger,'close',lambda:True)

def test_private_settings_narrowing_does_not_mutate_public_defaults(source_runtime):
    from app import agent_dispatch_api
    from dataclasses import asdict
    original=agent_dispatch_api.SETTINGS;before=asdict(original)
    effective=events.qualification_settings(original)
    assert asdict(original)==before and original.context_tokens==2048 and original.max_output_tokens==256
    assert effective.context_tokens==512 and effective.max_output_tokens==16
    assert {k:v for k,v in asdict(effective).items() if k not in ('context_tokens','max_output_tokens')}=={
        k:v for k,v in before.items() if k not in ('context_tokens','max_output_tokens')}

@pytest.mark.parametrize('drift',['context','output','options','model','prompt'])
def test_actual_outgoing_payload_drift_stops_before_post(source_runtime,monkeypatch,drift):
    from app.agent_cert_resident_model import ResidentAdmissionContract
    original=ResidentAdmissionContract.bind_chat_request
    def changed(self,payload):
        if drift=='context':payload['options']['num_ctx']=2048
        elif drift=='output':payload['options']['num_predict']=256
        elif drift=='options':payload['options']['temperature']=1
        elif drift=='model':payload['model']='gemma3:1b'
        else:payload['messages'][0]['content']+=' altered'
        return original(self,payload)
    monkeypatch.setattr(ResidentAdmissionContract,'bind_chat_request',changed)
    response=source_runtime.client.post('/api/agents/objectives',json=events.canonical_request('subject'),
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202 and response.json()['steps'][0]['state']=='blocked'
    assert source_runtime.model_calls == [('GET','/api/ps',b''),('GET','/api/ps',b'')]
    assert not any(method=='POST' for method,_,_ in source_runtime.model_calls)
