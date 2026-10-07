"""Synthetic governed HF fallback boundaries; no credentials or network calls."""
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from app import cloud_execution as cloud
from app.provider_runtime import ChatCompletionProvider, HuggingFaceProvider, ProviderFailure
from app.provider_circuit import ProviderCircuits


def stream_response():
    events = [
        {'choices': [{'index': 0, 'delta': {'content': 'verified fixture answer'}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
        {'choices': [], 'usage': {'prompt_tokens': 8, 'completion_tokens': 3}},
    ]
    return ''.join('data: ' + json.dumps(item) + '\n\n' for item in events) + 'data: [DONE]\n\n'


def setup_chain(monkeypatch, tmp_path, *, non_hf=False, primary_failure='capacity'):
    monkeypatch.setattr(cloud,'PROVIDER_CIRCUITS',ProviderCircuits())
    base = {'enabled': True, 'qualification_status': 'QUALIFIED', 'location': 'cloud',
            'tier': 'MINI', 'context_tokens': 4096, 'output_tokens': 64,
            'input_usd_million': '0.1', 'output_usd_million': '0.5',
            'provider_kind': 'huggingface', 'endpoint': HuggingFaceProvider.ENDPOINT,
            'secret_ref': 'env:HF_TOKEN', 'max_retries': 0}
    primary = {**base, 'id': 'hf-primary', 'model': 'fixture/primary:provider',
               'fallback_ids': ['alternate'], 'hf_fallback_policy': {
                   'version': 'hf-fallback.v1', 'allowed_provider_ids': ['alternate'],
                   'allow_non_hf': non_hf}}
    alternate = {**base, 'id': 'alternate', 'model': 'fixture/alternate:provider'}
    if non_hf:
        alternate.update(provider_kind='chat_completions', endpoint='https://alternate.invalid/chat',
                         secret_ref='env:ALTERNATE_TOKEN', model='alternate-fixture')
    entries = [primary, alternate]
    calls = []
    credential_refs = []
    actions = []
    before_failure = []

    def resolve(ref):
        credential_refs.append(ref)
        return 'hf-fixture-secret' if ref == 'env:HF_TOKEN' else 'alternate-fixture-secret'

    def handler(request):
        is_primary = json.loads(request.content)['model'] == primary['model']
        calls.append('hf-primary' if is_primary else 'alternate')
        if not is_primary:
            if non_hf:
                assert request.url.host == 'alternate.invalid'
                assert request.headers['Authorization'] == 'Bearer alternate-fixture-secret'
            return httpx.Response(200, text=stream_response())
        for callback in before_failure:
            callback()
        if primary_failure == 'capacity':
            return httpx.Response(503, json={'error': {'code': 'model_at_capacity'}})
        if primary_failure == 'credential':
            pytest.fail('missing primary credential must fail before HTTP')
        if primary_failure == 'timeout':
            raise httpx.ReadTimeout('private-fixture', request=request)
        if primary_failure == 'transport':
            raise httpx.ConnectError('private-fixture', request=request)
        if primary_failure == 'partial':
            return httpx.Response(200, text='data: '+json.dumps({'choices': [
                {'index': 0, 'delta': {'content': 'partial'}}]})+'\n\n')
        return httpx.Response(500)

    def fixture_adapter(entry):
        # Keep production credential/host checks; only inject synthetic transport.
        if entry['provider_kind'] != 'huggingface' and entry['secret_ref'] in {'env:HF_TOKEN', 'file:HF_TOKEN'}:
            return real_adapter(entry)
        resolver = (lambda _: None) if primary_failure == 'credential' and entry is primary else resolve
        if entry['provider_kind'] == 'huggingface':
            return HuggingFaceProvider(entry['secret_ref'], secret_resolver=resolver,
                                      transport=httpx.MockTransport(handler))
        return ChatCompletionProvider(entry['endpoint'], entry['secret_ref'], secret_resolver=resolver,
                                      transport=httpx.MockTransport(handler))

    real_adapter = cloud.adapter_for
    monkeypatch.setattr(cloud, 'load_catalog', lambda: entries)
    monkeypatch.setattr(cloud, 'adapter_for', fixture_adapter)
    monkeypatch.setattr(cloud, 'action_ledger', lambda: None)
    def execute(self, action, operation):
        actions.append(action)
        return operation()
    monkeypatch.setattr(cloud.DirectExecutor, 'execute', execute)
    job = {'id': 'hf-fixture-job', 'agent': 'a20', 'prompt': 'Synthetic fixture objective',
           'preferred_provider': 'hf-primary', 'allow_cloud': 1,
           'data_classification': 'CLOUD_PERMITTED', 'task_class': 'conversation',
           'timeout_seconds': 3, 'estimated_cost_usd': .0001, 'max_cost_usd': .0001}
    def run():
        return cloud.execute_cloud(job, SimpleNamespace(name='hf-primary'), tmp_path, lambda: False)
    def metrics():
        with sqlite3.connect(tmp_path/'compute-ledger.db') as db:
            return json.loads(db.execute('SELECT details FROM reasoning_attempts').fetchone()[0])
    # Expose only a fixture callback, not a production mutation mechanism.
    run.before_failure = before_failure
    return run, calls, credential_refs, actions, primary, alternate, job, metrics


@pytest.mark.parametrize('failure', ['capacity', 'credential'])
def test_explicit_hf_chain_falls_back_and_records_exact_provider(monkeypatch, tmp_path, failure):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(
        monkeypatch, tmp_path, primary_failure=failure)
    result = run()
    assert result['result'] == 'verified fixture answer'
    assert calls == (['hf-primary', 'alternate'] if failure == 'capacity' else ['alternate'])
    detail = metrics()
    code = 'CAPACITY' if failure == 'capacity' else 'CREDENTIAL_UNAVAILABLE'
    assert detail['provider'] == 'alternate' and detail['requested_provider'] == 'hf-primary'
    assert detail['fallback_route'] == [{'provider': 'hf-primary', 'code': code}]
    assert detail['agent_id'] == 'a20' and detail['success'] is True
    assert actions[0].parameters_summary['hf_fallback_policy']['version'] == 'hf-fallback.v1'
    assert actions[0].execution_location=='cloud'
    assert 'fixture-secret' not in json.dumps(detail)


def test_qualified_non_hf_alternate_uses_only_its_own_credential(monkeypatch, tmp_path):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(
        monkeypatch, tmp_path, non_hf=True)
    run()
    assert calls == ['hf-primary', 'alternate']
    assert refs == ['env:HF_TOKEN', 'env:ALTERNATE_TOKEN']


@pytest.mark.parametrize('failure,code', [('timeout', 'PROVIDER_TIMEOUT'),
    ('transport', 'PROVIDER_TRANSPORT_FAILURE'), ('partial', 'INCOMPLETE_STREAM'),
    ('http500', 'PROVIDER_HTTP_FAILURE')])
def test_ambiguous_or_partial_hf_failure_does_not_replay(monkeypatch, tmp_path, failure, code):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(
        monkeypatch, tmp_path, primary_failure=failure)
    with pytest.raises(ProviderFailure, match=code):
        run()
    assert calls == ['hf-primary']
    assert refs == ['env:HF_TOKEN']
    assert metrics()['success'] is False


@pytest.mark.parametrize('field,value,code', [
    ('qualification_status', 'UNMEASURED', 'FALLBACK_UNQUALIFIED'),
    ('enabled', False, 'FALLBACK_CONFIGURATION_INVALID'),
    ('tier', 'NANO', 'FALLBACK_POLICY_DENIED'),
    ('output_usd_million', '100', 'HF_BUDGET_NOT_RESERVED'),
])
def test_alternate_cannot_escape_qualification_tier_or_budget(monkeypatch, tmp_path, field, value, code):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(monkeypatch, tmp_path)
    alternate[field] = value
    with pytest.raises(ProviderFailure, match=code):
        run()
    assert 'alternate' not in calls
    if field != 'tier':
        assert calls == [] and refs == []


def test_non_hf_consent_required_before_any_disclosure(monkeypatch, tmp_path):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(monkeypatch, tmp_path, non_hf=True)
    primary['hf_fallback_policy']['allow_non_hf'] = False
    with pytest.raises(ProviderFailure, match='HF_NON_HF_FALLBACK_NOT_PERMITTED'):
        run()
    assert calls == [] and refs == []


@pytest.mark.parametrize('mutation', ['qualification', 'cost', 'consent', 'locality'])
def test_alternate_revalidated_after_primary_failure(monkeypatch, tmp_path, mutation):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(monkeypatch, tmp_path, non_hf=True)
    def change():
        if mutation == 'qualification':
            alternate['qualification_status'] = 'UNMEASURED'
        elif mutation == 'cost':
            alternate['output_usd_million'] = '100'
        elif mutation == 'consent':
            primary['hf_fallback_policy']['allow_non_hf'] = False
        else:
            job['data_classification'] = 'LOCAL_ONLY'
    run.before_failure.append(change)
    with pytest.raises(ProviderFailure, match='FALLBACK_POLICY_DENIED'):
        run()
    assert calls == ['hf-primary'] and refs == ['env:HF_TOKEN']
    assert metrics()['success'] is False


@pytest.mark.parametrize('mutation', ['consent', 'endpoint', 'secret_ref', 'model',
    'price', 'task_budget', 'removed', 'malformed'])
def test_fresh_catalog_changes_deny_prepared_fallback(monkeypatch, tmp_path, mutation):
    from app.compute_catalog import load_catalog
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(
        monkeypatch, tmp_path, non_hf=True)
    catalog_path = tmp_path/'providers.json'
    stored = json.loads(json.dumps({'models': [primary, alternate]}))
    catalog_path.write_text(json.dumps(stored))
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG', str(catalog_path))
    monkeypatch.setattr(cloud, 'load_catalog', load_catalog)
    def change_file():
        fresh_primary, fresh_alternate = stored['models']
        if mutation == 'consent':
            fresh_primary['hf_fallback_policy']['allow_non_hf'] = False
        elif mutation == 'endpoint':
            fresh_alternate['endpoint'] = 'https://changed.invalid/chat'
        elif mutation == 'secret_ref':
            fresh_alternate['secret_ref'] = 'env:NEW_ALTERNATE_TOKEN'
        elif mutation == 'model':
            fresh_alternate['model'] = 'new-alternate-fixture'
        elif mutation == 'price':
            # Still inside the reservation: binding must not silently change.
            fresh_alternate['output_usd_million'] = '0.6'
        elif mutation == 'task_budget':
            fresh_alternate['task_budgets'] = {'conversation': {
                'context_tokens': 2048, 'output_tokens': 32, 'timeout_seconds': 2}}
        elif mutation == 'removed':
            stored['models'].pop()
        else:
            catalog_path.write_text('{')
            return
        catalog_path.write_text(json.dumps(stored))
    run.before_failure.append(change_file)
    with pytest.raises(ProviderFailure, match='FALLBACK_POLICY_DENIED'):
        run()
    assert calls == ['hf-primary'] and refs == ['env:HF_TOKEN']
    assert metrics()['success'] is False


def test_unchanged_fresh_catalog_allows_bound_fallback(monkeypatch, tmp_path):
    from app.compute_catalog import load_catalog
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(
        monkeypatch, tmp_path, non_hf=True)
    catalog_path = tmp_path/'providers.json'
    catalog_path.write_text(json.dumps({'models': [primary, alternate]}))
    monkeypatch.setenv('PRIME_PROVIDER_CATALOG', str(catalog_path))
    monkeypatch.setattr(cloud, 'load_catalog', load_catalog)
    run()
    assert calls == ['hf-primary', 'alternate']
    assert refs == ['env:HF_TOKEN', 'env:ALTERNATE_TOKEN']
    assert metrics()['success'] is True


@pytest.mark.parametrize('ref', ['env:HF_TOKEN', 'file:HF_TOKEN'])
def test_hf_secret_reference_cannot_enter_non_hf_host(monkeypatch, tmp_path, ref):
    run, calls, refs, actions, primary, alternate, job, metrics = setup_chain(monkeypatch, tmp_path, non_hf=True)
    alternate['secret_ref'] = ref
    with pytest.raises(ProviderFailure, match='HF_CREDENTIAL_SCOPE_DENIED'):
        run()
    assert calls == [] and refs == []


@pytest.mark.parametrize('ref', ['env:HF_TOKEN', 'file:HF_TOKEN'])
def test_direct_adapter_rejects_hf_secret_for_non_hf_provider(ref):
    with pytest.raises(ProviderFailure, match='HF_CREDENTIAL_SCOPE_DENIED'):
        cloud.adapter_for({'provider_kind': 'chat_completions', 'secret_ref': ref,
                           'endpoint': 'https://alternate.invalid/chat'})
