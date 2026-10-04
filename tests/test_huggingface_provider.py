import asyncio
import json

import httpx
import pytest

from app.cloud_execution import adapter_for
from app.compute_catalog import load_catalog
from app.provider_runtime import HuggingFaceProvider, ModelSpec, ProviderFailure, complete


MODEL = ModelSpec('openai/gpt-oss-20b:groq', 'hf-chat-candidate', 'MINI', 4096, 64)


def stream_response():
    events = [
        {'choices': [{'index': 0, 'delta': {'content': 'three'}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
        {'choices': [], 'usage': {'prompt_tokens': 8, 'completion_tokens': 1}},
    ]
    return ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'


def test_huggingface_wire_uses_pinned_route_and_documented_payload():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, text=stream_response())

    provider = HuggingFaceProvider(secret_resolver=lambda _: 'fixture-secret', transport=httpx.MockTransport(handler))
    result = asyncio.run(complete(provider, MODEL, [{'role': 'user', 'content': 'Count three services'}], output_tokens=16))
    assert result['text'] == 'three' and result['usage'].input_tokens == 8
    request = observed[0]
    body = json.loads(request.content)
    assert str(request.url) == HuggingFaceProvider.ENDPOINT
    assert body == {'model': MODEL.name, 'messages': [{'role': 'user', 'content': 'Count three services'}],
                    'stream': True, 'stream_options': {'include_usage': True}, 'max_tokens': 16}
    assert request.headers['Authorization'] == 'Bearer fixture-secret'
    assert 'fixture-secret' not in str(result)


def test_huggingface_rejects_unpinned_model_before_network():
    calls = []
    provider = HuggingFaceProvider(secret_resolver=lambda _: 'fixture-secret',
                                   transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)))
    unpinned = ModelSpec('openai/gpt-oss-20b', 'candidate', 'MINI', 4096, 64)
    with pytest.raises(ProviderFailure, match='MODEL_PROVIDER_UNPINNED'):
        asyncio.run(complete(provider, unpinned, [{'role': 'user', 'content': 'hello'}], output_tokens=16))
    assert calls == []


def test_huggingface_missing_token_is_local_readiness_not_network_health():
    provider = HuggingFaceProvider(secret_resolver=lambda _: None)
    assert provider.health() == {'readiness': 'CREDENTIAL_UNAVAILABLE', 'provider_health': 'UNMEASURED',
                                 'network_probe_performed': False}
    with pytest.raises(ProviderFailure, match='CREDENTIAL_UNAVAILABLE'):
        asyncio.run(complete(provider, MODEL, [{'role': 'user', 'content': 'hello'}], output_tokens=16))


def test_catalog_requires_fixed_endpoint_token_pin_and_qualification(tmp_path):
    path = tmp_path / 'catalog.json'
    entry = {'id': 'hf-test', 'provider_kind': 'huggingface', 'enabled': False,
             'qualification_status': 'UNMEASURED', 'location': 'cloud', 'tier': 'MINI',
             'model': MODEL.name, 'endpoint': HuggingFaceProvider.ENDPOINT,
             'secret_ref': 'env:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 64}

    def load(value):
        path.write_text(json.dumps({'models': [value]}))
        return load_catalog(path)

    assert load(entry)[0]['enabled'] is False
    for change in ({'enabled': True}, {'endpoint': 'https://other.invalid/chat'},
                   {'secret_ref': 'env:OTHER_TOKEN'}, {'model': 'openai/gpt-oss-20b'}):
        with pytest.raises(ValueError):
            load({**entry, **change})
    qualified = {**entry, 'enabled': True, 'qualification_status': 'QUALIFIED'}
    assert load(qualified)[0]['provider_kind'] == 'huggingface'
    assert isinstance(adapter_for(qualified), HuggingFaceProvider)
