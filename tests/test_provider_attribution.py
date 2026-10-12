"""Wire fixtures prove source behavior only; these are not live/billing receipts."""
import asyncio,json,sqlite3
import httpx,pytest
from app.provider_runtime import ChatCompletionProvider,complete,ProviderFailure
from app.outcome_metrics import OutcomeMetrics
from tests.test_provider_runtime import MODEL,stream_response
from tests.test_objective_inference_evidence import evidence
from app import objective_api

def run(body,headers=None):
    provider=ChatCompletionProvider('https://fixture.invalid/v1/chat/completions','env:FIXTURE',
        secret_resolver=lambda ref:'fixture-only',transport=httpx.MockTransport(lambda _:httpx.Response(200,text=body,headers=headers)))
    return asyncio.run(complete(provider,MODEL,[],output_tokens=16,max_retries=0))

def with_metadata(body,response_id='chatcmpl_fixture',model='reported-model'):
    return ''.join('data: '+json.dumps({**json.loads(line[6:]),'id':response_id,'model':model})+'\n\n'
        if line.startswith('data: {') else line+'\n' for line in body.splitlines())

def test_provider_trace_and_usage_have_distinct_billing_truth():
    result=run(with_metadata(stream_response()),{'x-request-id':'req_fixture'})
    assert result['provider_trace']=={'request_id':'req_fixture','response_id':'chatcmpl_fixture','reported_model':'reported-model'}
    assert result['cost_basis']=='provider_usage_x_catalog_rates'
    assert result['billing_status']=='unreconciled'
    assert 'fixture-only' not in str(result)

def test_missing_metadata_and_usage_stay_unknown():
    result=run(stream_response(usage=False))
    assert result['provider_trace']==dict(request_id=None,response_id=None,reported_model=None)
    assert result['cost_usd'] is None and result['cost_basis']=='unknown'

@pytest.mark.parametrize('value',['sk-sensitive','Bearersecret','bad id','x'*201])
def test_bad_header_is_not_logged(value):
    with pytest.raises(ProviderFailure,match='INVALID_PROVIDER_TRACE') as e:run(stream_response(),{'x-request-id':value})
    assert value not in str(e.value)

def test_changed_response_identity_denies_ambiguous_stream():
    body=with_metadata(stream_response()).replace('chatcmpl_fixture','chatcmpl_other',1)
    with pytest.raises(ProviderFailure,match='PROVIDER_TRACE_CHANGED'):run(body)

def test_ledger_retains_task_agent_tokens_and_trace_without_claiming_verification(tmp_path):
    path=tmp_path/'ledger.db';m=OutcomeMetrics(path)
    m.record(attempt_id='attempt',task_id='task',task_class='reasoning',tier='MINI',seconds=.1,
        input_tokens=10,output_tokens=2,cost=.000028,agent_id='a18',provider='openai-route',model='requested-model',
        provider_request_id='req_fixture',provider_response_id='chatcmpl_fixture',reported_model='reported-model',
        cost_basis='provider_usage_x_catalog_rates',billing_status='unreconciled',success=True)
    with sqlite3.connect(path) as c:row=c.execute('select task_id,tokens,cost,verified,details from reasoning_attempts').fetchone()
    assert row[:4]==('task',12,.000028,0)
    assert json.loads(row[4])['provider_request_id']=='req_fixture'

def attach_attribution(evidence,**changes):
    detail={**evidence['detail'],'provider_request_id':'req_fixture','provider_response_id':'chatcmpl_fixture',
        'reported_model':'provider-resolved-model','input_tokens':5,'output_tokens':3,
        'cost_basis':'provider_usage_x_catalog_rates','billing_status':'unreconciled',**changes}
    with sqlite3.connect(evidence['path']) as c:c.execute('update reasoning_attempts set details=?',(json.dumps(detail),))

def test_owned_objective_projection_exports_safe_attribution(evidence):
    attach_attribution(evidence)
    result=objective_api.inference_attempt_projection([evidence['job']])
    assert result['status']=='OBSERVED' and result['verification']=='UNVERIFIED'
    attempt=result['attempts'][0]
    assert attempt['provider_request_id']=='req_fixture' and attempt['input_tokens']==5
    assert attempt['reported_model']=='provider-resolved-model' and attempt['selected_model']=='organization/alternate:provider'
    assert attempt['billing_status']=='unreconciled'

@pytest.mark.parametrize('change',[{'provider_request_id':'sk-never-export-this'},
    {'input_tokens':4},{'billing_status':'verified'},{'cost_basis':'billed'},
    {'reported_model':'Bearer never-export-this'},{'input_tokens':None}])
def test_bad_ledger_attribution_is_rejected_without_export(evidence,change):
    attach_attribution(evidence,**change)
    result=objective_api.inference_attempt_projection([evidence['job']])
    assert result['status']=='INVALID' and not result['attempts']
    assert 'never-export-this' not in json.dumps(result)
