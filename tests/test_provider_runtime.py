import asyncio,json
from decimal import Decimal
import httpx
import pytest
from app.provider_runtime import ModelSpec,Usage,ChatCompletionProvider,complete,ProviderFailure
from app.compute_catalog import task_tier,choose,bounded_list_task
from app.tier_router import Tier
from app.secret_refs import resolve_secret,SecretUnavailable
from app.outcome_metrics import OutcomeMetrics

MODEL=ModelSpec('fixture-model','fixture','MINI',8192,128,Decimal('2'),Decimal('4'))
def stream_response(text='ok',usage=True,finished=True):
    values=[{'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]}]
    if finished:values.append({'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})
    if usage:values.append({'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':2}})
    return ''.join('data: '+json.dumps(x)+'\n\n' for x in values)+'data: [DONE]\n\n'
def adapter(handler):return ChatCompletionProvider('https://fixture.invalid/v1/chat/completions','env:FIXTURE_KEY',secret_resolver=lambda ref:'fixture-only',transport=httpx.MockTransport(handler))
def test_stream_usage_and_no_secret_leak():
    observed=[]
    def handler(req):
        observed.append(json.loads(req.content));return httpx.Response(200,text=stream_response())
    result=asyncio.run(complete(adapter(handler),MODEL,[{'role':'user','content':'hello'}],output_tokens=16))
    assert result['text']=='ok' and result['usage']==Usage(10,2,0) and result['cost_usd']==Decimal('0.000028')
    assert 'fixture-only' not in str(result) and observed[0]['store'] is False
@pytest.mark.parametrize('body,code',[(stream_response('',True),'EMPTY_OR_INCOMPLETE_RESPONSE'),(stream_response('ok',True,False),'INCOMPLETE_STREAM'),('data: invalid\n\n','MALFORMED_STREAM')])
def test_bad_stream(body,code):
    with pytest.raises(ProviderFailure,match=code):asyncio.run(complete(adapter(lambda r:httpx.Response(200,text=body)),MODEL,[],output_tokens=16))
def test_missing_usage_is_unknown():
    r=asyncio.run(complete(adapter(lambda r:httpx.Response(200,text=stream_response(usage=False))),MODEL,[],output_tokens=16))
    assert r['cost_usd'] is None and r['usage'].input_tokens is None
def test_auth_error_sanitized_no_retry():
    calls=[]
    def handler(req):calls.append(1);return httpx.Response(401,text='secret fixture-only raw upstream error')
    with pytest.raises(ProviderFailure,match='AUTHENTICATION') as error:asyncio.run(complete(adapter(handler),MODEL,[],output_tokens=16))
    assert 'fixture-only' not in str(error.value) and len(calls)==1
def test_rate_limit_bounded_retry():
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls)==1 else httpx.Response(200,text=stream_response())
    r=asyncio.run(complete(adapter(handler),MODEL,[],output_tokens=16));assert r['retries']==1 and len(calls)==2
def test_quiet_stream_cancelled():
    class Quiet:
        async def stream(self,*args):
            await asyncio.sleep(10)
            yield None
    with pytest.raises(ProviderFailure,match='CANCELLED'):asyncio.run(complete(Quiet(),MODEL,[],output_tokens=16,cancelled=lambda:True))
def test_context_and_output_budget():
    with pytest.raises(ProviderFailure,match='CONTEXT_BUDGET'):asyncio.run(complete(None,MODEL,[{'content':'a'*9000}],output_tokens=16))
    with pytest.raises(ProviderFailure,match='OUTPUT_BUDGET'):asyncio.run(complete(None,MODEL,[],output_tokens=129))
def test_secret_reference(monkeypatch):
    monkeypatch.setenv('FIXTURE_KEY','fixture-only');assert resolve_secret('env:FIXTURE_KEY')=='fixture-only'
    with pytest.raises(SecretUnavailable):resolve_secret('literal-api-key')
def test_failed_nano_classes_require_sufficient_tier():
    assert task_tier('fix an unfamiliar repository')==Tier.FLAGSHIP
    assert task_tier('ordinary conversation')==Tier.MINI
    assert task_tier('classify these labels')==Tier.NANO
    cloud={'id':'x','tier':'FLAGSHIP','enabled':True,'location':'cloud'}
    assert choose([cloud],Tier.MINI,'LOCAL_ONLY','hello')==[]
def test_explicitly_bounded_short_lists_are_nano_without_lowering_complex_work():
    chinese='请用中文创建一份包含五项的家庭出行准备清单，并将结果保存为 Markdown 文件。'
    assert bounded_list_task(chinese)
    assert task_tier(chinese)==Tier.NANO
    assert task_tier('Create a five item release checklist')==Tier.NANO
    assert task_tier('Create a threat model with five items')==Tier.MINI
    assert not bounded_list_task('Create a general travel checklist')
def test_verified_outcome_economics(tmp_path):
    metrics=OutcomeMetrics(tmp_path/'compute-ledger.db')
    metrics.record(attempt_id='1',task_id='t',task_class='coding',tier='NANO',seconds=3,input_tokens=10,output_tokens=2,cost=.1,success=False)
    metrics.record(attempt_id='2',task_id='t',task_class='coding',tier='FLAGSHIP',seconds=5,input_tokens=20,output_tokens=4,cost=.2,verified=True,success=True,artifact_id='a',artifact_validation='PASS')
    r=metrics.summary('coding');assert r['verified_outcomes']==1 and r['tokens_per_verified_outcome']==36 and r['seconds_per_verified_outcome']==8
    with pytest.raises(ValueError):metrics.record(attempt_id='3',task_id='t',task_class='coding',tier='NANO',seconds=1,verified=True)
