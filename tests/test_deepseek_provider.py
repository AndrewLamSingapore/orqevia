"""Injected synthetic wire checks; no live credentials, socket or provider call."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import json

import httpx
import pytest

from app.deepseek_provider import DeepSeekProvider, ENDPOINT, SECRET_REF
from app.provider_runtime import Chunk, ModelSpec, ProviderFailure, Usage, complete, complete_with_fallback


MODEL = ModelSpec('deepseek-flash', 'deepseek-fixture', 'MINI', 4096, 128,
                 Decimal('2'), Decimal('4'), Decimal('.5'))
MESSAGES = [{'role': 'user', 'content': 'Synthetic public question'}]
TOKEN = 'SYNTHETIC_TEST_TOKEN_NOT_REAL'


def item(delta=None, reason=None, usage=None):
    return {'id': 'test-stream-identity', 'model': MODEL.name,
            'choices': [{'index': 0, 'delta': {'content': 'ok'} if delta is None else delta,
                         'finish_reason': reason}], 'usage': usage}


def usage():
    return {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
            'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 6,
            'prompt_tokens_details': {'cached_tokens': 4},
            'completion_tokens_details': {'reasoning_tokens': 0}}


def sse(*values, done=True):
    result = ''.join('data: ' + (value if type(value) is str else json.dumps(value)) + '\n\n'
                     for value in values)
    return result + ('data: [DONE]\n\n' if done else '')


def success():
    return sse(item(), item({}, 'stop', usage()))


def provider(handler, resolves=None):
    def resolve(reference):
        assert reference == SECRET_REF
        if resolves is not None:
            resolves.append(reference)
        return TOKEN
    return DeepSeekProvider(secret_resolver=resolve, transport=httpx.MockTransport(handler))


def response(raw):
    return httpx.Response(200, text=raw, headers={'Content-Type': 'text/event-stream'})


def run(adapter, **kwargs):
    return asyncio.run(complete(adapter, MODEL, MESSAGES, output_tokens=16, max_retries=0, **kwargs))


@pytest.mark.parametrize('endpoint', ['http://api.deepseek.com/chat/completions',
    ENDPOINT + '?token=bad', ENDPOINT + '/', 'https://router.huggingface.co/v1/chat/completions',
    'https://api.deepseek.com.attacker.invalid/chat/completions', 'https://user:pass@api.deepseek.com/chat/completions'])
def test_wrong_endpoint_rejected_without_secret_lookup(endpoint):
    calls = []
    with pytest.raises(ValueError):
        DeepSeekProvider(endpoint=endpoint, secret_resolver=lambda ref: calls.append(ref))
    assert calls == []


@pytest.mark.parametrize('reference', ['env:HF_TOKEN', 'file:HF_TOKEN', 'env:OTHER_KEY',
                                      'DEEPSEEK_API_KEY', None, True])
def test_wrong_credential_reference_rejected_without_secret_lookup(reference):
    calls = []
    with pytest.raises(ValueError):
        DeepSeekProvider(reference, secret_resolver=lambda ref: calls.append(ref))
    assert calls == []


@pytest.mark.parametrize('field,value', [('endpoint', 'https://attacker.invalid/'),
                                       ('secret_ref', 'env:HF_TOKEN')])
def test_mutated_scope_rejected_before_lookup_or_transport(field, value):
    calls, resolves = [], []
    adapter = provider(lambda request: calls.append(request), resolves)
    setattr(adapter, field, value)
    with pytest.raises(ProviderFailure, match='PROVIDER_SCOPE_DENIED') as exc:
        run(adapter)
    assert exc.value.pre_execution is True and calls == resolves == []
    assert adapter.health()['readiness'] == 'CONFIGURATION_INVALID' and resolves == []


def test_request_uses_current_documented_text_contract_not_generic_unsupported_parameters():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        assert str(request.url) == ENDPOINT and request.headers['authorization'] == 'Bearer ' + TOKEN
        return response(success())
    result = run(provider(handler))
    assert calls == [{'model': MODEL.name, 'messages': MESSAGES, 'stream': True,
        'stream_options': {'include_usage': True}, 'max_tokens': 16, 'thinking': {'type': 'disabled'}}]
    assert result['text'] == 'ok' and result['usage'] == Usage(10, 2, 4)
    assert result['cost_usd'] == Decimal('.000022')
    assert TOKEN not in str(result)


@pytest.mark.parametrize('name', ['deepseek-chat', 'deepseek-reasoner', 'deepseek-flash:fastest',
                                 'https://attacker.invalid/model', 'unknown'])
def test_unsupported_model_rejected_before_secret_lookup(name):
    resolves = []
    adapter = provider(lambda _: pytest.fail('No transport'), resolves)
    with pytest.raises(ProviderFailure, match='PROVIDER_MODEL_UNSUPPORTED'):
        asyncio.run(complete(adapter, replace(MODEL, name=name), MESSAGES, output_tokens=16, max_retries=0))
    assert resolves == []


@pytest.mark.parametrize('messages', [[], [{'role': 'tool', 'content': 'x'}],
    [{'role': 'user', 'content': [{'type': 'image_url'}]}],
    [{'role': 'assistant', 'content': 'x', 'reasoning_content': 'PRIVATE_REASONING'}],
    [{'role': 'user', 'content': 'x', 'name': 'extra'}]])
def test_nontext_or_unadvertised_message_features_never_resolve_credentials(messages):
    resolves = []
    adapter = provider(lambda _: pytest.fail('No transport'), resolves)
    with pytest.raises(ProviderFailure):
        asyncio.run(complete(adapter, MODEL, messages, output_tokens=16, max_retries=0))
    assert resolves == []


@pytest.mark.parametrize('mutation', [{'prompt_tokens': True}, {'completion_tokens': 2.0},
    {'total_tokens': 13}, {'prompt_cache_hit_tokens': -1}, {'prompt_cache_miss_tokens': 7},
    {'prompt_tokens_details': {'cached_tokens': 3}}, {'completion_tokens_details': {'reasoning_tokens': 3}},
    {'completion_tokens_details': 'PRIVATE_ERROR'}])
def test_contradictory_or_malformed_usage_is_uncertain_nonreplayable(mutation):
    value = {**usage(), **mutation}
    calls = []
    def handler(request):
        calls.append(1)
        return response(sse(item(), item({}, 'stop', value)))
    with pytest.raises(ProviderFailure, match='INVALID_USAGE') as exc:
        asyncio.run(complete(provider(handler), MODEL, MESSAGES, output_tokens=16, max_retries=2))
    assert exc.value.pre_execution is False and len(calls) == 1
    assert 'PRIVATE_ERROR' not in str(exc.value)


@pytest.mark.parametrize('raw,code', [
    ('data: {"id":"a","id":"b"}\n\n', 'MALFORMED_STREAM'),
    ('data: {"x":1,"\\u0078":2}\n\n', 'MALFORMED_STREAM'),
    ('data: {"x":NaN}\n\n', 'MALFORMED_STREAM'),
    ('data: {"x":1e999}\n\n', 'MALFORMED_STREAM'),
    ('data: PRIVATE_ERROR\n\n', 'MALFORMED_STREAM'),
    (sse(item(), item({}, 'stop', None)), 'INVALID_USAGE'),
    (sse(item(), item({}, None, usage())), 'INVALID_USAGE'),
    (sse(item(), item({}, 'stop', usage()), done=False), 'INCOMPLETE_STREAM'),
    (sse(item({'reasoning_content': 'PRIVATE_REASONING'})), 'UNSUPPORTED_COMPLETION'),
    (sse(item({'tool_calls': [{'id': 'unknown'}]})), 'UNSUPPORTED_COMPLETION'),
    (sse(item(), item({}, 'length', usage())), 'OUTPUT_BUDGET_EXHAUSTED'),
    (sse(item(), item({}, 'insufficient_system_resource', usage())), 'MALFORMED_STREAM'),
])
def test_malformed_unsupported_or_partial_stream_never_replayed(raw, code):
    calls = []
    def handler(request):
        calls.append(1)
        return response(raw)
    with pytest.raises(ProviderFailure, match=code) as exc:
        asyncio.run(complete(provider(handler), MODEL, MESSAGES, output_tokens=16, max_retries=2))
    assert len(calls) == 1 and exc.value.pre_execution is False
    assert 'PRIVATE_' not in str(exc.value)


@pytest.mark.parametrize('status,body', [
    (401, {'error': {'message': TOKEN}}), (402, {'error': {'message': TOKEN}}),
    (500, {'error': {'message': TOKEN}}),
    (503, {'error': {'code': 'model_at_capacity', 'message': 'Overloaded'}}),
    (429, {'error': {'message': 'Rate limit'}, 'usage': {'prompt_tokens': 1}}),
    (429, '{"error":{"message":"Rate limit","message":"contradiction"}}'),
])
def test_ambiguous_or_auth_http_failure_cannot_select_alternate(status, body):
    calls, alternate = [], []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, content=body if type(body) is str else json.dumps(body))
    class NeverAlternate:
        async def stream(self, *args):
            alternate.append(1)
            yield Chunk('wrong', Usage(1, 1, 0), True)
    with pytest.raises(ProviderFailure) as exc:
        asyncio.run(complete_with_fallback([(provider(handler), MODEL), (NeverAlternate(), MODEL)],
            MESSAGES, authorize_candidate=lambda *args: True, output_tokens=16, timeout=1, max_retries=0))
    assert exc.value.pre_execution is False and calls == [1] and alternate == []
    assert TOKEN not in str(exc.value)


def test_clean_explicit_rate_rejection_allows_only_existing_authorized_fallback_contract():
    calls, alternate = [], []
    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={'error': {'message': 'Rate limit reached', 'code': 'rate_limit'}})
    class Alternate:
        async def stream(self, *args):
            alternate.append(1)
            yield Chunk('approved', Usage(1, 1, 0), True)
    result = asyncio.run(complete_with_fallback([(provider(handler), MODEL), (Alternate(), MODEL)],
        MESSAGES, authorize_candidate=lambda *args: True, output_tokens=16, timeout=1, max_retries=0))
    assert result['text'] == 'approved' and calls == alternate == [1]
    assert result['fallback_failures'] == [{'provider': MODEL.provider, 'code': 'RATE_LIMIT'}]


def test_cancel_quiet_stream_closes_connection_without_second_request():
    state = {'requested': False, 'closed': False, 'count': 0}
    class Quiet(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(10)
            yield b''
        async def aclose(self):
            state['closed'] = True
    def handler(request):
        state.update(requested=True, count=state['count'] + 1)
        return httpx.Response(200, stream=Quiet())
    with pytest.raises(ProviderFailure, match='CANCELLED') as exc:
        run(provider(handler), timeout=1, cancelled=lambda: state['requested'])
    assert exc.value.pre_execution is False and state['closed'] is True and state['count'] == 1


def test_read_timeout_after_partial_content_preserves_no_replay():
    state = {'count': 0, 'closed': False}
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse(item(), done=False).encode()
            raise httpx.ReadTimeout('PRIVATE_TRANSPORT_ERROR')
        async def aclose(self):
            state['closed'] = True
    def handler(request):
        state['count'] += 1
        return httpx.Response(200, stream=Partial())
    with pytest.raises(ProviderFailure, match='PROVIDER_TIMEOUT') as exc:
        asyncio.run(complete(provider(handler), MODEL, MESSAGES, output_tokens=16, max_retries=2))
    assert exc.value.pre_execution is False and state['count'] == 1 and state['closed'] is True
    assert 'PRIVATE_TRANSPORT_ERROR' not in str(exc.value)


def test_readiness_is_not_network_health_or_qualification():
    adapter = provider(lambda _: pytest.fail('Readiness must not contact provider'))
    assert adapter.health() == {'readiness': 'READY', 'provider_health': 'UNMEASURED',
                                'network_probe_performed': False}


def test_second_current_model_and_unicode_split_across_unread_network_chunks():
    model = replace(MODEL, name='deepseek-v4-pro')
    values = [item({'content': 'Unicode \u03bb \U0001f9ea'}), item({}, 'stop', usage())]
    for value in values:
        value['model'] = model.name
    raw = sse(*values).encode()
    class Split(httpx.AsyncByteStream):
        async def __aiter__(self):
            for begin in range(0, len(raw), 3):
                yield raw[begin:begin + 3]
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, stream=Split())
    result = asyncio.run(complete(provider(handler), model, MESSAGES, output_tokens=16, max_retries=0))
    assert result['text'] == 'Unicode \u03bb \U0001f9ea' and len(calls) == 1
    assert calls[0]['model'] == 'deepseek-v4-pro'


def test_changed_stream_model_or_identity_is_not_bound_execution():
    for field, value in [('model', 'deepseek-v4-pro'), ('id', 'different-stream')]:
        terminal = item({}, 'stop', usage())
        terminal[field] = value
        with pytest.raises(ProviderFailure, match='MALFORMED_STREAM') as exc:
            run(provider(lambda _: response(sse(item(), terminal))))
        assert exc.value.pre_execution is False


def test_oversized_wire_line_stops_before_json_decode():
    with pytest.raises(ProviderFailure, match='STREAM_SIZE_EXCEEDED') as exc:
        run(provider(lambda _: response('data: ' + 'x' * 1_000_001)))
    assert exc.value.pre_execution is False


def test_prestart_cancel_and_authority_denial_do_not_resolve_secret():
    resolves = []
    adapter = provider(lambda _: pytest.fail('No request allowed'), resolves)
    with pytest.raises(ProviderFailure, match='CANCELLED'):
        run(adapter, cancelled=lambda: True)
    with pytest.raises(ProviderFailure, match='FALLBACK_POLICY_DENIED'):
        asyncio.run(complete_with_fallback([(adapter, MODEL)], MESSAGES,
            authorize_candidate=lambda *args: False, output_tokens=16, timeout=1, max_retries=0))
    assert resolves == []


def test_redirect_never_sends_key_to_other_host():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={'Location': 'https://attacker.invalid/steal'})
    with pytest.raises(ProviderFailure, match='PROVIDER_HTTP_FAILURE') as exc:
        run(provider(handler))
    assert exc.value.pre_execution is False and calls == [ENDPOINT]
