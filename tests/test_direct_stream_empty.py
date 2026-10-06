import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app.direct_stream import infer
from tests.backend_receipt_fixture import install as install_backend_receipt


@pytest.mark.parametrize('content,ok',[('',False),('verified fixture',True)])
def test_completion_marker_requires_actual_text(content,ok,monkeypatch,tmp_path):
    import json
    install_backend_receipt(monkeypatch,tmp_path,'http://fixture')
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text=json.dumps({
        'done':True,'message':{'content':content},'prompt_eval_count':2,'eval_count':3})+'\n'))
    client=httpx.AsyncClient(transport=transport)
    with patch('app.direct_stream.httpx.AsyncClient',return_value=client):
        call=infer({'timeout_seconds':5,'prompt':'fixture','ram_mb':1024},SimpleNamespace(model='fixture'),
            settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive=0,context_tokens=128,max_output_tokens=8),capacity=lambda _:None,options=lambda:{})
        if ok:assert asyncio.run(call)['result']==content
        else:
            with pytest.raises(RuntimeError,match='Incomplete or empty'):asyncio.run(call)


@pytest.mark.parametrize('response_format,expected_format', [
    ('text', None), ('strict_json', 'json'),
])
def test_persisted_response_format_reaches_ollama(response_format, expected_format,
                                                  monkeypatch, tmp_path):
    import json
    install_backend_receipt(monkeypatch, tmp_path, 'http://fixture')
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, text=json.dumps({
            'done': True, 'message': {'content': '{"ok":true}'},
            'prompt_eval_count': 2, 'eval_count': 3}) + '\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch('app.direct_stream.httpx.AsyncClient', return_value=client):
        result = asyncio.run(infer({
            'timeout_seconds': 5, 'prompt': 'fixture', 'ram_mb': 1024,
            'response_format': response_format,
        }, SimpleNamespace(model='fixture'), settings=SimpleNamespace(
            ollama_base_url='http://fixture', keep_alive=0,
            context_tokens=128, max_output_tokens=8),
            capacity=lambda _: None, options=lambda: {}))
    assert result['result'] == '{"ok":true}'
    assert payloads[0].get('format') == expected_format


def test_tampered_persisted_response_format_is_rejected_before_http():
    with pytest.raises(PermissionError, match='persisted response format'):
        asyncio.run(infer({'response_format': None}, SimpleNamespace(model='fixture'),
                          settings=SimpleNamespace(ollama_base_url='http://fixture'),
                          capacity=lambda _: None, options=lambda: {}))
