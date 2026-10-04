import asyncio
import json
import sqlite3

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
    with pytest.raises(ValueError):
        load({**entry, 'enabled': True, 'qualification_status': 'QUALIFIED'})
    qualified = {**entry, 'enabled': True, 'qualification_status': 'QUALIFIED',
                 'input_usd_million': '0.1', 'output_usd_million': '0.5'}
    with pytest.raises(ValueError):
        load({**qualified, 'input_usd_million': 'NaN'})
    assert load(qualified)[0]['provider_kind'] == 'huggingface'
    assert isinstance(adapter_for(qualified), HuggingFaceProvider)


def test_qualified_hf_route_flows_through_governed_queue_and_outcome(monkeypatch, tmp_path):
    from app import cloud_execution as cloud
    from app.job_queue import JobQueue, Provider, QueuePolicy
    from app.outcome_metrics import OutcomeMetrics

    entry = {'id': 'hf-fixture', 'provider_kind': 'huggingface', 'enabled': True,
             'qualification_status': 'QUALIFIED', 'location': 'cloud', 'tier': 'MINI',
             'model': MODEL.name, 'endpoint': HuggingFaceProvider.ENDPOINT,
             'secret_ref': 'env:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 64,
             'input_usd_million': '0.1', 'output_usd_million': '0.5'}
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'models': [entry]}))
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG', str(catalog))
    monkeypatch.setenv('HF_TOKEN', 'fixture-secret')
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=stream_response())

    real_adapter = cloud.HuggingFaceProvider
    monkeypatch.setattr(cloud, 'HuggingFaceProvider',
                        lambda ref, secret_resolver: real_adapter(ref, secret_resolver=secret_resolver,
                                                                 transport=httpx.MockTransport(handler)))
    queue = JobQueue(tmp_path / 'queue.db', QueuePolicy(cloud_wait_seconds=0))
    provider = Provider('hf-fixture', 'cloud', MODEL.name, 0, 0, 1, .1, .5, 64)
    submitted = queue.submit(agent='a10', prompt='Count three fixture services',
                             preferred_provider='hf-fixture', allow_cloud=True,
                             data_classification='CLOUD_PERMITTED', max_cost_usd=.01,
                             timeout_seconds=10)
    job = queue.claim('fixture-worker', [provider])
    assert job and job['id'] == submitted['id']
    result = cloud.execute_cloud(job, provider, tmp_path, lambda: False)
    queue.finish(job['id'], **result)
    assert queue.get(job['id'])['status'] == 'completed'
    assert result['result'] == 'three' and len(calls) == 1
    assert json.loads(calls[0].content)['max_tokens'] == 64
    ledger = tmp_path / 'compute-ledger.db'
    assert OutcomeMetrics(ledger).summary('auto')['attempts'] == 1
    with sqlite3.connect(ledger) as db:
        details = json.loads(db.execute('SELECT details FROM reasoning_attempts').fetchone()[0])
    assert details['success'] is True and details['provider'] == 'hf-fixture'
    assert details['model'] == MODEL.name and details['agent_id'] == 'a10'


def test_hf_queue_requires_explicit_selection_before_claim(monkeypatch, tmp_path):
    from app import compute_catalog, compute_queue_api
    from app.job_queue import JobQueue, QueuePolicy

    entry = {'id': 'hf-fixture', 'provider_kind': 'huggingface', 'enabled': True,
             'qualification_status': 'QUALIFIED', 'location': 'cloud', 'tier': 'MINI',
             'model': MODEL.name, 'endpoint': HuggingFaceProvider.ENDPOINT,
             'secret_ref': 'env:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 64,
             'input_usd_million': '0.1', 'output_usd_million': '0.5'}
    monkeypatch.setattr(compute_catalog, 'load_catalog', lambda: [entry])
    monkeypatch.delenv('HF_TOKEN', raising=False)
    provider = next(p for p in compute_queue_api.providers() if p.name == 'hf-fixture')
    assert provider.explicit_selection_required

    queue = JobQueue(tmp_path / 'queue.db', QueuePolicy(cloud_wait_seconds=0))
    for preferred in (None, 'missing-provider'):
        job = queue.submit(agent='a10', prompt='Synthetic cloud task',
                           preferred_provider=preferred, allow_cloud=True,
                           data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
        assert queue.claim('fixture-worker', [provider]) is None
        assert queue.get(job['id'])['status'] == 'queued'

    explicit = queue.submit(agent='a10', prompt='Synthetic HF task',
                            preferred_provider='hf-fixture', allow_cloud=True,
                            data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    claimed = queue.claim('fixture-worker', [provider])
    assert claimed and claimed['id'] == explicit['id']
    assert 'HF_TOKEN' not in json.dumps(claimed)
