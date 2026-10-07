import asyncio
import json

import httpx
import pytest

from app.hf_serverless import HFServerlessQA
from app.provider_runtime import ProviderFailure


CONTEXT = 'My name is Clara and I live in Berkeley.'
QUESTION = 'What is my name?'
SPAN = {'answer': 'Clara', 'score': .97, 'start': 11, 'end': 16}


def run(provider, **kwargs):
    return asyncio.run(provider.answer(context=kwargs.pop('context', CONTEXT),
        question=kwargs.pop('question', QUESTION),
        data_classification=kwargs.pop('data_classification', 'CLOUD_PERMITTED'), **kwargs))


def adapter(response=None, *, exception=None, resolver=None):
    calls = []
    def handler(request):
        calls.append(request)
        if exception:
            raise exception
        return response if response is not None else httpx.Response(200, json=SPAN)
    return HFServerlessQA(secret_resolver=resolver or (lambda _: 'fixture-only'),
                         transport=httpx.MockTransport(handler)), calls


@pytest.mark.parametrize('payload', [SPAN, [SPAN]])
def test_real_task_shape_fixed_hf_owned_route_and_unknown_usage(payload):
    provider, calls = adapter(httpx.Response(200, json=payload))
    result = run(provider)
    assert len(calls) == 1 and str(calls[0].url) == HFServerlessQA.ENDPOINT
    assert calls[0].method == 'POST'
    assert json.loads(calls[0].content) == {
        'inputs': {'context': CONTEXT, 'question': QUESTION},
        'parameters': {'top_k': 1, 'max_answer_len': 64, 'handle_impossible_answer': True}}
    assert result['answer'] == 'Clara' and result['provider_score'] == .97
    assert result['provider'] == 'hf-inference' and result['route'] == 'DIRECT_HF'
    assert result['task'] == 'question-answering' and result['latency_ms'] >= 0
    assert result['quality_oracle'] == 'CALLER_VERIFICATION_REQUIRED'
    for field in ('input_tokens', 'output_tokens', 'cost_usd', 'time_to_first_token_ms', 'tokens_per_second'):
        assert result[field] is None
    assert result['retries'] == 0 and 'fixture-only' not in json.dumps(result)


@pytest.mark.parametrize('kwargs', [
    {'context': None}, {'context': ''}, {'question': []}, {'question': ' '},
    {'context': 'x' * 2049}, {'question': 'x' * 257}, {'context': '\ud800'},
    {'context': 'private\x00input'}, {'context': 'password=never-send'},
    {'data_classification': 'LOCAL_ONLY'}, {'data_classification': 'SENSITIVE'},
    {'timeout_seconds': 0}, {'timeout_seconds': True}, {'timeout_seconds': 31},
    {'timeout_seconds': float('nan')},
])
def test_input_budget_locality_timeout_before_credential_or_network(kwargs):
    def denied(_):
        pytest.fail('preflight must not resolve credential')
    provider, calls = adapter(resolver=denied)
    with pytest.raises(ProviderFailure) as failure:
        run(provider, **kwargs)
    assert failure.value.pre_execution and calls == []
    assert 'never-send' not in str(failure.value)


@pytest.mark.parametrize('value', [None, '', 'x\n', 'x y', 'é', 'x' * 4097])
def test_invalid_credential_is_sanitized_before_transport(value):
    provider, calls = adapter(resolver=lambda _: value)
    with pytest.raises(ProviderFailure, match='CREDENTIAL_UNAVAILABLE') as failure:
        run(provider)
    assert failure.value.pre_execution and calls == []


def test_resolver_raw_exception_never_appears_and_health_not_network_proof():
    def denied(_):
        raise ValueError('private token=never-print-this')
    provider, calls = adapter(resolver=denied)
    assert provider.health()['provider_health'] == 'UNMEASURED'
    with pytest.raises(ProviderFailure, match='CREDENTIAL_UNAVAILABLE') as failure:
        run(provider)
    assert 'never-print' not in str(failure.value) and calls == []


@pytest.mark.parametrize('payload', [
    [], [SPAN, SPAN], None, 'raw private output', [],
    {**SPAN, 'score': True}, {**SPAN, 'score': float('nan')}, {**SPAN, 'score': float('inf')},
    {**SPAN, 'score': -1}, {**SPAN, 'score': 1.01}, {**SPAN, 'score': '0.97'},
    {**SPAN, 'score': 10 ** 1000}, {**SPAN, 'answer': '\ud800'},
    {**SPAN, 'start': True}, {**SPAN, 'start': -1}, {**SPAN, 'end': len(CONTEXT) + 1},
    {**SPAN, 'start': 16}, {**SPAN, 'answer': ''}, {**SPAN, 'answer': 'Berkeley'},
    {**SPAN, 'end': 16.0}, {**SPAN, 'answer': {'private': 'raw'}},
])
def test_finite_bounded_exact_answer_span_required(payload):
    # Raw wire bodies deliberately carry NaN/Infinity so validation, not the
    # fixture constructor's strict encoder, discriminates the malformed result.
    provider, calls = adapter(httpx.Response(200, content=json.dumps(payload).encode()))
    with pytest.raises(ProviderFailure) as failure:
        run(provider)
    assert failure.value.code in {'MALFORMED_QA_RESPONSE', 'INVALID_QA_ANSWER_SPAN'}
    assert not failure.value.pre_execution and len(calls) == 1
    assert 'raw private' not in str(failure.value)


def test_unicode_span_indexes_bind_original_context():
    context = '名字是 Clara。'
    span = {'answer': 'Clara', 'score': .9, 'start': 4, 'end': 9}
    provider, _ = adapter(httpx.Response(200, json=span))
    assert run(provider, context=context)['answer'] == 'Clara'


@pytest.mark.parametrize('raw', [
    b'{"answer":"Clara","score":0.97,"start":11,"end":16,"end":30}',
    b'not-json private token=never-print', b'\xff', b'[]' + b' ' * 16383,
])
def test_malformed_duplicate_or_oversized_response_rejected_without_replay(raw):
    provider, calls = adapter(httpx.Response(200, content=raw))
    with pytest.raises(ProviderFailure) as failure:
        run(provider)
    assert len(calls) == 1 and failure.value.code in {'MALFORMED_QA_RESPONSE', 'QA_RESPONSE_SIZE_EXCEEDED'}
    assert 'never-print' not in str(failure.value)


@pytest.mark.parametrize('status,body,code,pre', [
    (301, None, 'PROVIDER_HTTP_FAILURE', False),
    (401, {'error': 'raw private'}, 'AUTHENTICATION', False),
    (403, {}, 'AUTHENTICATION', False), (429, {}, 'RATE_LIMIT', True),
    (500, {}, 'PROVIDER_HTTP_FAILURE', False),
    (503, {'error': {'code': 'model_at_capacity'}}, 'CAPACITY', True),
    (503, {'error': {'message': 'Ambiguous private execution'}}, 'PROVIDER_HTTP_FAILURE', False),
])
def test_http_faults_have_one_request_no_redirect_replay_or_raw_errors(status, body, code, pre):
    provider, calls = adapter(httpx.Response(status, json=body,
        headers={'Location': 'https://untrusted.invalid/credential-sink'}))
    with pytest.raises(ProviderFailure) as failure:
        run(provider)
    assert len(calls) == 1 and failure.value.code == code
    assert failure.value.pre_execution is pre and 'private' not in str(failure.value)


@pytest.mark.parametrize('error,code', [
    (httpx.ReadTimeout('private timeout'), 'PROVIDER_TIMEOUT'),
    (httpx.ConnectError('private endpoint'), 'PROVIDER_TRANSPORT_FAILURE'),
])
def test_transport_ambiguity_is_not_retried(error, code):
    provider, calls = adapter(exception=error)
    with pytest.raises(ProviderFailure) as failure:
        run(provider)
    assert failure.value.code == code and not failure.value.pre_execution
    assert len(calls) == 1 and 'private' not in str(failure.value)


def test_whole_request_deadline_bounds_slow_trickle_and_closes_stream():
    closed = []
    calls = []
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(3):
                await asyncio.sleep(.01)
                yield b' '
        async def aclose(self):
            closed.append(True)
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=SlowStream())
    provider = HFServerlessQA(secret_resolver=lambda _: 'fixture-only',
                             transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure, match='PROVIDER_TIMEOUT') as failure:
        run(provider, timeout_seconds=.015)
    assert not failure.value.pre_execution and len(calls) == 1 and closed == [True]


def test_caller_cancellation_propagates_and_never_becomes_provider_fault():
    closed = []
    class WaitingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise asyncio.CancelledError()
            yield b'unreachable'
        async def aclose(self):
            closed.append(True)
    provider = HFServerlessQA(secret_resolver=lambda _: 'fixture-only',
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=WaitingStream())))
    with pytest.raises(asyncio.CancelledError):
        run(provider)
    assert closed == [True]


@pytest.mark.parametrize('kwargs', [
    {'secret_ref': 'env:OTHER_KEY'}, {'secret_ref': 'file:../token'},
    {'secret_ref': []},
    {'model': 'other/model'}, {'model': HFServerlessQA.MODEL + ':deepinfra'},
    {'secret_resolver': None},
])
def test_model_and_credential_scope_cannot_be_redirected(kwargs):
    with pytest.raises(ValueError):
        HFServerlessQA(**kwargs)


_AMBIGUOUS_REJECTIONS = [
    {'error': {'code': 'model_at_capacity', 'usage': {'total_tokens': 1}}},
    {'error': {'code': 'model_at_capacity', 'content': 'already generated'}},
    {'error': {'code': 'model_at_capacity'}, 'text': 'already generated'},
    {'error': {'code': 'model_at_capacity'}, 'delta': {'content': 'already generated'}},
    {'error': {'code': 'model_at_capacity'}, 'total_tokens': 1},
    {'error': {'code': 'model_at_capacity', 'details': {'answer': 'already generated'}}},
    {'error': {'code': 'model_at_capacity', 'request_id': ['malformed']}},
    {'error': {'code': 'model_at_capacity', 'message': {'private': 'fixture'}}},
    {'error': {'code': 'model_at_capacity'}, 'status': True},
    {'error': {'code': 'model_at_capacity'}, 'retry_after': float('nan')},
    {'error': {'code': 'model_at_capacity'}, 'retry_after': float('inf')},
]


@pytest.mark.parametrize('status', [429, 503])
@pytest.mark.parametrize('body', _AMBIGUOUS_REJECTIONS)
def test_ambiguous_rejected_admission_never_claims_pre_execution(status, body):
    provider, calls = adapter(httpx.Response(status, content=json.dumps(body).encode()))
    with pytest.raises(ProviderFailure, match='^PROVIDER_HTTP_FAILURE$') as failure:
        run(provider)
    assert failure.value.pre_execution is False and len(calls) == 1
    assert 'already generated' not in str(failure.value) and 'fixture' not in str(failure.value)


@pytest.mark.parametrize('status', [429, 503])
@pytest.mark.parametrize('raw', [
    b'{"error":{"code":"model_at_capacity","code":"capacity_exceeded"}}',
    b'{"error":{"code":"model_at_capacity","c\\u006fde":"capacity_exceeded"}}',
    b'{"error":{"code":"model_at_capacity"},"message":"a","message":"b"}',
    b'{"error":{"code":"model_at_capacity"},"retry_after":1e9999}',
    b'{"error":{"code":"model_at_capacity"},"status":NaN}',
    b'{"error":{"code":"model_at_capacity"},"retry_after":Infinity}',
])
def test_duplicate_and_nonfinite_rejected_admission_is_ambiguous(status, raw):
    provider, calls = adapter(httpx.Response(status, content=raw))
    with pytest.raises(ProviderFailure, match='^PROVIDER_HTTP_FAILURE$') as failure:
        run(provider)
    assert failure.value.pre_execution is False and len(calls) == 1


@pytest.mark.parametrize('status,code', [(429, 'RATE_LIMIT'), (503, 'CAPACITY')])
def test_clean_typed_rejected_admission_preserves_explicit_capacity_and_rate_limit(status, code):
    body = {'error': {'code': 'model_at_capacity', 'message': 'capacity',
        'request_id': 'public-fixture'}, 'status': status, 'retry_after': 1.5}
    provider, calls = adapter(httpx.Response(status, json=body))
    with pytest.raises(ProviderFailure, match='^' + code + '$') as failure:
        run(provider)
    assert failure.value.pre_execution is True and len(calls) == 1


@pytest.mark.parametrize('status,code,pre_execution', [(429, 'RATE_LIMIT', True),
    (503, 'PROVIDER_HTTP_FAILURE', False)])
def test_empty_rate_rejection_is_not_empty_ambiguous_server_failure(status, code, pre_execution):
    provider, calls = adapter(httpx.Response(status, content=b''))
    with pytest.raises(ProviderFailure, match='^' + code + '$') as failure:
        run(provider)
    assert failure.value.pre_execution is pre_execution and len(calls) == 1


@pytest.mark.parametrize('raw', [
    b'{"answer":"Clara","score":0.97,"start":11,"end":16,"diagnostic":NaN}',
    b'{"answer":"Clara","score":0.97,"start":11,"end":16,"diagnostic":Infinity}',
    b'{"answer":"Clara","score":0.97,"start":11,"end":16,"diagnostic":1e9999}',
])
def test_success_body_nonfinite_unknown_fields_fail_closed(raw):
    provider, calls = adapter(httpx.Response(200, content=raw))
    with pytest.raises(ProviderFailure, match='^MALFORMED_QA_RESPONSE$') as failure:
        run(provider)
    assert failure.value.pre_execution is False and len(calls) == 1


@pytest.mark.parametrize('status', [429, 503])
def test_ambiguous_rejected_admission_cannot_dispatch_qa_router_fallback(monkeypatch, status):
    import hashlib
    from app.hf_qa_execution import QAReservation, execute_direct_qa
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'only-offline-owner-fixture')
    provider, calls = adapter(httpx.Response(status, json=_AMBIGUOUS_REJECTIONS[0]))
    router_calls = []

    def admit(binding, previous, phase):
        return QAReservation(reservation_id='0f0f204b-5bcd-4e64-82d0-8309d7ca9941',
            binding_sha256=hashlib.sha256(json.dumps(binding, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest(),
            price_contract_sha256='a' * 64, expires_monotonic=200.0,
            direct_maximum_charge_usd='.001', router_maximum_charge_usd='.001',
            hf_router_provider_id='hf-router-approved',
            hf_router_model='google/gemma-3-4b-it:deepinfra')

    def forbidden_router(**kwargs):
        router_calls.append(True)
        raise AssertionError('ambiguous direct execution cannot replay')

    with pytest.raises(ProviderFailure, match='^PROVIDER_HTTP_FAILURE$') as failure:
        execute_direct_qa(authorization='Bearer only-offline-owner-fixture', agent_id='a18',
            task_id='b3c60f03-e8e5-4f19-a0b4-c085ffbb0a01', context=CONTEXT, question=QUESTION,
            data_classification='CLOUD_PERMITTED', max_cost_usd='.01', admit=admit,
            execute_hf_router=forbidden_router, qa=provider, clock=lambda: 100.0)
    assert failure.value.pre_execution is False and len(calls) == 1 and router_calls == []
