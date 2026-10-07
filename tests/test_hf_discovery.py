"""Anonymous public metadata mocks, never inference or live credentials."""
import asyncio
import copy
import hashlib
import json

import httpx
import pytest

from app.hf_discovery import HFDiscoveryError, discover_hf


MODEL = 'google/gemma-3-4b-it'


def hub(shape='list'):
    fields = {'status': 'live', 'task': 'conversational', 'providerId': MODEL}
    mapping = [{'provider': 'deepinfra', **fields}] if shape == 'list' else {'deepinfra': fields}
    return [{'id': MODEL, 'pipeline_tag': 'image-text-to-text', 'inferenceProviderMapping': mapping}]


def router():
    return {'data': {'id': MODEL, 'providers': [{'provider': 'deepinfra', 'status': 'live',
        'context_length': 131072, 'pricing': {'input': .05, 'output': .10},
        'supports_tools': True, 'supports_structured_output': True,
        'first_token_latency_ms': 308, 'throughput': 36.4}]}}


def call(hub_body=None, router_body=None, *, model=MODEL, handler=None, task='image-text-to-text', limit=5):
    calls = []
    def response(request):
        calls.append(request)
        assert request.method == 'GET'
        assert not request.content
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        if handler:
            return handler(request)
        return httpx.Response(200, json=(hub() if hub_body is None else hub_body)
            if request.url.host == 'huggingface.co' else (router() if router_body is None else router_body))
    value = asyncio.run(discover_hf(task, limit=limit, model_id=model, transport=httpx.MockTransport(response)))
    return value, calls


@pytest.mark.parametrize('shape', ['list', 'object'])
def test_both_observed_mapping_shapes_are_bounded_metadata_not_admission(shape, monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'SYNTHETIC_DO_NOT_USE_ENV_TOKEN')
    value, calls = call(hub(shape))
    assert len(calls) == 2
    assert calls[0].url.params.get('pipeline_tag') == 'image-text-to-text'
    assert calls[0].url.params.get_list('expand') == ['inferenceProviderMapping', 'pipeline_tag']
    assert value['models'][0]['providers'][0]['reported_task'] == 'conversational'
    assert value['models'][0]['providers'][0]['prime_adapter_compatibility'] == 'TEXT_CHAT_SOURCE_ONLY_ADMISSION_REQUIRED'
    assert value['router_model']['providers'][0]['context_length'] == 131072
    assert value['router_model']['reported_input_modalities'] is None
    assert value['inference_requests'] == 0 and value['catalog_changes'] is False
    assert value['health'] == 'UNMEASURED' and value['prime_authorization'] == 'NOT_GRANTED'
    assert not value['provider_selection_documentation']['native_dynamic_inference_enabled']
    assert 'SYNTHETIC_DO_NOT_USE_ENV_TOKEN' not in json.dumps(value)
    original = {key: item for key, item in value.items() if key != 'snapshot_sha256'}
    raw = json.dumps(original, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    assert value['snapshot_sha256'] == hashlib.sha256(raw).hexdigest()
    assert all(not source['authentication_used'] for source in value['sources'])


def test_one_hub_only_request_and_empty_result_is_not_unhealthy():
    value, calls = call([], model=None)
    assert len(calls) == 1 and value['models'] == [] and value['router_model'] is None
    assert value['health'] == 'UNMEASURED' and not value['complete_global_inventory']


@pytest.mark.parametrize('task,limit,model', [('unknown', 5, None), ('conversation', 5, None),
    ('text-generation', True, None), ('text-generation', 0, None), ('text-generation', 11, None),
    ('text-generation', 5, 'https://attacker.invalid/model'), ('text-generation', 5, '../model'),
    ('text-generation', 5, MODEL + ':auto'), ('text-generation', 5, MODEL + '?token=x')])
def test_invalid_task_model_url_and_limits_make_no_request(task, limit, model):
    calls = []
    def response(request):
        calls.append(request)
        raise AssertionError()
    with pytest.raises(HFDiscoveryError):
        asyncio.run(discover_hf(task, limit=limit, model_id=model, transport=httpx.MockTransport(response)))
    assert calls == []


@pytest.mark.parametrize('mutation', [
    lambda value: value.append(copy.deepcopy(value[0])),
    lambda value: value[0].update(id='https://attacker.invalid/model'),
    lambda value: value[0].update(pipeline_tag=True),
    lambda value: value[0]['inferenceProviderMapping'].append(copy.deepcopy(value[0]['inferenceProviderMapping'][0])),
    lambda value: value[0]['inferenceProviderMapping'][0].update(provider='deepinfra?token=secret'),
    lambda value: value[0]['inferenceProviderMapping'][0].update(status='healthy'),
    lambda value: value[0]['inferenceProviderMapping'][0].update(task=False),
    lambda value: value[0]['inferenceProviderMapping'][0].update(providerId='bad\nvalue'),
])
def test_hub_conflicts_malformed_identity_and_unproven_health_do_not_pass(mutation):
    value = hub()
    mutation(value)
    with pytest.raises(HFDiscoveryError):
        call(value)


def test_conflicting_object_provider_identity_denies():
    value = hub('object')
    value[0]['inferenceProviderMapping']['deepinfra']['provider'] = 'different'
    with pytest.raises(HFDiscoveryError):
        call(value)


@pytest.mark.parametrize('field,item', [('context_length', True), ('context_length', 1.5),
    ('context_length', 10000001), ('supports_tools', 'true'), ('supports_structured_output', 1),
    ('throughput', -1), ('throughput', float('nan')), ('first_token_latency_ms', float('inf')),
    ('pricing', {'input': -1}), ('pricing', {'input': True}), ('pricing', {'output': 10 ** 500}),
    ('pricing', 'PRIVATE_UNTRUSTED_BODY')])
def test_known_router_fields_are_literal_typed_finite_and_bounded(field, item):
    value = router()
    value['data']['providers'][0][field] = item
    with pytest.raises(HFDiscoveryError) as error:
        call(router_body=value)
    assert 'PRIVATE_UNTRUSTED_BODY' not in str(error.value)


def test_missing_price_context_or_modalities_stays_unknown_not_zero_or_admitted():
    value = router()
    row = value['data']['providers'][0]
    row.pop('pricing')
    row.pop('context_length')
    projected, _ = call(router_body=value)
    observed = projected['router_model']['providers'][0]
    assert observed['input_usd_million'] is None and observed['output_usd_million'] is None
    assert observed['context_length'] is None and observed['prime_authorization'] == 'NOT_GRANTED'


def test_wrong_router_model_cannot_steal_requested_binding():
    value = router()
    value['data']['id'] = 'other/model'
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_MODEL_BINDING_INVALID'):
        call(router_body=value)


@pytest.mark.parametrize('raw', [b'[{"id":"a/a","id":"a/b"}]', b'{"x":NaN}',
    b'{"x":1e999}', b'[{"x":1,"\\u0078":2}]', b'\xff', b'not json'])
def test_duplicate_decoded_keys_and_malformed_nonfinite_json_fail_closed(raw):
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_JSON_INVALID'):
        call(handler=lambda _: httpx.Response(200, content=raw))


@pytest.mark.parametrize('status', [301, 302, 307, 401, 429, 503])
def test_redirects_and_errors_are_not_followed_or_retried(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={'Location': 'https://attacker.invalid/steal'},
                              text='PRIVATE_ERROR_BODY')
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_HTTP_FAILURE') as error:
        call(handler=handler)
    assert len(calls) == 1 and 'PRIVATE_ERROR_BODY' not in str(error.value)


def test_response_limit_is_checked_before_decode():
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_RESPONSE_TOO_LARGE'):
        call(handler=lambda _: httpx.Response(200, content=b' ' * 98305))


def test_single_absolute_deadline_bounds_complete_operation(monkeypatch):
    monkeypatch.setattr('app.hf_discovery.DEADLINE_SECONDS', .01)
    calls = []
    async def slow(request):
        calls.append(request)
        await asyncio.sleep(.1)
        return httpx.Response(200, json=hub())
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_TIMEOUT'):
        asyncio.run(discover_hf('text-generation', transport=httpx.MockTransport(slow)))
    assert len(calls) == 1


def test_transport_exception_details_are_not_exported():
    def fail(request):
        raise httpx.ConnectError('PRIVATE_EXCEPTION', request=request)
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_TRANSPORT_UNAVAILABLE') as error:
        call(handler=fail)
    assert 'PRIVATE_EXCEPTION' not in str(error.value)


def test_unknown_extra_metadata_is_not_exported_as_facts_or_execution():
    value = hub()
    value[0]['token'] = 'PRIVATE_UPSTREAM_FIELD'
    value[0]['inferenceProviderMapping'][0]['qualified'] = True
    metadata = router()
    metadata['data']['private'] = 'PRIVATE_UPSTREAM_FIELD'
    result, _ = call(value, metadata)
    assert 'PRIVATE_UPSTREAM_FIELD' not in json.dumps(result)
    assert result['models'][0]['providers'][0]['prime_qualification'] == 'UNMEASURED'


def test_upstream_cookie_is_not_reused_on_router_sibling_domain():
    calls = []
    def response(request):
        calls.append(request)
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        assert request.headers['accept-encoding'] == 'identity'
        if request.url.host == 'huggingface.co':
            return httpx.Response(200, json=hub(),
                headers={'Set-Cookie': 'metadata-session=synthetic; Domain=.huggingface.co; Path=/'})
        return httpx.Response(200, json=router())
    value = asyncio.run(discover_hf('text-generation', model_id=MODEL, transport=httpx.MockTransport(response)))
    assert len(calls) == 2 and all(not source['authentication_used'] for source in value['sources'])


def test_compressed_response_cannot_expand_beyond_bounded_decoding_boundary():
    import gzip
    with pytest.raises(HFDiscoveryError, match='HF_DISCOVERY_COMPRESSED_RESPONSE_DENIED'):
        call(handler=lambda _: httpx.Response(200, content=gzip.compress(b' ' * 100000),
                                             headers={'Content-Encoding': 'gzip'}))
