import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app.direct_stream import infer


@pytest.mark.parametrize('content,ok',[('',False),('verified fixture',True)])
def test_completion_marker_requires_actual_text(content,ok):
    import json
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text=json.dumps({
        'done':True,'message':{'content':content},'prompt_eval_count':2,'eval_count':3})+'\n'))
    client=httpx.AsyncClient(transport=transport)
    with patch('app.direct_stream.httpx.AsyncClient',return_value=client):
        call=infer({'timeout_seconds':5,'prompt':'fixture'},SimpleNamespace(model='fixture'),
            settings=SimpleNamespace(ollama_base_url='http://fixture',keep_alive=0,context_tokens=128,max_output_tokens=8),capacity=lambda _:None,options=lambda:{})
        if ok:assert asyncio.run(call)['result']==content
        else:
            with pytest.raises(RuntimeError,match='Incomplete or empty'):asyncio.run(call)
