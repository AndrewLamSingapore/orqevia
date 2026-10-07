"""HF JSON-object wire mode fixtures only; never model quality or live calls."""
import asyncio
from decimal import Decimal
import json

import httpx
import pytest

from app.provider_runtime import HuggingFaceProvider, ModelSpec, ProviderFailure, Usage, complete


MODEL = ModelSpec('google/gemma-3-4b-it:deepinfra', 'hf-json-fixture', 'MINI', 4096, 64,
                  Decimal('.05'), Decimal('.10'))
MESSAGES = [{'role': 'user', 'content': 'Public synthetic case. Return a JSON object.'}]


def sse(text='{"answer":"ODD"}', *, usage=True, done=True, finish='stop'):
    rows = [{'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]},
            {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}]
    if usage:
        rows.append({'choices': [], 'usage': {'prompt_tokens': 20, 'completion_tokens': 8}})
    return ''.join('data: ' + json.dumps(row) + '\n\n' for row in rows) + ('data: [DONE]\n\n' if done else '')


def provider(handler, *, mode='json_object', resolver=None):
    return HuggingFaceProvider(response_format=mode,
        secret_resolver=resolver or (lambda _: 'SYNTHETIC_ONLY_HF_TOKEN'),
        transport=httpx.MockTransport(handler))


def run(adapter, **kwargs):
    return asyncio.run(complete(adapter, MODEL, MESSAGES, output_tokens=32, timeout=.2,
                                max_retries=0, **kwargs))


@pytest.mark.parametrize('mode', ['DEFAULT', 'text'])
def test_existing_text_body_is_exactly_unchanged(mode):
    kwargs = {} if mode == 'DEFAULT' else {'response_format': mode}
    adapter = HuggingFaceProvider(secret_resolver=lambda _: 'SYNTHETIC_ONLY_HF_TOKEN', **kwargs)
    expected = {'model': MODEL.name, 'messages': MESSAGES, 'stream': True,
                'stream_options': {'include_usage': True}, 'max_tokens': 32}
    body = adapter.request_body(MODEL, MESSAGES, 32)
    assert json.dumps(body).encode() == json.dumps(expected).encode()
    assert 'response_format' not in body


def test_json_object_adds_only_explicit_wire_field_and_preserves_usage():
    bodies = []
    def handler(request):
        assert request.method == 'POST'
        assert str(request.url) == HuggingFaceProvider.ENDPOINT
        bodies.append(json.loads(request.content))
        return httpx.Response(200, text=sse())
    result = run(provider(handler))
    assert bodies == [{'model': MODEL.name, 'messages': MESSAGES, 'stream': True,
        'stream_options': {'include_usage': True}, 'max_tokens': 32,
        'response_format': {'type': 'json_object'}}]
    assert result['text'] == '{"answer":"ODD"}'
    assert result['usage'] == Usage(20, 8, 0)
    assert result['cost_usd'] == Decimal('.0000018') and result['retries'] == 0
    assert 'SYNTHETIC_ONLY_HF_TOKEN' not in str(result)


class StringSubclass(str):
    pass


@pytest.mark.parametrize('mode', [None, True, False, 0, 1, [], {}, {'type': 'json_object'},
    'json_schema', 'JSON_OBJECT', 'json_object\n', 'json_object ', 'auto',
    'PRIVATE_UNTRUSTED_MODE', StringSubclass('json_object')])
def test_invalid_constructor_modes_reject_before_credential_access(mode):
    calls = []
    with pytest.raises(ValueError, match='Unsupported Hugging Face response format') as error:
        HuggingFaceProvider(response_format=mode, secret_resolver=lambda ref: calls.append(ref))
    assert calls == [] and 'PRIVATE_UNTRUSTED_MODE' not in str(error.value)


@pytest.mark.parametrize('mode', [None, False, {'type': 'json_object'}, 'json_schema', 'PRIVATE_UNTRUSTED_MODE'])
def test_mutated_mode_rejected_before_secret_or_transport(mode):
    secrets, transport = [], []
    adapter = provider(lambda req: transport.append(req), resolver=lambda ref: secrets.append(ref))
    adapter.response_format = mode
    with pytest.raises(ProviderFailure, match='RESPONSE_FORMAT_UNSUPPORTED') as error:
        run(adapter)
    assert error.value.pre_execution is True
    assert secrets == [] and transport == []
    assert 'PRIVATE_UNTRUSTED_MODE' not in str(error.value)


@pytest.mark.parametrize('name', ['google/gemma-3-4b-it:auto', 'google/gemma-3-4b-it:fastest',
    'google/gemma-3-4b-it', 'https://attacker.invalid/model'])
def test_json_mode_preserves_pinned_model_boundary(name):
    model = ModelSpec(name, MODEL.provider, MODEL.tier, 4096, 64)
    adapter = provider(lambda _: None)
    with pytest.raises(ProviderFailure, match='MODEL_PROVIDER_UNPINNED'):
        adapter.request_body(model, MESSAGES, 32)


@pytest.mark.parametrize('status,body,code,pre_execution', [
    (401, 'PRIVATE_UPSTREAM_BODY', 'AUTHENTICATION', False),
    (302, 'PRIVATE_UPSTREAM_BODY', 'PROVIDER_HTTP_FAILURE', False),
    (503, '{"error":{"code":"capacity_exceeded"},"content":"admitted"}', 'PROVIDER_HTTP_FAILURE', False),
    (429, '', 'RATE_LIMIT', True),
    (503, '{"error":{"code":"capacity_exceeded"}}', 'CAPACITY', True)])
def test_output_mode_does_not_change_rejection_ambiguity_or_replay(status, body, code, pre_execution):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=body, headers={'Location': 'https://attacker.invalid/steal'})
    with pytest.raises(ProviderFailure, match=code) as error:
        run(provider(handler))
    assert len(calls) == 1 and error.value.pre_execution is pre_execution
    assert 'PRIVATE_UPSTREAM_BODY' not in str(error.value)


@pytest.mark.parametrize('body,code', [
    (sse(finish='length'), 'OUTPUT_BUDGET_EXHAUSTED'),
    (sse(done=False), 'INCOMPLETE_STREAM'),
    ('data: {"choices":[],"choices":[]}\n\n', 'MALFORMED_STREAM')])
def test_completion_validation_still_fails_closed(body, code):
    with pytest.raises(ProviderFailure, match=code):
        run(provider(lambda _: httpx.Response(200, text=body)))


def test_output_mode_is_not_an_oracle_or_parser_repair():
    result = run(provider(lambda _: httpx.Response(200, text=sse('not valid JSON'))))
    assert result['text'] == 'not valid JSON'  # Downstream oracle must reject it unchanged.


def test_cancellation_does_not_submit_or_resolve_credentials():
    secrets, calls = [], []
    adapter = provider(lambda req: calls.append(req), resolver=lambda ref: secrets.append(ref))
    with pytest.raises(ProviderFailure, match='CANCELLED'):
        run(adapter, cancelled=lambda: True)
    assert secrets == [] and calls == []
