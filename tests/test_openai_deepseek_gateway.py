"""Nonbillable contract fixtures; these tests never contact model providers."""
import asyncio
import json
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from app.provider_runtime import ModelSpec,Usage,ProviderFailure,complete,complete_with_fallback
from app.openai_deepseek_providers import OpenAIResponsesProvider,DeepSeekChatProvider
from app.compute_catalog import load_catalog
from app.cloud_execution import adapter_for,require_text_admission
from app.job_queue import JobQueue,QueuePolicy
from app.outcome_metrics import OutcomeMetrics
from app.provider_usage import usage_projection

MODEL=ModelSpec('explicit-fixture-model','fixture','MINI',8192,128,Decimal('2'),Decimal('4'),Decimal('1'))


def sse(*events,done=False):
    return ''.join('data: '+json.dumps(x)+'\n\n' for x in events)+('data: [DONE]\n\n' if done else '')


def responses(text='answer',usage=True):
    final={'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}]}
    if usage:final['usage']={'input_tokens':10,'output_tokens':2,'input_tokens_details':{'cached_tokens':4}}
    return sse({'type':'response.output_text.delta','delta':text},{'type':'response.completed','response':final})


def chat():
    return sse({'choices':[{'index':0,'delta':{'content':'answer'},'finish_reason':None}]},
               {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':10,'completion_tokens':2,'prompt_cache_hit_tokens':4}},done=True)


@pytest.mark.parametrize('cls,body',[(OpenAIResponsesProvider,responses()),(DeepSeekChatProvider,chat())])
def test_pinned_wire_usage_and_isolated_credentials(cls,body):
    requests=[]
    def handler(req):
        requests.append(req)
        return httpx.Response(200,text=body)
    provider=cls(secret_resolver=lambda ref:'fixture-secret',transport=httpx.MockTransport(handler))
    result=asyncio.run(complete(provider,MODEL,[{'role':'user','content':'public fixture'}],output_tokens=16,max_retries=0))
    assert result['text']=='answer' and result['usage']==Usage(10,2,4)
    assert result['cost_usd']==Decimal('0.000024')
    assert 'fixture-secret' not in str(result)
    assert str(requests[0].url)==cls.ENDPOINT
    body=json.loads(requests[0].content)
    if cls is OpenAIResponsesProvider:
        assert body['max_output_tokens']==16 and body['store'] is False and 'input' in body
        assert 'max_tokens' not in body
    else:
        assert body['max_tokens']==16 and 'messages' in body
        assert 'store' not in body and 'max_completion_tokens' not in body


def test_responses_missing_usage_stays_unknown():
    provider=OpenAIResponsesProvider(secret_resolver=lambda _: 'fixture',transport=httpx.MockTransport(lambda _:httpx.Response(200,text=responses(usage=False))))
    result=asyncio.run(complete(provider,MODEL,[],output_tokens=16,max_retries=0))
    assert result['cost_usd'] is None and result['usage'].input_tokens is None


@pytest.mark.parametrize('event,code',[
    ({'type':'response.incomplete'},'OUTPUT_BUDGET_EXHAUSTED'),
    ({'type':'response.failed'},'PROVIDER_STREAM_FAILURE'),
    ({'type':'response.completed','response':{'status':'completed','output':[],'error':{'code':'fault'}}},'PROVIDER_STREAM_FAILURE'),
    ({'type':'response.output_item.added','item':{'type':'function_call'}},'UNSUPPORTED_COMPLETION'),
    ({'type':'response.completed','response':{'status':'completed','output':[],'usage':{'input_tokens':2,'output_tokens':True}}},'INVALID_USAGE'),
    ({'type':'response.completed','response':{'status':'failed','output':[]}},'MALFORMED_STREAM'),
    ({'type':'unexpected'},'UNSUPPORTED_STREAM_EVENT'),
])
def test_responses_admitted_failures_never_replayed(event,code):
    calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,text=sse(event))
    provider=OpenAIResponsesProvider(secret_resolver=lambda _: 'fixture',transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure,match=code):
        asyncio.run(complete(provider,MODEL,[],output_tokens=16,max_retries=2))
    assert len(calls)==1


@pytest.mark.parametrize('cls',[OpenAIResponsesProvider,DeepSeekChatProvider])
@pytest.mark.parametrize('status,code',[(401,'AUTHENTICATION'),(402,'INSUFFICIENT_BALANCE'),(500,'PROVIDER_HTTP_FAILURE')])
def test_errors_do_not_leak_or_replay(cls,status,code):
    calls=[]
    def handler(req):calls.append(req);return httpx.Response(status,text='raw fixture-secret')
    provider=cls(secret_resolver=lambda _: 'fixture-secret',transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure,match=code) as error:
        asyncio.run(complete(provider,MODEL,[],output_tokens=16,max_retries=2))
    assert 'fixture-secret' not in str(error.value) and len(calls)==1


def test_explicit_authorized_fallback_preserves_ambiguous_execution_boundary():
    primary=OpenAIResponsesProvider(secret_resolver=lambda _:None)
    requests=[]
    target=DeepSeekChatProvider(secret_resolver=lambda _:'fixture',transport=httpx.MockTransport(lambda req:requests.append(req) or httpx.Response(200,text=chat())))
    result=asyncio.run(complete_with_fallback([(primary,MODEL),(target,MODEL)],[],authorize_candidate=lambda *args:True,output_tokens=16,max_retries=0))
    assert result['fallback_failures']==[{'provider':'fixture','code':'CREDENTIAL_UNAVAILABLE'}] and len(requests)==1


def test_partial_openai_stream_cannot_fall_back_to_deepseek():
    target_calls=[]
    primary=OpenAIResponsesProvider(secret_resolver=lambda _:'fixture',transport=httpx.MockTransport(
        lambda _:httpx.Response(200,text=sse({'type':'response.output_text.delta','delta':'partial'}, {'type':'response.failed'}))))
    target=DeepSeekChatProvider(secret_resolver=lambda _:'fixture',transport=httpx.MockTransport(
        lambda request:target_calls.append(request) or httpx.Response(200,text=chat())))
    with pytest.raises(ProviderFailure,match='PROVIDER_STREAM_FAILURE') as error:
        asyncio.run(complete_with_fallback([(primary,MODEL),(target,MODEL)],[],authorize_candidate=lambda *args:True,output_tokens=16,max_retries=2))
    assert not target_calls and error.value.pre_execution is False


@pytest.mark.parametrize('cls',[OpenAIResponsesProvider,DeepSeekChatProvider])
def test_provider_redirect_cannot_disclose_credential_to_another_host(cls):
    calls=[]
    def handler(request):calls.append(str(request.url));return httpx.Response(302,headers={'Location':'https://untrusted.invalid/'})
    provider=cls(secret_resolver=lambda _:'fixture',transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure,match='PROVIDER_HTTP_FAILURE'):
        asyncio.run(complete(provider,MODEL,[],output_tokens=16,max_retries=2))
    assert calls==[cls.ENDPOINT]


def configured_entry(cls):
    domain='https://developers.openai.com/api/docs/models/' if cls is OpenAIResponsesProvider else 'https://api-docs.deepseek.com/quick_start/pricing/'
    return {'id':'explicit-fixture','provider_kind':'openai_responses' if cls is OpenAIResponsesProvider else 'deepseek_chat',
            'tier':'MINI','location':'cloud','model':'explicit-fixture-model','endpoint':cls.ENDPOINT,
            'secret_ref':cls.SECRET_REF,'enabled':True,'qualification_status':'QUALIFIED',
            'capabilities':['text_generation'],'context_tokens':8192,'output_tokens':128,
            'input_usd_million':'2','output_usd_million':'4',
            'rate_evidence':{'source_url':domain,'verified_at':'2026-10-01T00:00:00Z'},
            'capability_evidence':{'source_url':domain,'verified_at':'2026-10-01T00:00:00Z'}}


@pytest.mark.parametrize('cls',[OpenAIResponsesProvider,DeepSeekChatProvider])
def test_catalog_enforces_provider_capabilities_rates_and_credential_scope(cls,tmp_path):
    entry=configured_entry(cls);path=tmp_path/'catalog.json'
    path.write_text(json.dumps({'models':[entry]}));assert len(load_catalog(path))==1
    for field,value in [('secret_ref','env:HF_TOKEN'),('endpoint','https://fixture.invalid/'),
                        ('capabilities',['tools']),('rate_evidence',None),('capability_evidence',None),
                        ('qualification_status','UNVERIFIED'),('input_usd_million',None)]:
        path.write_text(json.dumps({'models':[{**entry,field:value}]}))
        with pytest.raises(ValueError):load_catalog(path)
    with pytest.raises(ValueError):adapter_for({**entry,'secret_ref':'env:OTHER_PROVIDER_KEY'})
    for job in ({'response_format':'strict_json'},{'model_role':'embedding'}):
        with pytest.raises(ProviderFailure,match='UNSUPPORTED_CAPABILITY'):require_text_admission(entry,job)


def test_queue_idempotency_persists_and_conflicting_payload_rejected(tmp_path):
    path=tmp_path/'queue.db';queue=JobQueue(path)
    request={'agent':'a17','prompt':'public fixture','idempotency_key':'fixture-id-1'}
    first=queue.submit(**request)
    assert JobQueue(path).submit(**request)['id']==first['id']
    with pytest.raises(ValueError,match='conflicts'):queue.submit(**{**request,'prompt':'changed fixture'})
    assert len(queue.list())==1
    assert queue.submit(**{**request,'agent':'a18'})['id']!=first['id']


def test_concurrent_duplicate_submission_is_one_durable_job(tmp_path):
    path=tmp_path/'queue.db';queues=[JobQueue(path),JobQueue(path)]
    def submit(index):return queues[index%2].submit(agent='a17',prompt='public fixture',idempotency_key='concurrent-key')['id']
    with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(submit,range(12)))
    assert len(set(ids))==1 and len(queues[0].list())==1


def test_usage_projection_is_21_scoped_read_only_and_unknown_safe(tmp_path):
    path=tmp_path/'missing.db';policy=QueuePolicy()
    empty=usage_projection(path,policy,evidence_scope='MOCK_CONTRACT_FIXTURES')
    assert not path.exists() and len(empty['agents'])==21
    assert all(x['tokens'] is None and x['provider_balance_usd'] is None for x in empty['agents'])
    metrics=OutcomeMetrics(path)
    metrics.record(attempt_id='fixture-1',task_id='fixture-task',task_class='conversation',tier='MINI',seconds=1,input_tokens=10,output_tokens=2,cost=.000024,agent_id='a17',provider='fixture-route',success=True)
    report=usage_projection(path,policy,evidence_scope='MOCK_CONTRACT_FIXTURES')
    row=next(x for x in report['agents'] if x['agent']=='a17')
    assert row['tokens']==12 and row['estimated_cost_usd']==.000024 and row['balance_state']=='UNKNOWN'
    metrics.record(attempt_id='fixture-2',task_id='fixture-task-2',task_class='conversation',tier='MINI',seconds=1,agent_id='a17',provider='fixture-route',success=False)
    report=usage_projection(path,policy,evidence_scope='MOCK_CONTRACT_FIXTURES')
    row=next(x for x in report['agents'] if x['agent']=='a17')
    assert row['tokens'] is None and row['estimated_cost_usd'] is None
    assert row['missing_usage_attempts']==1 and row['quota']['allocation_state']=='NOT_CONFIGURED'
    assert report['billing_verified'] is False and report['provider_probe_performed'] is False


def test_usage_route_requires_existing_auth_and_never_probes_providers(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import compute_queue_api as api
    monkeypatch.setenv('PRIME_SPINE_TOKEN','fixture-owner')
    monkeypatch.setattr(api,'DATA',tmp_path)
    app=FastAPI();app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get('/api/compute-queue/providers/usage').status_code==401
        response=client.get('/api/compute-queue/providers/usage',headers={'Authorization':'Bearer fixture-owner'})
    assert response.status_code==200 and len(response.json()['agents'])==21
    assert not (tmp_path/'compute-ledger.db').exists()
    assert 'fixture-owner' not in response.text and response.json()['provider_probe_performed'] is False
