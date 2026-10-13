import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app.direct_stream import infer


@pytest.mark.parametrize('content,ok', [('{"ok":true}',True),
    ('```json\n{"ok":true}\n```',False), ('[]',False),
    ('{"ok":true,"ok":false}',False), ('{"value":NaN}',False),
    ('{"value":1e400}',False), ('not json',False),
    pytest.param('{"nested":' + '[' * 20000 + '0' + ']' * 20000 + '}',False, id='nested-recursion')])
def test_strict_json_is_requested_and_invalid_outputs_are_not_completed(content,ok,monkeypatch,tmp_path):
    import json
    for name in ('PRIME_LOCAL_ADMISSION_MODE','PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE','PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    requests=[]
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,text=json.dumps({'done':True,'message':{'content':content}})+'\n')
    client=httpx.AsyncClient(transport=httpx.MockTransport(reply))
    with patch('app.direct_stream.httpx.AsyncClient',return_value=client):
        call=infer({'timeout_seconds':5,'prompt':'fixture','ram_mb':1024,'response_format':'strict_json'},
            SimpleNamespace(model='gemma3:1b'),settings=SimpleNamespace(ollama_base_url='http://fixture',
            keep_alive=0,context_tokens=128,max_output_tokens=8),capacity=lambda _:None,options=lambda:{})
        result=asyncio.run(call)
        assert result['result']==content
        if ok:
            assert 'error' not in result
        else:
            assert result['error']=='STRICT_JSON_CONTRACT_FAILED'
            assert result['retryable'] is False
    assert len(requests)==1 and requests[0]['format']=='json'


@pytest.mark.parametrize('content,ok',[('',False),('verified fixture',True)])
def test_completion_marker_requires_actual_text(content,ok,monkeypatch,tmp_path):
    import json
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE', 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    def reply(request):
        assert 'format' not in json.loads(request.content)
        return httpx.Response(200,text=json.dumps({
            'done':True,'message':{'content':content},'prompt_eval_count':2,'eval_count':3})+'\n')
    transport=httpx.MockTransport(reply)
    client=httpx.AsyncClient(transport=transport)
    with patch('app.direct_stream.httpx.AsyncClient',return_value=client):
        call=infer({'timeout_seconds':5,'prompt':'fixture','ram_mb':1024},SimpleNamespace(model='gemma3:1b'),
            settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive=0,context_tokens=128,max_output_tokens=8),capacity=lambda _:None,options=lambda:{})
        if ok:assert asyncio.run(call)['result']==content
        else:
            with pytest.raises(RuntimeError,match='Incomplete or empty'):asyncio.run(call)


def test_golden_direct_stream_rejects_unobserved_model(monkeypatch,tmp_path):
    for name in ('PRIME_BACKEND_MEMORY_RECEIPT', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_LOCAL_ADMISSION_MODE', 'golden_n1')
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    with patch('app.direct_stream.httpx.AsyncClient', side_effect=AssertionError('backend contacted')):
        with pytest.raises(PermissionError,match='requires measured'):
            asyncio.run(infer({'timeout_seconds':5,'prompt':'fixture','ram_mb':1024},
                              SimpleNamespace(model='qwen3:14b'),
                              settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive=0,
                                                       context_tokens=128,max_output_tokens=8),
                              capacity=lambda _:None,options=lambda:{}))


@pytest.mark.parametrize('response_format,configured,expected', [
    ('strict_json', {}, {'temperature': 0}),
    ('strict_json', {'temperature': .35, 'top_p': .9}, {'temperature': .35, 'top_p': .9}),
    ('text', {}, {}),
    ('text', {'temperature': .7}, {'temperature': .7}),
])
def test_structured_generation_respects_configured_options(response_format,configured,expected,monkeypatch,tmp_path):
    import json
    for name in ('PRIME_LOCAL_ADMISSION_MODE','PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE','PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    before=dict(configured);requests=[]
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,text=json.dumps({'done':True,'message':{'content':'{"ok":true}'}})+'\n')
    client=httpx.AsyncClient(transport=httpx.MockTransport(reply))
    with patch('app.direct_stream.httpx.AsyncClient',return_value=client):
        result=asyncio.run(infer({'timeout_seconds':5,'prompt':'fixture','ram_mb':1024,
            'response_format':response_format},SimpleNamespace(model='gemma3:1b'),
            settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive=0,
                context_tokens=128,max_output_tokens=8),capacity=lambda _:None,options=lambda:configured))
    assert result['result']=='{"ok":true}'
    assert len(requests)==1
    assert requests[0]['options']=={'num_ctx':128,'num_predict':8,**expected}
    assert configured==before
    assert (requests[0].get('format')=='json') is (response_format=='strict_json')
