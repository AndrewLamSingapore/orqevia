"""Synthetic HTTP diagnosis only; no provider, credential or quality proof."""
import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from app import cloud_execution as cloud
from app.outcome_metrics import OutcomeMetrics
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import HuggingFaceProvider, ModelSpec, ProviderFailure, complete


REQUEST_ID = 'synthetic-request-id:123'
FINGERPRINT = hashlib.sha256(REQUEST_ID.encode('ascii')).hexdigest()
MODEL = ModelSpec('fixture/model:provider', 'hf-fixture', 'MINI', 4096, 64)


def adapter(status=500, request_id=REQUEST_ID, body='private body fixture', calls=None):
    def handler(_request):
        if calls is not None:
            calls.append(status)
        headers = {'Authorization': 'Bearer private-header-fixture'}
        if request_id is not None:
            headers['X-Request-Id'] = request_id
        return httpx.Response(status, headers=headers, text=body)
    return HuggingFaceProvider(secret_resolver=lambda _ref: 'synthetic-key-not-real',
        transport=httpx.MockTransport(handler))


def failure(provider, *, retries=0):
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(complete(provider, MODEL, [], output_tokens=4, max_retries=retries))
    return error.value


def test_http_failure_preserves_numeric_status_and_only_request_id_fingerprint():
    calls = []
    error = failure(adapter(calls=calls), retries=2)
    assert error.diagnostics() == {'upstream_http_status': 500, 'upstream_request_id_sha256': FINGERPRINT}
    assert error.code == 'PROVIDER_HTTP_FAILURE' and error.pre_execution is False
    assert error.retryable is False and error.retry_count == 0 and calls == [500]
    assert error.args == ('PROVIDER_HTTP_FAILURE',)
    public = json.dumps(error.diagnostics()) + str(error)
    assert REQUEST_ID not in public and 'private' not in public and 'synthetic-key' not in public


@pytest.mark.parametrize('request_id', [None, '', 'two words', 'Bearer private',
    'https://private.invalid/id', 'password=fixture', 'a' * 129, '\tunsafe'])
def test_unbounded_or_unsafe_request_id_header_is_not_retained(request_id):
    error = failure(adapter(request_id=request_id))
    assert error.diagnostics() == {'upstream_http_status': 500}
    assert error.code == 'PROVIDER_HTTP_FAILURE' and error.pre_execution is False


@pytest.mark.parametrize('field,value', [
    ('upstream_http_status', True), ('upstream_http_status', '500'),
    ('upstream_http_status', 99), ('upstream_http_status', 600),
    ('upstream_http_status', float('nan')), ('upstream_http_status', 500.0),
    ('upstream_request_id_sha256', REQUEST_ID), ('upstream_request_id_sha256', 'a' * 63),
    ('upstream_request_id_sha256', 'A' * 64), ('upstream_request_id_sha256', True),
])
def test_invalid_optional_failure_metadata_is_dropped_without_changing_failure(field, value):
    error = ProviderFailure('CAPACITY', True, 2, pre_execution=True, **{field: value})
    assert error.diagnostics() == {}
    assert error.code == 'CAPACITY' and error.pre_execution is True
    assert error.retryable is True and error.retry_after == 2 and error.args == ('CAPACITY',)


def test_legacy_failure_has_no_metadata_and_mutated_attributes_are_revalidated():
    error = ProviderFailure('CREDENTIAL_UNAVAILABLE', pre_execution=True)
    assert error.diagnostics() == {} and error.pre_execution is True
    error.upstream_http_status = 'private upstream value'
    error.upstream_request_id_sha256 = 'private raw id'
    assert error.diagnostics() == {}


@pytest.mark.parametrize('status,body,code,pre', [
    (401, 'private', 'AUTHENTICATION', False), (403, 'private', 'AUTHENTICATION', False),
    (404, 'private', 'PROVIDER_HTTP_FAILURE', False),
    (429, '', 'RATE_LIMIT', True), (503, '', 'PROVIDER_HTTP_FAILURE', False),
    (503, '{"error":{"code":"model_at_capacity"}}', 'CAPACITY', True),
    (200, 'data: invalid\n\n', 'MALFORMED_STREAM', False),
])
def test_metadata_never_reclassifies_rejection_or_authorizes_retry(status, body, code, pre):
    error = failure(adapter(status=status, body=body))
    assert error.code == code and error.pre_execution is pre
    assert error.diagnostics() == {'upstream_http_status': status, 'upstream_request_id_sha256': FINGERPRINT}
    assert error.retry_count == 0


def test_cloud_failure_persists_only_safe_diagnosis_and_unknown_cost(monkeypatch, tmp_path):
    entry = dict(id='hf-fixture', provider_kind='huggingface', enabled=True,
        qualification_status='QUALIFIED', location='cloud', tier='MINI',
        model=MODEL.name, context_tokens=4096, output_tokens=64,
        input_usd_million=.09, output_usd_million=.55, max_retries=0)
    monkeypatch.setattr(cloud, 'load_catalog', lambda: [entry])
    monkeypatch.setattr(cloud, 'adapter_for', lambda _entry: adapter())
    monkeypatch.setattr(cloud, 'PROVIDER_CIRCUITS', ProviderCircuits())
    monkeypatch.setattr(cloud, 'action_ledger', lambda: None)
    monkeypatch.setattr(cloud.DirectExecutor, 'execute', lambda self, _action, operation: operation())
    job = dict(id='synthetic-metadata-job', agent='a19', prompt='PUBLIC SYNTHETIC metadata fixture',
        preferred_provider=entry['id'], allow_cloud=1, data_classification='CLOUD_PERMITTED',
        task_class='planning', estimated_cost_usd=.001, max_cost_usd=.001, max_retries=0, timeout_seconds=3)
    with pytest.raises(ProviderFailure, match='PROVIDER_HTTP_FAILURE'):
        cloud.execute_cloud(job, SimpleNamespace(name=entry['id']), tmp_path, lambda: False)
    with sqlite3.connect(tmp_path / 'compute-ledger.db') as db:
        tokens, cost, verified, raw = db.execute('SELECT tokens,cost,verified,details FROM reasoning_attempts').fetchone()
    detail = json.loads(raw)
    assert detail['upstream_http_status'] == 500 and detail['upstream_request_id_sha256'] == FINGERPRINT
    assert detail['failure_kind'] == 'PROVIDER_HTTP_FAILURE' and detail['success'] is False
    assert tokens is None and cost is None and verified == 0
    assert REQUEST_ID not in raw and 'private' not in raw and 'synthetic-key' not in raw


@pytest.mark.parametrize('field,value', [
    ('upstream_http_status', False), ('upstream_http_status', '500'),
    ('upstream_http_status', 600), ('upstream_request_id_sha256', REQUEST_ID),
    ('upstream_request_id_sha256', 'A' * 64), ('response_body', 'private'),
])
def test_failure_metrics_reject_raw_or_invalid_diagnostics(field, value, tmp_path):
    metrics = OutcomeMetrics(tmp_path / 'fixture.db')
    with pytest.raises(ValueError):
        metrics.record(attempt_id='fixture', task_id='fixture', task_class='planning',
            tier='MINI', seconds=0, **{field: value})
    with metrics.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM reasoning_attempts').fetchone()[0] == 0
