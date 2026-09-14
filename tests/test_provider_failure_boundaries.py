import asyncio
import json
import httpx
import pytest
from app.provider_runtime import (ModelSpec,Chunk,Usage,ProviderFailure,
    ChatCompletionProvider,complete,complete_with_fallback)

MODEL=ModelSpec('fixture','fixture','MINI',4096,64)

def wire(body,status=200):
    return ChatCompletionProvider('https://fixture.invalid/chat','fixture-ref',
        secret_resolver=lambda ref:'fixture-value',
        transport=httpx.MockTransport(lambda req:httpx.Response(status,text=body)))

@pytest.mark.parametrize('item', [[],1,'secret-content',None,
    {'choices':42},{'choices':[None]}, {'choices':[{'delta':[]}]},
    {'choices':[{'delta':{'content':{'secret-content':1}}}]},
    {'choices':[{'index':False}]},{'usage':{'prompt_tokens':True,'completion_tokens':1}},
    {'usage':{'prompt_tokens':1.2,'completion_tokens':1}},
    {'usage':{'prompt_tokens':1,'completion_tokens':1,'prompt_tokens_details':[]}}])
def test_malformed_shapes_are_sanitized(item):
    with pytest.raises(ProviderFailure) as exc:
        asyncio.run(complete(wire('data: '+json.dumps(item)+'\n\n'),MODEL,[],output_tokens=4))
    assert exc.value.code in {'MALFORMED_STREAM','INVALID_USAGE'}
    assert 'secret-content' not in str(exc.value)

def test_http500_is_not_replayed():
    calls=[]
    adapter=ChatCompletionProvider('https://fixture.invalid/chat','ref',secret_resolver=lambda ref:'fixture',
        transport=httpx.MockTransport(lambda req:calls.append(1) or httpx.Response(500)))
    with pytest.raises(ProviderFailure):asyncio.run(complete(adapter,MODEL,[],output_tokens=4))
    assert len(calls)==1

class Fixture:
    def __init__(self,code=None,pre=False,partial=False,usage=False):
        self.calls=0;self.code=code;self.pre=pre;self.partial=partial;self.usage=usage
    async def stream(self,*args):
        self.calls+=1
        if self.partial:yield Chunk(text='partial')
        if self.usage:yield Chunk(usage=Usage(2,0,0))
        if self.code:raise ProviderFailure(self.code,pre_execution=self.pre)
        yield Chunk(text='verified fixture response')
        yield Chunk(complete=True)

def test_preflight_fallback_rechecks_policy():
    first=Fixture('CREDENTIAL_UNAVAILABLE',True);second=Fixture();checks=[]
    result=asyncio.run(complete_with_fallback([(first,MODEL),(second,MODEL)],[],
        authorize_candidate=lambda *args:checks.append(args) or True,output_tokens=4))
    assert len(checks)==2 and second.calls==1
    assert result['fallback_failures']==[{'provider':'fixture','code':'CREDENTIAL_UNAVAILABLE'}]
    first=Fixture('CREDENTIAL_UNAVAILABLE',True);second=Fixture();checks=[]
    with pytest.raises(ProviderFailure,match='FALLBACK_POLICY_DENIED'):
        asyncio.run(complete_with_fallback([(first,MODEL),(second,MODEL)],[],
            authorize_candidate=lambda *args:checks.append(args) or len(checks)==1,output_tokens=4))
    assert second.calls==0

@pytest.mark.parametrize('code,pre,partial,usage',[
    ('PROVIDER_TRANSPORT_FAILURE',False,False,False),('PROVIDER_TIMEOUT',False,False,False),
    ('RATE_LIMIT',True,True,False),('RATE_LIMIT',True,False,True),
    ('CANCELLED',True,False,False),('CONTEXT_BUDGET_EXCEEDED',True,False,False)])
def test_ambiguous_or_partial_failure_never_falls_back(code,pre,partial,usage):
    first=Fixture(code,pre,partial,usage);second=Fixture()
    with pytest.raises(ProviderFailure):
        asyncio.run(complete_with_fallback([(first,MODEL),(second,MODEL)],[],authorize_candidate=lambda *a:True,output_tokens=4))
    assert second.calls==0

def test_health_is_readiness_only_and_sanitized():
    adapter=wire('unused')
    assert adapter.health()=={'readiness':'READY','provider_health':'UNMEASURED','network_probe_performed':False}
    def fail(ref):raise ValueError('secret fixture-value')
    adapter.resolve=fail
    assert adapter.health()['readiness']=='CREDENTIAL_UNAVAILABLE'
    with pytest.raises(ProviderFailure,match='CREDENTIAL_UNAVAILABLE') as exc:
        asyncio.run(complete(adapter,MODEL,[],output_tokens=4))
    assert 'fixture-value' not in str(exc.value) and exc.value.pre_execution

def test_malformed_generic_provider_chunk_is_sanitized():
    class Bad:
        async def stream(self,*args):yield {'text':'private raw'}
    with pytest.raises(ProviderFailure,match='MALFORMED_STREAM'):
        asyncio.run(complete(Bad(),MODEL,[],output_tokens=4))


def cloud_fixture(monkeypatch, *, second_rate='1', second_tier='MINI', fail_code='CREDENTIAL_UNAVAILABLE', partial=False):
    from app import cloud_execution as cloud
    from pathlib import Path
    from types import SimpleNamespace
    base={'enabled':True,'qualification_status':'QUALIFIED','location':'cloud','tier':'MINI','context_tokens':4096,'output_tokens':64,
          'input_usd_million':'1','output_usd_million':'1','endpoint':'https://fixture.invalid/chat'}
    entries=[dict(base,id='first',model='first-model',secret_ref='first',fallback_ids=['second']),
             dict(base,id='second',model='second-model',secret_ref='second',input_usd_million=second_rate,tier=second_tier)]
    calls=[];records=[]
    class Adapter:
        def __init__(self,endpoint,ref,**kwargs):self.ref=ref
        async def stream(self,*args):
            calls.append(self.ref)
            if self.ref=='first':
                if partial:yield Chunk(text='partial')
                raise ProviderFailure(fail_code,pre_execution=fail_code=='CREDENTIAL_UNAVAILABLE')
            yield Chunk(text='fixture response',usage=Usage(10,2,0))
            yield Chunk(complete=True)
    class Metrics:
        def __init__(self,*args):pass
        def record(self,**kwargs):records.append(kwargs)
    monkeypatch.setattr(cloud,'load_catalog',lambda:entries)
    monkeypatch.setattr(cloud,'ChatCompletionProvider',Adapter)
    monkeypatch.setattr(cloud,'OutcomeMetrics',Metrics)
    monkeypatch.setattr(cloud,'action_ledger',lambda:None)
    monkeypatch.setattr(cloud.DirectExecutor,'execute',lambda self,record,operation:operation())
    job=dict(id='job',agent='a12',prompt='fixture objective',data_classification='CLOUD_PERMITTED',
             allow_cloud=True,timeout_seconds=5,estimated_cost_usd=.001,max_cost_usd=.001)
    def run():return cloud.execute_cloud(job,SimpleNamespace(name='first'),Path('.'),lambda:False)
    return run,calls,records,job


def test_execute_cloud_explicit_fallback_accounts_actual_provider(monkeypatch):
    run,calls,records,job=cloud_fixture(monkeypatch)
    result=run()
    assert calls==['first','second']
    assert records[-1]['provider']=='second'
    assert set(result)=={'result','input_tokens','output_tokens','actual_cost_usd'}
    assert records[-1]['model']=='second-model' and result['actual_cost_usd'] is not None


@pytest.mark.parametrize('rate,tier',[('10000','MINI'),('1','NANO')])
def test_execute_cloud_fallback_cannot_escape_reserved_budget_or_tier(monkeypatch,rate,tier):
    run,calls,records,job=cloud_fixture(monkeypatch,second_rate=rate,second_tier=tier)
    with pytest.raises(ProviderFailure,match='FALLBACK_POLICY_DENIED'):run()
    assert calls==['first']


@pytest.mark.parametrize('code,partial',[('PROVIDER_TRANSPORT_FAILURE',False),('CREDENTIAL_UNAVAILABLE',True)])
def test_execute_cloud_does_not_replay_ambiguous_work(monkeypatch,code,partial):
    run,calls,records,job=cloud_fixture(monkeypatch,fail_code=code,partial=partial)
    with pytest.raises(ProviderFailure):run()
    assert calls==['first']


def test_execute_cloud_respects_local_only(monkeypatch):
    run,calls,records,job=cloud_fixture(monkeypatch)
    job['data_classification']='LOCAL_ONLY'
    with pytest.raises(ProviderFailure,match='DATA_LOCALITY'):run()
    assert calls==[]


@pytest.mark.parametrize('chunk,code',[(Chunk(text='x'*4_000_001),'STREAM_SIZE_EXCEEDED'),
    (Chunk(usage=Usage(1,5,0)),'OUTPUT_BUDGET_EXHAUSTED')])
def test_stream_cannot_exceed_output_bounds(chunk,code):
    class Excess:
        async def stream(self,*args):yield chunk
    with pytest.raises(ProviderFailure,match=code):
        asyncio.run(complete(Excess(),MODEL,[],output_tokens=4))
