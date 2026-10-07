"""Rejected admission must not hide output, usage or duplicate JSON keys."""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import cloud_execution as cloud
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import HuggingFaceProvider, ProviderFailure


def successful_stream():
    events = [
        {'choices': [{'index': 0, 'delta': {'content': 'alternate fixture'}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
        {'choices': [], 'usage': {'prompt_tokens': 8, 'completion_tokens': 3}},
    ]
    return ''.join('data: ' + json.dumps(item) + '\n\n' for item in events) + 'data: [DONE]\n\n'


def chain(monkeypatch, status, raw):
    base = {'enabled': True, 'qualification_status': 'QUALIFIED', 'location': 'cloud',
        'tier': 'NANO', 'context_tokens': 4096, 'output_tokens': 64,
        'input_usd_million': '0.05', 'output_usd_million': '0.10',
        'provider_kind': 'huggingface', 'endpoint': HuggingFaceProvider.ENDPOINT,
        'secret_ref': 'env:HF_TOKEN', 'max_retries': 0}
    entries = [dict(base, id='hf-primary', model='fixture/primary:provider',
        fallback_ids=['hf-alternate'], hf_fallback_policy={
            'version': 'hf-fallback.v1', 'allowed_provider_ids': ['hf-alternate'],
            'allow_non_hf': False}),
        dict(base, id='hf-alternate', model='fixture/alternate:provider')]
    calls, reads, metrics = [], [], []
    circuits = ProviderCircuits(failure_threshold=1)
    def handler(request):
        model = json.loads(request.content)['model']
        calls.append(model)
        return (httpx.Response(status, content=raw) if model == entries[0]['model'] else
                httpx.Response(200, text=successful_stream()))
    def adapter(entry):
        def resolve(_):
            reads.append(entry['id'])
            return 'private-fixture-key-not-a-real-credential'
        return HuggingFaceProvider(entry['secret_ref'], secret_resolver=resolve,
            transport=httpx.MockTransport(handler))
    class Metrics:
        def __init__(self, *args):
            pass
        def record(self, **kwargs):
            metrics.append(kwargs)
    monkeypatch.setattr(cloud, 'load_catalog', lambda: entries)
    monkeypatch.setattr(cloud, 'adapter_for', adapter)
    monkeypatch.setattr(cloud, 'PROVIDER_CIRCUITS', circuits)
    monkeypatch.setattr(cloud, 'OutcomeMetrics', Metrics)
    monkeypatch.setattr(cloud, 'action_ledger', lambda: None)
    monkeypatch.setattr(cloud.DirectExecutor, 'execute', lambda self, record, operation: operation())
    job = {'id': 'fixture-job', 'agent': 'a20', 'prompt': 'Public synthetic classification',
        'preferred_provider': 'hf-primary', 'allow_cloud': 1,
        'data_classification': 'CLOUD_PERMITTED', 'task_class': 'classification',
        'timeout_seconds': 3, 'estimated_cost_usd': .0001, 'max_cost_usd': .0001}
    def run():
        return cloud.execute_cloud(job, SimpleNamespace(name='hf-primary'), Path('.'), lambda: False)
    return run, calls, reads, metrics, circuits


AMBIGUOUS = [
    b'{"error":{"code":"model_at_capacity"},"usage":{"prompt_tokens":1,"completion_tokens":1}}',
    b'{"error":{"code":"model_at_capacity"},"choices":[{"message":{"content":"already completed"}}]}',
    b'{"error":{"code":"model_at_capacity"},"result":"already completed"}',
    b'{"error":{"code":"model_at_capacity","usage":{"completion_tokens":1}}}',
    b'{"error":{"code":"model_at_capacity","details":{"output":"already completed"}}}',
    b'{"error":{"code":"unknown"},"error":{"code":"model_at_capacity"}}',
    b'{"error":{"code":"unknown","code":"model_at_capacity"}}',
    b'{"error":{"co\\u0064e":"unknown","code":"model_at_capacity"}}',
    b'{"error":{"code":"model_at_capacity","message":{"private":"raw-upstream"}}}',
    b'{"error":{"code":[],"message":"Selected model is at capacity. Please try a different model."}}',
    b'{"error":{"code":"model_at_capacity"},"metadata":NaN}',
    b'{"error":{"code":"model_at_capacity"},"metadata":1e999}',
    b'[{"error":{"code":"model_at_capacity"}}]',
    b'private raw-upstream non-JSON response',
    b'{"error":{"code":"model_at_capacity"},"message":"' + b'x' * 65536 + b'"}',
    b'{"error":{"code":"model_at_capacity"},"content":"already completed"}',
    b'{"error":{"code":"model_at_capacity"},"delta":{"content":"already completed"}}',
    b'{"error":{"code":"model_at_capacity"},"total_tokens":3}',
    b'{"error":{"code":"model_at_capacity"},"tokens":["already completed"]}',
    b'{"error":{"code":"model_at_capacity","details":{"content":"already completed"}}}',
    b'{"error":{"code":"model_at_capacity","details":{"total_tokens":3}}}',
    b'{"error":{"code":"model_at_capacity"},"unrecognized_payload":{"answer":"already completed"}}',
    b'{"error":{"code":"model_at_capacity","unrecognized":"already completed"}}',
    b'{"error":{"code":"model_at_capacity"},"status":200}',
    b'{"error":{"code":"model_at_capacity"},"retry_after":-1}',
]


@pytest.mark.parametrize('status', [503, 429])
@pytest.mark.parametrize('raw', AMBIGUOUS, ids=[
    'usage', 'choices', 'result', 'nested-usage', 'nested-output', 'duplicate-error',
    'duplicate-code', 'duplicate-decoded-code', 'malformed-message', 'malformed-code', 'nonfinite-json', 'overflow-number',
    'nonobject-json', 'invalid-json', 'oversized-error', 'content', 'delta',
    'total-tokens', 'tokens', 'nested-content', 'nested-total-tokens',
    'unsupported-root-envelope', 'unsupported-error-envelope', 'contradictory-status', 'invalid-retry-metadata'])
def test_ambiguous_error_never_dispatches_alternate_or_invents_usage(monkeypatch, status, raw):
    run, calls, reads, metrics, circuits = chain(monkeypatch, status, raw)
    with pytest.raises(ProviderFailure, match='PROVIDER_HTTP_FAILURE') as caught:
        run()
    assert caught.value.pre_execution is False
    assert calls == ['fixture/primary:provider'] and reads == ['hf-primary']
    assert metrics[-1]['success'] is False and metrics[-1]['retries'] == 0
    assert metrics[-1]['input_tokens'] is metrics[-1]['output_tokens'] is metrics[-1]['cost'] is None
    assert metrics[-1]['fallback_route'] == []
    assert 'private' not in str(caught.value) and 'raw-upstream' not in str(caught.value)
    state = circuits.snapshot('hf-primary')
    assert state['circuit_state'] == 'OPEN' and state['active_permits'] == 0
    assert state['last_failure_pre_execution'] is False


@pytest.mark.parametrize('status,raw,code', [
    (503, b'{"error":{"code":"model_at_capacity"}}', 'CAPACITY'),
    (503, b'{"error":{"message":"Selected model is at capacity. Please try a different model."}}', 'CAPACITY'),
    (429, b'{"error":{"code":"rate_limit_exceeded","message":"Rate limited"}}', 'RATE_LIMIT'),
    (429, b'', 'RATE_LIMIT'),
    (503, b'{"error":{"code":"model_at_capacity","message":"At capacity","type":"server_error","param":null},"status":503,"request_id":"fixture-request","retry_after":1}', 'CAPACITY'),
    (429, b'{"error":{"code":"rate_limit_exceeded","message":"Rate limited","type":"rate_limit_error","param":null},"status_code":429,"requestId":"fixture-request","retry_after_seconds":1}', 'RATE_LIMIT'),
])
def test_clean_rejected_admission_keeps_approved_fallback(monkeypatch, status, raw, code):
    run, calls, reads, metrics, circuits = chain(monkeypatch, status, raw)
    result = run()
    assert result['result'] == 'alternate fixture'
    assert calls == ['fixture/primary:provider', 'fixture/alternate:provider']
    assert reads == ['hf-primary', 'hf-alternate']
    assert metrics[-1]['success'] is True and metrics[-1]['retries'] == 0
    assert metrics[-1]['fallback_route'] == [{'provider': 'hf-primary', 'code': code}]
    assert metrics[-1]['provider'] == 'hf-alternate' and metrics[-1]['cost'] is not None
    state = circuits.snapshot('hf-primary')
    assert state['circuit_state'] == 'OPEN' and state['last_failure_pre_execution'] is True


@pytest.mark.parametrize('event', [
    '{"choices":[{"delta":{"content":"hidden"}}],"choices":[]}',
    '{"usage":{"prompt_tokens":100,"prompt_tokens":1,"completion_tokens":1}}',
    '{"cho\\u0069ces":[{"delta":{"content":"hidden"}}],"choices":[]}',
    '{"error":{"code":"unknown","code":"model_at_capacity"}}',
])
def test_duplicate_sse_keys_fail_closed_without_safe_replay(monkeypatch, event):
    raw = ('data: ' + event + '\n\n' + successful_stream()).encode()
    run, calls, reads, metrics, circuits = chain(monkeypatch, 200, raw)
    with pytest.raises(ProviderFailure, match='MALFORMED_STREAM') as caught:
        run()
    assert caught.value.pre_execution is False
    assert calls == ['fixture/primary:provider'] and reads == ['hf-primary']
    assert metrics[-1]['input_tokens'] is metrics[-1]['output_tokens'] is metrics[-1]['cost'] is None
    assert metrics[-1]['fallback_route'] == [] and metrics[-1]['success'] is False


def test_empty_503_stays_ambiguous(monkeypatch):
    run, calls, reads, metrics, circuits = chain(monkeypatch, 503, b'')
    with pytest.raises(ProviderFailure, match='PROVIDER_HTTP_FAILURE'):
        run()
    assert calls == ['fixture/primary:provider'] and metrics[-1]['cost'] is None
