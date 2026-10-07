import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app.direct_stream import infer


@pytest.mark.parametrize('content,ok',[('',False),('verified fixture',True)])
def test_completion_marker_requires_actual_text(content,ok,monkeypatch,tmp_path):
    import json
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_BACKEND_MEMORY_RECEIPT',
                 'PRIME_MEASURED_COMPUTE_PROFILE', 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256',
                 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB',str(tmp_path/'queue.db'))
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text=json.dumps({
        'done':True,'message':{'content':content},'prompt_eval_count':2,'eval_count':3})+'\n'))
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
