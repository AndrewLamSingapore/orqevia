import asyncio
from decimal import Decimal
import json
import sqlite3
import httpx
import pytest
from app.provider_runtime import ChatCompletionProvider,ModelSpec,ProviderFailure,complete

MODEL=ModelSpec('fixture','fixture','MINI',4096,64)

@pytest.mark.parametrize('stream',[False,True])
def test_explicit_capacity_is_rejected_admission(stream):
    message={'error':{'message':'Selected model is at capacity. Please try a different model.'}}
    response=httpx.Response(200,text='data: '+json.dumps(message)+'\n\n') if stream else httpx.Response(503,json=message)
    adapter=ChatCompletionProvider('https://fixture.invalid/chat','ref',secret_resolver=lambda _:'mock-value',transport=httpx.MockTransport(lambda _:response))
    with pytest.raises(ProviderFailure) as caught:asyncio.run(complete(adapter,MODEL,[],output_tokens=4,max_retries=0))
    assert caught.value.code=='CAPACITY' and caught.value.pre_execution is (not stream)

def test_stream_capacity_does_not_replay_after_accepted_http_200():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,text='data: '+json.dumps({'error':{'message':'Selected model is at capacity. Please try a different model.'}})+'\n\n')
    adapter=ChatCompletionProvider('https://fixture.invalid/chat','ref',secret_resolver=lambda _:'mock-value',transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure,match='CAPACITY'):
        asyncio.run(complete(adapter,MODEL,[],output_tokens=4,max_retries=2))
    assert len(calls)==1

def fixture(monkeypatch,tmp_path,*,tier='FLAGSHIP',rate='1',qualified=True,partial=False):
    from app import cloud_execution as cloud
    from app.job_queue import JobQueue,QueuePolicy,Provider
    root=tmp_path/'capacity-fixture';root.mkdir()
    monkeypatch.setenv('PRIME_DATA_DIR',str(root))
    base={'enabled':True,'qualification_status':'QUALIFIED','location':'cloud','tier':'MINI','context_tokens':4096,
          'output_tokens':64,'input_usd_million':'1','output_usd_million':'1','endpoint':'https://fixture.invalid/chat'}
    entries=[dict(base,id='preferred',model='preferred-model',secret_ref='preferred',fallback_ids=['alternate']),
             dict(base,id='alternate',model='alternate-model',secret_ref='alternate',tier=tier,input_usd_million=rate,
                  qualification_status='QUALIFIED' if qualified else 'UNMEASURED')]
    calls=[];delays=[]
    class Adapter:
        def __init__(self,endpoint,ref,**kwargs):self.ref=ref
        async def stream(self,*args):
            from app.provider_runtime import Chunk,Usage
            calls.append(self.ref)
            if self.ref=='preferred':
                if partial:yield Chunk(text='partial')
                raise ProviderFailure('CAPACITY',True,pre_execution=True)
            yield Chunk(text='verified output',usage=Usage(10,2,1));yield Chunk(complete=True)
    async def sleep(delay):delays.append(delay)
    monkeypatch.setattr(cloud,'load_catalog',lambda:entries)
    monkeypatch.setattr(cloud,'ChatCompletionProvider',Adapter)
    monkeypatch.setattr(asyncio,'sleep',sleep)
    queue=JobQueue(root/'queue.db',QueuePolicy(cloud_wait_seconds=0))
    provider=Provider('preferred','cloud','preferred-model',0,0,1,1,1,64)
    submitted=queue.submit(agent='a10',prompt='Synthetic nonsecret interpretation',allow_cloud=True,
        preferred_provider='preferred',data_classification='CLOUD_PERMITTED',max_cost_usd=.01,timeout_seconds=10)
    job=queue.claim('fixture-worker',[provider]);assert job and job['id']==submitted['id']
    def run():
        result=cloud.execute_cloud(job,provider,root,lambda:False)
        queue.finish(job['id'],**result)
        return result
    def metrics():
        with sqlite3.connect(root/'compute-ledger.db') as db:return json.loads(db.execute('SELECT details FROM reasoning_attempts').fetchone()[0])
    return run,calls,delays,metrics,queue,job,root

def test_real_queue_dispatch_retry_higher_qualified_fallback_and_durable_metrics(monkeypatch,tmp_path):
    run,calls,delays,metrics,queue,job,root=fixture(monkeypatch,tmp_path)
    result=run()
    assert calls==['preferred','preferred','alternate'] and delays==[1]
    assert result['input_tokens']==10 and result['output_tokens']==2
    stored=queue.get(job['id']);assert stored['status']=='completed' and stored['actual_cost_usd']>=0
    detail=metrics()
    assert detail['requested_tier']=='MINI' and detail['requested_model']=='preferred-model'
    assert detail['model']=='alternate-model' and detail['retries']==1
    assert detail['cached_tokens']==1 and detail['fallback_route']==[{'provider':'preferred','code':'CAPACITY'}]
    assert detail['success'] is True
    assert detail['error_classifications']==['CAPACITY']

@pytest.mark.parametrize('kwargs,code',[
    ({'tier':'NANO'},'FALLBACK_POLICY_DENIED'),({'rate':'10000'},'FALLBACK_POLICY_DENIED'),
    ({'qualified':False},'FALLBACK_UNQUALIFIED'),({'partial':True},'CAPACITY')])
def test_no_downgrade_budget_escape_unqualified_or_partial_replay(monkeypatch,tmp_path,kwargs,code):
    run,calls,delays,metrics,queue,job,root=fixture(monkeypatch,tmp_path,**kwargs)
    with pytest.raises(ProviderFailure,match=code):run()
    assert 'alternate' not in calls
    if kwargs.get('partial'):assert calls==['preferred'] and delays==[]
    assert metrics()['success'] is False
    if kwargs.get('tier')=='NANO' or kwargs.get('rate'):
        assert metrics()['retries']==1 and metrics()['fallback_route']==[{'provider':'preferred','code':'CAPACITY'}]

def test_generic_503_not_capacity_or_retried():
    calls=[]
    adapter=ChatCompletionProvider('https://fixture.invalid/chat','ref',secret_resolver=lambda _:'mock-value',
        transport=httpx.MockTransport(lambda _:calls.append(1) or httpx.Response(503,json={'error':{'message':'Uncertain upstream execution'}})))
    with pytest.raises(ProviderFailure) as caught:asyncio.run(complete(adapter,MODEL,[],output_tokens=4))
    assert caught.value.code=='PROVIDER_HTTP_FAILURE' and not caught.value.pre_execution and len(calls)==1
