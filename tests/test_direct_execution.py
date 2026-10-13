"""Superseding-model acceptance; effects occur only in isolated test storage."""
import asyncio
import hashlib
import json
import threading
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.action_records import ActionRecord,ActionLedger,DirectExecutor,action_ledger,close_ledgers
from app.connector_sdk import ConnectorRegistry,Sink


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    close_ledgers()
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED','1')
    monkeypatch.setenv('PRIME_SPINE_TOKEN','isolated-test-owner')
    monkeypatch.setenv('OLLAMA_BASE_URL','http://fixture')
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE','golden_n1')
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    yield
    close_ledgers()


def no_gate(*args,**kwargs):raise AssertionError('Legacy authority gate called')


@pytest.fixture
def api(monkeypatch,tmp_path):
    from app import compute_queue_api as compute
    from app import backend_admission
    from app.action_harness import ActionHarness
    from app.agent_runtime import AgentAuthorityRuntime
    from app.job_queue import JobQueue
    monkeypatch.setattr(compute,'queue',JobQueue(str(tmp_path/'queue.db'),compute.POLICY))
    # This fixture tests authenticated routing, not measured model admission.
    monkeypatch.setattr(backend_admission,'reserve_model',lambda *_args,**_kw:None)
    monkeypatch.setattr(compute,'_validate_job_lease',no_gate)
    monkeypatch.setattr(ActionHarness,'authorize',no_gate)
    monkeypatch.setattr(AgentAuthorityRuntime,'begin_path',no_gate)
    from app.direct_entry import app
    return TestClient(app),compute


@pytest.mark.parametrize('classification',['R0','R1','R2','R3'])
def test_direct_routing_all_classes(api,classification):
    client,compute=api
    response=client.post('/api/agents/dispatch',headers={'Authorization':'Bearer isolated-test-owner'},json={
        'capability':'responsibility.a17','objective':'Reply exactly: hello','classification':classification})
    assert response.status_code==202,response.text
    value=response.json();job=value['job']
    assert job['status']=='queued' and not job['harness_envelope']
    assert job['classification']==classification
    from app.job_queue import Provider
    claimed=compute.queue.claim('test',[Provider('ollama-fast','local',job['model'],32768,0,1)])
    assert claimed['id']==job['id']
    assert value['execution_model']=='DIRECT_OBSERVED'


@pytest.mark.parametrize('classification',['R0','R1','R2','R3'])
def test_real_connector_effect_and_audit(tmp_path,classification):
    registry=ConnectorRegistry();out=tmp_path/'effect.txt'
    registry.register(Sink('file','write',classification,'test file',True,'LOCAL_ONLY','unused'),
        lambda payload:out.write_text(payload['text']))
    assert registry.execute('file','write',{'text':'actual'},task_id='t',agent_id='a17')==6
    assert out.read_text()=='actual'
    ledger=action_ledger();assert ledger.flush()
    records=[json.loads(x) for x in ledger.path.read_text().splitlines()]
    assert [x['phase'] for x in records]==['started','completed']
    assert records[-1]['success'] is True and records[-1]['classification']==classification
    previous='0'*64
    for row in records:
        digest=row.pop('sha256');assert row['previous_sha256']==previous
        assert hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==digest
        previous=digest


def test_logging_failure_does_not_block(tmp_path):
    obstruction=tmp_path/'file';obstruction.write_text('original')
    ledger=ActionLedger(obstruction/'audit.jsonl')
    assert DirectExecutor(ledger).execute(ActionRecord('t','a17','test','fixture'),lambda:42)==42
    assert not ledger.flush()
    assert ledger.status()['dropped']==2 and not ledger.status()['healthy']
    assert obstruction.read_text()=='original'
    ledger.close()


def test_record_creation_failure_and_failed_action(tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl')
    executor=DirectExecutor(ledger)
    assert executor.execute(None,lambda:42)==42
    assert not ledger.flush() and ledger.status()['dropped']==2
    with pytest.raises(ValueError):executor.execute(ActionRecord('t','a17','test','fixture'),lambda:(_ for _ in ()).throw(ValueError('secret detail')))
    ledger.flush()
    rows=[json.loads(x) for x in ledger.path.read_text().splitlines()]
    assert rows[-1]['success'] is False and rows[-1]['error']=='ValueError'
    ledger.close()


def test_factory_failure_observable(monkeypatch):
    import app.action_records as records
    monkeypatch.setattr(records,'ActionLedger',no_gate)
    ledger=records.action_ledger()
    assert DirectExecutor(ledger).execute(ActionRecord('t','a17','test','fixture'),lambda:42)==42
    assert not ledger.status()['healthy'] and ledger.status()['dropped']==2


def test_secrets_redacted(tmp_path):
    ledger=ActionLedger(tmp_path/'audit')
    ledger.emit(ActionRecord('t','a17','test','fixture',parameters_summary={'api_key':'secret-value','text':'Bearer abc'}),'started')
    assert ledger.flush();raw=ledger.path.read_text();assert 'secret-value' not in raw and 'Bearer abc' not in raw
    ledger.close()


def test_direct_sandbox_and_containment(api,monkeypatch):
    client,_=api
    import app.engineering_api as engineering
    monkeypatch.setattr(engineering,'require_bounded_work_capacity',lambda:None)
    headers={'Authorization':'Bearer isolated-test-owner'}
    for role in ('A12 Builder','A13 Test Engineer'):
        result=client.post('/api/agents/engineering/wasm',headers=headers,json={
            'role':role,'source':'(module (func (export "answer") (result i32) i32.const 42))','export':'answer'})
        assert result.status_code==200,result.text
        assert result.json()['result']['result']==42
    denied=client.post('/api/agents/engineering/wasm',headers=headers,json={
        'role':'A12 Builder','source':'(module (import "host" "run" (func)))','export':'run'})
    assert denied.status_code==422


def test_parallel_failure_isolation_and_repair(tmp_path):
    from app.workflow_engine import Task,execute
    from app.engineering_loop import build_verify
    barrier=threading.Barrier(2)
    def together(*args):barrier.wait(timeout=2);return 'ran'
    result=execute((Task('a',(),'a17','run',authority_class='R2'),Task('b',(),'a18','run',authority_class='R3'),
        Task('fail',('a',),'a17','missing'),Task('blocked',('fail',),'a18','run')),
        {'run':together},{},workers=2)
    assert result['tasks']['a']['status']==result['tasks']['b']['status']=='COMPLETED'
    assert result['tasks']['fail']['status']=='FAILED' and result['tasks']['blocked']['status']=='BLOCKED'


def test_client_auth_and_legacy_routes_absent(api):
    client,_=api
    assert client.get('/health').status_code==401
    assert client.post('/api/harness/pilot/dispatch',json={}).status_code==404
    assert client.get('/health',headers={'Authorization':'Bearer isolated-test-owner'}).json()['agents']==21


def test_cancellation_is_operational(api):
    _,compute=api
    job=compute.queue.submit(agent='a17',prompt='hello',classification='R3')
    assert compute.queue.cancel(job['id'])['status']=='cancelled'
    assert compute.queue.finish(job['id'],result='late result')['status']=='cancelled'


def test_direct_stream_without_lease(monkeypatch,tmp_path):
    from app.direct_stream import infer
    import app.direct_stream as stream
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def raise_for_status(self):pass
        async def aiter_lines(self):
            yield json.dumps({'message':{'content':'actual'},'done':True,'eval_count':1})
    class Client(Response):
        def __init__(self,*args,**kwargs):pass
        def stream(self,*args,**kwargs):return Response()
    monkeypatch.setattr(stream.httpx,'AsyncClient',Client)
    settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive='1m',context_tokens=128,max_output_tokens=4)
    result=asyncio.run(infer({'prompt':'test','timeout_seconds':1,'ram_mb':1024},SimpleNamespace(model='gemma3:1b'),settings=settings,capacity=lambda m:None,options=lambda:{}))
    assert result['result']=='actual'


def test_closed_ledger_reports_loss(tmp_path):
    ledger=ActionLedger(tmp_path/'audit');assert ledger.close()
    assert DirectExecutor(ledger).execute(ActionRecord('t','a17','test','fixture'),lambda:42)==42
    assert ledger.status()['dropped']==2 and not ledger.status()['healthy']


def test_direct_router_has_no_approval_inputs():
    from app.tier_router import select_direct_route,Backend,Tier
    backend=Backend('fixture-cloud','fixture-model',Tier.MINI,'cloud')
    assert select_direct_route((backend,),minimum_tier=Tier.MINI,classification='CLOUD_PERMITTED',text='ordinary').state=='READY'
    assert select_direct_route((backend,),minimum_tier=Tier.MINI,classification='LOCAL_ONLY',text='ordinary').state=='UNAVAILABLE'
    assert select_direct_route((backend,),minimum_tier=Tier.MINI,classification='CLOUD_PERMITTED',text='api_key=secret').state=='UNAVAILABLE'


def test_interface_identity_not_action_approval(api,monkeypatch):
    client,_=api
    monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON',json.dumps({'one':{'token_sha256':hashlib.sha256(b'client-one').hexdigest()},'two':{'token_sha256':hashlib.sha256(b'client-two').hexdigest()}}))
    headers={'X-Client-ID':'one','Authorization':'Bearer client-one'}
    submitted=client.post('/api/interface/v1/objectives',headers=headers,json={'objective':'Hello','idempotency_key':'once'})
    assert submitted.status_code==202,submitted.text
    task=submitted.json()['task_id']
    assert client.get('/api/interface/v1/tasks/'+task,headers={'X-Client-ID':'two','Authorization':'Bearer client-two'}).status_code==404
    assert client.post('/api/interface/v1/tasks/'+task+'/cancel',headers=headers).status_code==200


def _silent_stream_fixture(monkeypatch):
    import app.direct_stream as stream
    entered=threading.Event()
    closed=[]
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):closed.append('response')
        def raise_for_status(self):pass
        async def aiter_lines(self):
            entered.set()
            await asyncio.Event().wait()
            yield '{}'
    class Client(Response):
        def __init__(self,*args,**kwargs):pass
        async def __aexit__(self,*args):closed.append('client')
        def stream(self,*args,**kwargs):return Response()
    monkeypatch.setattr(stream.httpx,'AsyncClient',Client)
    settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive='1m',context_tokens=128,max_output_tokens=4)
    return entered,closed,settings


def test_stream_cancel_closes_silent_connection(monkeypatch):
    from app.direct_stream import infer
    entered,closed,settings=_silent_stream_fixture(monkeypatch)
    # Cancellation tests HTTP cleanup, not a one-second cold-start deadline.
    # Signal only after both contexts opened and the fake stream is waiting.
    with pytest.raises(RuntimeError,match='cancelled'):
        asyncio.run(infer({'prompt':'test','timeout_seconds':5,'ram_mb':1024},SimpleNamespace(model='gemma3:1b'),settings=settings,capacity=lambda m:None,options=lambda:{},cancelled=entered.is_set))
    assert entered.is_set() and closed==['response','client']


def test_stream_deadline_still_closes_silent_connection(monkeypatch):
    from app.direct_stream import infer
    entered,closed,settings=_silent_stream_fixture(monkeypatch)
    with pytest.raises(TimeoutError):
        asyncio.run(infer({'prompt':'test','timeout_seconds':.1,'ram_mb':1024},SimpleNamespace(model='gemma3:1b'),settings=settings,capacity=lambda m:None,options=lambda:{},cancelled=lambda:False))
    assert entered.is_set() and closed==['response','client']


def test_cloud_queue_metadata_is_not_approval(tmp_path):
    from app.job_queue import JobQueue,QueuePolicy,Provider
    queue=JobQueue(tmp_path/'cloudfixture.db',QueuePolicy(cloud_wait_seconds=0,max_job_cost_usd=2,daily_cost_ceiling_usd=3))
    job=queue.submit(agent='a17',prompt='fixture',model='fixture-model',allow_cloud=True,max_cost_usd=1,classification='R3',data_classification='CLOUD_PERMITTED')
    assert job['status']=='queued' and job['approval_status']=='not_required'
    assert queue.claim('test',[Provider('fixture','cloud','fixture-model',32768,0,1)])['id']==job['id']


def test_cloud_cost_capacity_still_applies(tmp_path):
    from app.job_queue import JobQueue,QueuePolicy,Provider
    queue=JobQueue(tmp_path/'cost.db',QueuePolicy(cloud_wait_seconds=0,max_job_cost_usd=2,daily_cost_ceiling_usd=3))
    job=queue.submit(agent='a17',prompt='x'*10000,model='large',allow_cloud=True,max_cost_usd=.01,data_classification='CLOUD_PERMITTED')
    assert queue.claim('test',[Provider('fixture','cloud','large',32768,0,1,10000,10000)]) is None
    assert queue.get(job['id'])['status']=='budget_blocked'


def test_new_entry_is_direct(api):
    from app.entry import app
    assert app.title=='ORQEVIA · 奥启维亚 — direct execution'


def test_buffer_saturation_is_observable(tmp_path,monkeypatch):
    import app.action_records as records
    # Hold the writer only in this fixture to deterministically fill its buffer.
    release=threading.Event()
    original=records.ActionLedger._write
    def delayed(self):release.wait(timeout=3);original(self)
    monkeypatch.setattr(records.ActionLedger,'_write',delayed)
    ledger=ActionLedger(tmp_path/'audit',capacity=1)
    try:
        assert DirectExecutor(ledger).execute(ActionRecord('t','a17','fixture','test'),lambda:42)==42
        assert ledger.status()['dropped']==1 and ledger.status()['last_error']=='Full'
    finally:release.set();ledger.close()
