"""Native disposable STORE/control-flow tests; mocked HTTP never qualifies models."""
import copy,json,uuid,sqlite3,hashlib
from datetime import timedelta
from types import SimpleNamespace
import httpx,pytest
from app import agent_cert_resident_model as residency,backend_admission
from app.job_queue import JobQueue,QueuePolicy
from app.agent_registry import REGISTRY_PATH
from app.action_records import ActionLedger
from tests.test_agent_cert_authority_chain import runtime as objective_runtime
from tests.test_agent_cert_review_dispatch import configured

SOURCE='c'*40
ENDPOINT='http://127.0.0.1:11435'
PROMPT='Classify these public synthetic checks: true,false,true. Reply only DEGRADED if any is false, otherwise PASS.'
FAST='gemma3:1b';DEEP='gemma3:4b'

def raw(value):return residency.canonical(value)
def models(*names):
    return raw(dict(models=[dict(name=name,model=name,digest='a'*64 if name==FAST else 'b'*64,
        expires_at=(residency.now()+timedelta(seconds=60)).isoformat()) for name in names]))

@pytest.fixture
def native(tmp_path,monkeypatch):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT','PRIME_MEASURED_COMPUTE_PROFILE',
        'PRIME_MEASURED_COMPUTE_PROFILE_SHA256','PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE','golden_n1');monkeypatch.setenv('OLLAMA_BASE_URL',ENDPOINT)
    domain=str(uuid.uuid4());(tmp_path/'source-qualification-domain.json').write_bytes(raw(dict(
        schema='prime.source-qualification-domain.v1',domain_id=domain,source_revision=SOURCE,
        scope='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME')))
    queue=JobQueue(tmp_path/'compute-queue.db',QueuePolicy())
    ledger=ActionLedger(tmp_path/'action-records.jsonl')
    settings=SimpleNamespace(ollama_base_url=ENDPOINT,fast_model=FAST,deep_model=DEEP,
        keep_alive='10m',context_tokens=128,max_output_tokens=8)
    value=SimpleNamespace(root=tmp_path,domain=domain,queue=queue,ledger=ledger,settings=settings)
    yield value
    ledger.close()

def contract(native):
    return residency.ResidentAdmissionContract(SOURCE,native.domain,native.root,residency.sha(PROMPT.encode()),
        FAST,DEEP,'a'*64,'b'*64,residency.sha(REGISTRY_PATH.read_bytes()),residency.ResidentCaseWindow())

def transport(monkeypatch,*,ps=None,fault=None):
    calls=[];client_class=httpx.AsyncClient
    def handler(request):
        calls.append((request.method,request.url.path,request.content))
        if request.method=='GET':return httpx.Response(200,content=models(DEEP) if ps is None else ps)
        if fault=='ambiguous':raise httpx.ReadError('Disposable ambiguous POST')
        if fault=='5xx':return httpx.Response(503,content=b'Unavailable')
        final=dict(model=DEEP,message={'content':'DEGRADED'},done=True,prompt_eval_count=8,eval_count=3,
            load_duration=98765,eval_duration=54321)
        if fault=='partial':final.pop('done')
        if fault=='wrong_model':final['model']=FAST
        if fault=='missing_load':final.pop('load_duration')
        return httpx.Response(200,content=raw(final)+b'\n')
    mocked=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:client_class(transport=mocked,**kwargs))
    return calls

def run(native,value):return residency.run_source_assessment(native.queue,settings=native.settings,
    contract=value,prompt=PROMPT,ledger=native.ledger)

@pytest.mark.parametrize('attribute',['started','monotonic_started','deadline'])
def test_original_window_anchors_cannot_be_reset(attribute):
    from dataclasses import FrozenInstanceError
    window=residency.ResidentCaseWindow();original=getattr(window,attribute)
    with pytest.raises(FrozenInstanceError):setattr(window,attribute,original)
    assert getattr(window,attribute)==original

def test_denial_receipt_copies_cannot_change_original_phase():
    original={'phase':'PRE_DISPATCH','decision':'RESIDENCY_UNAVAILABLE'}
    error=residency.ResidencyUnavailable(original)
    original['phase']='POST_DISPATCH';error.receipt['phase']='POST_DISPATCH'
    assert error.receipt['phase']=='PRE_DISPATCH'

def test_original_authenticated_objective_window_is_not_reset(objective_runtime,monkeypatch):
    from app import agent_cert_initialization as initialization
    from app.agent_cert_role_review import canonical_case_spec
    from tests.test_agent_cert_operator_io import TOKEN
    from copy import deepcopy
    spec=canonical_case_spec('a19','responsibility.a19','baseline:initialization')
    body=spec['request'];captured=[];original=initialization.build_initialization_report
    anchor=residency.ResidentCaseWindow()
    def observed(task_id,**kwargs):
        narrowed=residency.ResidentCaseWindow.from_original_task(root=objective_runtime.root,
            task_id=task_id,submitted_request=body,runtime=kwargs['runtime'],dispatch_window=anchor)
        assert narrowed.monotonic_started==anchor.monotonic_started
        assert narrowed.deadline<=anchor.deadline and narrowed.started<=anchor.started
        bad=deepcopy(body);bad['objective']+=' altered'
        with pytest.raises(ValueError):
            residency.ResidentCaseWindow.from_original_task(root=objective_runtime.root,
                task_id=task_id,submitted_request=bad,runtime=kwargs['runtime'],dispatch_window=anchor)
        captured.append(task_id);return original(task_id,**kwargs)
    monkeypatch.setattr(initialization,'build_initialization_report',observed)
    response=objective_runtime.client.post('/api/agents/objectives',json=body,
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==202,response.text
    assert captured==[response.json()['id']]

def test_post_dispatch_residency_loss_preserves_chat_and_never_falls_back(native,monkeypatch):
    calls=[];client_class=httpx.AsyncClient
    def handler(request):
        calls.append((request.method,request.url.path,request.content))
        if request.method=='GET':
            count=sum(method=='GET' for method,_,_ in calls)
            return httpx.Response(200,content=models(FAST) if count==1 else models())
        return httpx.Response(200,content=raw(dict(model=FAST,message={'content':'DEGRADED'},
            done=True,prompt_eval_count=8,eval_count=3,load_duration=98765))+b'\n')
    mocked=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:client_class(transport=mocked,**kwargs))
    with pytest.raises(residency.ResidencyLostAfterDispatch):run(native,contract(native))
    assert [json.loads(body)['model'] for method,_,body in calls if method=='POST']==[FAST]
    with sqlite3.connect(native.queue.db_path) as database:
        assert database.execute('SELECT model,status,attempts FROM compute_jobs').fetchall()==[(FAST,'failed',1)]
    receipt=json.loads((native.root/'source-residency-fast-failure.json').read_bytes())
    assert receipt['attempt']['residency']['phase']=='POST_DISPATCH'
    assert 'DEGRADED' in receipt['native_chat_utf8'] and receipt['state']=='SOURCE_UNREADY'

def test_original_native_jobs_lease_and_audit_mock_response_never_qualified(native,monkeypatch):
    calls=transport(monkeypatch);trace=[]
    for name in ('check','dispatch','completed','cancel'):
        original=getattr(backend_admission,name)
        def traced(connection,endpoint,job,*args,_name=name,_original=original,**kwargs):
            trace.append((_name,job,connection.execute('SELECT state FROM backend_admission WHERE job_id=?',(job,)).fetchall()))
            return _original(connection,endpoint,job,*args,**kwargs)
        monkeypatch.setattr(backend_admission,name,traced)
    value=run(native,contract(native))
    assert value['state']=='SOURCE_UNREADY' and value['certification']=='UNVERIFIED'
    assert value['fallback_exercised'] is True and value['atomic_no_cold_load_guarantee'] is False
    first,last=[item['job'] for item in value['attempts']]
    assert first['status']=='failed' and first['error']=='RESIDENCY_UNAVAILABLE' and first['model']==FAST
    assert last['status']=='completed' and last['model']==DEEP and first['prompt']==last['prompt']==PROMPT
    assert first['attempts']==last['attempts']==1 and first['max_retries']==last['max_retries']==0
    assert [json.loads(body)['model'] for method,path,body in calls if method=='POST']==[DEEP]
    ps=[item for item in trace if item[0]=='check'];assert ps and ps[0][2]==[('pending',)]
    assert any(name=='dispatch' and job==last['id'] and rows==[('pending',)] for name,job,rows in trace)
    assert any(name=='completed' and job==last['id'] and rows==[('running',)] for name,job,rows in trace)
    with sqlite3.connect(native.queue.db_path) as database:
        assert database.execute('SELECT COUNT(*) FROM backend_admission').fetchone()[0]==0
        assert database.execute('SELECT COUNT(*) FROM compute_jobs').fetchone()[0]==2
    lines=(native.root/'action-records.jsonl').read_text().splitlines()
    assert len(lines)==4 and [json.loads(line)['phase'] for line in lines]==['started','completed']*2
    after=value['attempts'][1]['residency'];assert after['before']['raw_ps_sha256']==residency.sha(after['before']['raw_ps_utf8'].encode())
    assert after['completion']['load_duration']==98765 # Preserved, never invented zero.
    assert after['native_chat_utf8'].endswith('\n')
    with pytest.raises(FileExistsError):run(native,contract(native))
    assert sum(method=='POST' for method,_,_ in calls)==1

@pytest.mark.parametrize('fault',['ambiguous','5xx','partial','wrong_model','missing_load'])
def test_native_post_ambiguity_and_completion_drift_never_replayed(native,monkeypatch,fault):
    calls=transport(monkeypatch,fault=fault)
    with pytest.raises(Exception):run(native,contract(native))
    assert sum(method=='POST' for method,_,_ in calls)==1
    assert (native.root/'source-residency-deep-failure.json').exists()
    assert not (native.root/'source-residency-result.json').exists()
    with sqlite3.connect(native.queue.db_path) as database:
        states=database.execute('SELECT status,attempts,max_retries FROM compute_jobs ORDER BY rowid').fetchall()
        assert states==[('failed',1,0),('failed',1,0)]
        assert database.execute('SELECT state FROM backend_admission').fetchall()==[('uncertain',)]

@pytest.mark.parametrize('defect',['wrong_digest','duplicate_model','expired','short_expiry','missing_expiry','bad_json','huge','duplicate_key'])
def test_original_ps_strict_binding_and_unavailable_expiry(native,monkeypatch,defect):
    value=contract(native);body=json.loads(models(DEEP))
    if defect=='wrong_digest':body['models'][0]['digest']='c'*64
    elif defect=='duplicate_model':body['models']*=2
    elif defect=='expired':body['models'][0]['expires_at']=(residency.now()-timedelta(seconds=1)).isoformat()
    elif defect=='short_expiry':body['models'][0]['expires_at']=(residency.now()+timedelta(seconds=1)).isoformat()
    elif defect=='missing_expiry':body['models'][0].pop('expires_at')
    original=raw(body)
    if defect=='bad_json':original=b'{'
    elif defect=='huge':original=b'x'*(residency.MAX_PS+1)
    elif defect=='duplicate_key':original=b'{"models":[],"models":[]}'
    calls=transport(monkeypatch,ps=original)
    with pytest.raises(Exception):run(native,value)
    assert not any(method=='POST' for method,_,_ in calls)
    assert not (native.root/'source-residency-result.json').exists()

@pytest.mark.parametrize('defect',['actor','prompt','cloud','cost','role','attempts','missing_lease','wrong_source_marker','timeout','classification','provider_preference','ram'])
def test_native_original_store_tamper_rejected_before_request(native,monkeypatch,defect):
    calls=transport(monkeypatch);original_claim=native.queue.claim
    def claim(*args,**kwargs):
        job=original_claim(*args,**kwargs)
        with native.queue.connect() as db:
            updates={'actor':('agent','a26'),'prompt':('prompt','changed'),'cloud':('allow_cloud',1),
                'cost':('max_cost_usd',1),'role':('model_role','deep'),'attempts':('attempts',2),
                'timeout':('timeout_seconds',30),'classification':('classification','R2'),
                'provider_preference':('preferred_provider','ollama-deep'),'ram':('ram_mb',1025)}
            if defect in updates:
                key,value=updates[defect];db.execute('UPDATE compute_jobs SET '+key+'=? WHERE id=?',(value,job['id']))
            elif defect=='missing_lease':db.execute('DELETE FROM backend_admission')
        if defect=='wrong_source_marker':
            marker=json.loads((native.root/'source-qualification-domain.json').read_bytes());marker['source_revision']='d'*40
            (native.root/'source-qualification-domain.json').write_bytes(raw(marker))
        return job
    monkeypatch.setattr(native.queue,'claim',claim)
    with pytest.raises(Exception):run(native,contract(native))
    assert calls==[]


def test_shared_budget_and_clock_rollback_cannot_widen(native,monkeypatch):
    window=residency.ResidentCaseWindow();clock=window.monotonic_started
    monkeypatch.setattr(residency.time,'monotonic',lambda:clock+4)
    monkeypatch.setattr(residency,'now',lambda:window.started-timedelta(seconds=60))
    assert 0<window.remaining()<=1
    monkeypatch.setattr(residency.time,'monotonic',lambda:clock+5)
    with pytest.raises(residency.ResidencyAdmissionError):window.remaining()


def test_wrong_contract_class_cannot_expand_inference(native,monkeypatch):
    import asyncio
    from app.direct_stream import infer
    calls=transport(monkeypatch)
    with pytest.raises(residency.ResidencyAdmissionError):asyncio.run(infer({'timeout_seconds':5},SimpleNamespace(model=FAST),
        settings=native.settings,capacity=lambda _:None,options=lambda:{},residency_contract=object()))
    assert calls==[]
@pytest.mark.parametrize('defect',['growth_during_read','replacement_at_open'])
def test_marker_toctou_is_bounded_and_rejected_before_sql(native,monkeypatch,defect):
    value=contract(native);marker=native.root/'source-qualification-domain.json'
    original_open=type(marker).open;read_limits=[]
    def guarded(path,*args,**kwargs):
        if path!=marker:return original_open(path,*args,**kwargs)
        if defect=='replacement_at_open':
            marker.rename(native.root/'source-marker-original.json')
            with original_open(marker,'wb') as other:other.write(b'{}')
        held=original_open(path,*args,**kwargs)
        class Held:
            def __enter__(self):return self
            def __exit__(self,*args):return held.__exit__(*args)
            def fileno(self):return held.fileno()
            def read(self,count):
                read_limits.append(count)
                if defect=='growth_during_read':
                    with original_open(marker,'ab') as writer:writer.write(b'x'*100000)
                return held.read(count)
        return Held()
    monkeypatch.setattr(type(marker),'open',guarded)
    monkeypatch.setattr(sqlite3,'connect',lambda *args,**kwargs:pytest.fail('SQLite must not open after marker TOCTOU'))
    with pytest.raises(residency.ResidencyAdmissionError):value.source_domain()
    assert read_limits in ([],[4097])

@pytest.mark.parametrize('defect',['oversized_shm','aggregate_sidecars'])
def test_native_sidecars_are_admitted_before_sqlite_connection(native,monkeypatch,defect):
    value=contract(native);db=native.root/'compute-queue.db'
    if defect=='oversized_shm':
        with open(str(db)+'-shm','wb') as file:file.write(b'x'*(8*1024*1024+1))
    else:
        with open(str(db)+'-wal','wb') as file:file.write(b'x'*(4*1024*1024))
        with open(str(db)+'-shm','wb') as file:file.write(b'x'*(4*1024*1024))
    monkeypatch.setattr(sqlite3,'connect',lambda *args,**kwargs:pytest.fail('SQLite must not open after native sidecar rejection'))
    with pytest.raises(residency.ResidencyAdmissionError):value.native_row(dict(_admission_db=str(db),id=str(uuid.uuid4())))


def test_real_original_pending_admission_expiration_stops_without_secondary(native,monkeypatch):
    import time
    calls=[];client_class=httpx.AsyncClient
    def handler(request):
        calls.append((request.method,request.url.path));time.sleep(5.05)
        return httpx.Response(200,content=models(DEEP))
    mocked=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:client_class(transport=mocked,**kwargs))
    with pytest.raises(Exception):run(native,contract(native))
    assert calls==[('GET','/api/ps')]
    with sqlite3.connect(native.queue.db_path) as db:
        assert db.execute('SELECT status,attempts FROM compute_jobs').fetchall()==[('failed',1)]
        assert db.execute('SELECT COUNT(*) FROM backend_admission').fetchone()[0]==0



def test_current_registry_digest_drift_before_native_http(native,monkeypatch):
    from app import agent_registry
    value=contract(native);copied=native.root/'changed-public-registry.json'
    original=agent_registry.REGISTRY_PATH.read_bytes();copied.write_bytes(b' '+original)
    monkeypatch.setattr(agent_registry,'REGISTRY_PATH',copied)
    calls=transport(monkeypatch)
    with pytest.raises(Exception):run(native,value)
    assert calls==[]
