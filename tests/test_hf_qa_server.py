"""Offline real-queue/transport proof, never live HF or price qualification."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import time
import uuid

from fastapi import HTTPException
import httpx
import pytest

from app import hf_qa_server as server, cloud_execution as cloud
from app.action_records import ActionLedger
from app.hf_serverless import HFServerlessQA
from app.hf_qa_execution import qa_router_prompt
from app.job_queue import JobQueue, Provider, QueuePolicy
from app.provider_circuit import ProviderCircuits
from app.provider_runtime import HuggingFaceProvider, ProviderFailure


CONTEXT = 'My name is Clara and I live in Berkeley.'
SPAN = {'answer': 'Clara', 'score': .97, 'start': 11, 'end': 16}


def _router_response(answer='Clara', *, include_usage=True):
    events = [
        {'choices': [{'index': 0, 'delta': {'content': answer}, 'finish_reason': None}]},
        {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
    ]
    if include_usage:
        events.append({'choices': [], 'usage': {'prompt_tokens': 8, 'completion_tokens': 2}})
    return httpx.Response(200, text=''.join('data: ' + json.dumps(x) + '\n\n' for x in events)
                          + 'data: [DONE]\n\n')


@pytest.fixture
def governed(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'offline-owner-fixture')
    entry = {'id': 'hf-approved', 'provider_kind': 'huggingface', 'location': 'cloud',
        'enabled': True, 'qualification_status': 'QUALIFIED', 'tier': 'MINI',
        'model': 'fixture/span:provider', 'endpoint': HuggingFaceProvider.ENDPOINT,
        'secret_ref': 'env:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 64,
        'input_usd_million': '.1', 'output_usd_million': '.5', 'concurrency': 1,
        'allowed_task_classes': ['question_answering'], 'max_retries': 0,
        'serverless_qa': {'version': 'hf-serverless-qa.price.v1', 'model': HFServerlessQA.MODEL,
            'maximum_charge_usd': '.001', 'price_contract_sha256': 'a' * 64,
            'valid_until_utc': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            'router_fallback': True}}
    catalog = [entry]
    monkeypatch.setattr(server, 'load_catalog', lambda: deepcopy(catalog))
    monkeypatch.setattr(cloud, 'load_catalog', lambda: deepcopy(catalog))
    monkeypatch.setattr(cloud, 'PROVIDER_CIRCUITS', ProviderCircuits())
    q = JobQueue(tmp_path / 'queue.db', QueuePolicy(cloud_wait_seconds=0))
    p = Provider(entry['id'], 'cloud', entry['model'], 0, 0, 1, .1, .5, 64, True)
    calls, credentials = [], []
    direct_response = [httpx.Response(200, json=SPAN)]
    before_direct = []

    def resolve(ref):
        credentials.append(ref)
        return 'offline-secret-fixture'

    def handler(request):
        route = 'direct' if request.url.path.endswith(HFServerlessQA.MODEL) else 'router'
        calls.append(route)
        if route == 'direct':
            for callback in before_direct:
                callback()
            value = direct_response[0]
            if isinstance(value, Exception):
                raise value
            return value
        return _router_response()

    transport = httpx.MockTransport(handler)
    qa = HFServerlessQA('env:HF_TOKEN', secret_resolver=resolve, transport=transport)
    factory = lambda **_kw: qa
    factory.MODEL, factory.CIRCUIT_ID = HFServerlessQA.MODEL, HFServerlessQA.CIRCUIT_ID
    factory.validate_request = HFServerlessQA.validate_request
    monkeypatch.setattr(server, 'HFServerlessQA', factory)
    monkeypatch.setattr(cloud, 'adapter_for', lambda item: HuggingFaceProvider(
        item['secret_ref'], secret_resolver=resolve, transport=transport))
    ledger = ActionLedger(tmp_path / 'actions.jsonl')
    monkeypatch.setattr(cloud, 'action_ledger', lambda: ledger)
    arguments = {'authorization': 'Bearer offline-owner-fixture', 'queue': q, 'data': tmp_path,
        'available_providers': [p], 'provider_id': p.name, 'agent_id': 'a18',
        'task_id': str(uuid.uuid4()), 'context': CONTEXT, 'question': 'What is my name?',
        'data_classification': 'CLOUD_PERMITTED', 'max_cost_usd': '.01'}
    yield arguments, entry, calls, credentials, direct_response, before_direct
    assert ledger.close()


def test_direct_success_retains_unknown_charge_and_cancels_unused_hold(governed):
    arguments, _, calls, credentials, _, _ = governed
    result = server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and credentials == ['env:HF_TOKEN']
    assert result['route'] == 'DIRECT_HF' and result['cost_usd'] is None
    assert result['automatic_qualification'] is False and result['l7_awarded'] is False
    jobs = arguments['queue'].list()
    direct = next(job for job in jobs if job['provider'] == HFServerlessQA.CIRCUIT_ID)
    router = next(job for job in jobs if job['provider'] == 'hf-approved')
    assert direct['status'] == 'completed' and direct['actual_cost_usd'] is None
    assert direct['estimated_cost_usd'] == .001
    assert router['status'] == 'cancelled' and router['actual_cost_usd'] == 0
    assert arguments['queue'].metrics()['daily_spend_usd'] == .001


def test_clean_capacity_rejection_claims_one_real_router_job_and_measures_cost(governed):
    arguments, _, calls, _, responses, _ = governed
    responses[0] = httpx.Response(503, json={'error': {'code': 'model_at_capacity'}})
    result = server.execute_governed_qa(**arguments)
    assert calls == ['direct', 'router'] and result['route'] == 'HF_ROUTER'
    assert result['provider'] == 'hf-approved' and result['model'] == 'fixture/span:provider'
    q = arguments['queue']
    child = q.get(result['router_task_id'])
    direct = q.get(result['reservation_id'])
    assert child['status'] == 'completed' and child['attempts'] == 1
    assert child['max_retries'] == 0 and child['actual_cost_usd'] == .0000018
    assert direct['status'] == 'failed' and direct['actual_cost_usd'] == 0
    assert q.metrics()['daily_spend_usd'] == child['actual_cost_usd']
    with q.connect() as db:
        receipts = [json.loads(row[0]) for row in db.execute(
            "SELECT details_json FROM compute_events WHERE event_type='cloud_reserved'")]
    assert len(receipts) == 2 and receipts[0] == receipts[1]
    assert receipts[0]['parent_task_id'] == arguments['task_id']
    assert receipts[0]['request_binding_sha256'] == result['request_binding_sha256']


@pytest.mark.parametrize('response', [
    httpx.Response(503, json={}), httpx.ReadTimeout('offline'),
    httpx.Response(200, json={**SPAN, 'answer': 'wrong'}),
])
def test_ambiguous_dispatch_never_falls_back_or_releases_unknown_direct_cap(governed, response):
    arguments, _, calls, _, responses, _ = governed
    responses[0] = response
    with pytest.raises(ProviderFailure):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct']
    assert arguments['queue'].metrics()['daily_spend_usd'] == .001
    assert all(job['status'] in {'failed', 'cancelled'} for job in arguments['queue'].list())


@pytest.mark.parametrize('change', ['missing', 'expired', 'model', 'digest', 'zero',
                                   'null_expiry', 'nan_expiry', 'object_expiry', 'nan_charge'])
def test_real_operator_price_contract_is_required_before_credentials_or_reservation(governed, change):
    arguments, entry, calls, credentials, _, _ = governed
    if change == 'missing':
        entry.pop('serverless_qa')
    else:
        key, value = {'expired': ('valid_until_utc', '2020-01-01T00:00:00+00:00'),
            'model': ('model', 'other/model'), 'digest': ('price_contract_sha256', ''),
            'zero': ('maximum_charge_usd', '0'), 'null_expiry': ('valid_until_utc', None),
            'nan_expiry': ('valid_until_utc', float('nan')), 'object_expiry': ('valid_until_utc', {}),
            'nan_charge': ('maximum_charge_usd', 'NaN')}[change]
        entry['serverless_qa'][key] = value
    with pytest.raises(ProviderFailure, match='QA_PRICE_CONTRACT_UNAVAILABLE'):
        server.execute_governed_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_owner_authority_precedes_catalog_and_reservation(governed):
    arguments, entry, calls, credentials, _, _ = governed
    arguments['authorization'] = 'Bearer wrong-fixture'
    entry.pop('serverless_qa')
    with pytest.raises(HTTPException) as failure:
        server.execute_governed_qa(**arguments)
    assert failure.value.status_code == 401
    assert not calls and not credentials and not arguments['queue'].list()


def test_existing_scope_and_combined_daily_budget_deny_before_disclosure(governed):
    arguments, entry, calls, credentials, _, _ = governed
    entry['allowed_task_classes'] = ['coding']
    with pytest.raises(ProviderFailure, match='PROVIDER_UNQUALIFIED'):
        server.execute_governed_qa(**arguments)
    entry['allowed_task_classes'] = ['question_answering']
    arguments['queue'].policy = replace(arguments['queue'].policy, daily_cost_ceiling_usd=.001)
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_direct_qa_cannot_borrow_classification_only_qualification(governed):
    arguments, entry, calls, credentials, _, _ = governed
    entry['allowed_task_classes'] = ['classification']
    with pytest.raises(ProviderFailure, match='PROVIDER_UNQUALIFIED'):
        server.execute_governed_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


@pytest.mark.parametrize('fallback', [False, True])
def test_direct_qa_persists_question_answering_scope_for_entire_chain(governed, fallback):
    arguments, entry, calls, credentials, direct_response, _ = governed
    entry['serverless_qa']['router_fallback'] = fallback
    if fallback:
        direct_response[0] = httpx.Response(429, json={})
    result = server.execute_governed_qa(**arguments)
    assert result['answer'] == 'Clara'
    jobs = arguments['queue'].list()
    assert len(jobs) == (2 if fallback else 1)
    assert all(job['task_class'] == 'question_answering' for job in jobs)
    assert calls == (['direct', 'router'] if fallback else ['direct'])


def test_backpressure_does_not_read_credentials_or_increase_global_slots(governed):
    arguments, _, calls, credentials, _, _ = governed
    q, p = arguments['queue'], arguments['available_providers'][0]
    busy = q.submit(agent='a20', prompt='occupied', model=p.model, preferred_provider=p.name,
        allow_cloud=True, data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('fixture-worker', [p])['id'] == busy['id']
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_qa(**arguments)
    assert not calls and not credentials
    assert q.metrics()['policy']['global_concurrency'] == 1
    assert len(q.metrics()['running']) == 1


def test_catalog_change_after_rejection_denies_router_credentials(governed):
    arguments, entry, calls, credentials, responses, before = governed
    responses[0] = httpx.Response(429, json={})
    before.append(lambda: entry.update(model='fixture/changed:provider'))
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and len(credentials) == 1
    assert arguments['queue'].metrics()['daily_spend_usd'] == 0


def test_cancellation_after_dispatch_never_replays_and_retains_cap(governed):
    arguments, _, calls, _, _, before = governed
    q = arguments['queue']
    before.append(lambda: q.cancel(q.metrics()['running'][0]['id']))
    with pytest.raises(ProviderFailure, match='CANCELLED'):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and q.metrics()['daily_spend_usd'] == .001


def test_same_task_cannot_create_a_second_paid_chain(governed):
    arguments, _, calls, credentials, _, _ = governed
    server.execute_governed_qa(**arguments)
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and len(credentials) == 1
    assert len(arguments['queue'].list()) == 2


def test_open_direct_circuit_uses_only_separately_reserved_hf_alternate(governed, monkeypatch):
    arguments, _, calls, credentials, _, _ = governed
    circuits = ProviderCircuits(failure_threshold=1)
    circuits.fail(circuits.acquire(HFServerlessQA.CIRCUIT_ID), 'CAPACITY', pre_execution=True)
    monkeypatch.setattr(cloud, 'PROVIDER_CIRCUITS', circuits)
    result = server.execute_governed_qa(**arguments)
    assert calls == ['router'] and credentials == ['env:HF_TOKEN']
    assert result['fallback_failures'][0]['code'] == 'PROVIDER_CIRCUIT_OPEN'
    assert arguments['queue'].get(result['reservation_id'])['actual_cost_usd'] == 0


def test_router_catalog_drift_denies_before_a_second_credential(governed, monkeypatch):
    arguments, entry, calls, credentials, responses, _ = governed
    responses[0] = httpx.Response(429, json={})
    monkeypatch.setattr(cloud, 'load_catalog', lambda: [{**entry, 'model': 'fixture/drift:provider'}])
    with pytest.raises(ProviderFailure, match='QA_CATALOG_CHANGED'):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and len(credentials) == 1
    jobs = arguments['queue'].list()
    router = next(job for job in jobs if job['provider'] == 'hf-approved')
    direct = next(job for job in jobs if job['provider'] == HFServerlessQA.CIRCUIT_ID)
    assert direct['actual_cost_usd'] == 0
    # The alternate executor was entered: absent per-attempt billing proof,
    # conservatively retain its unknown reserve rather than trust a final flag.
    assert router['actual_cost_usd'] is None
    assert arguments['queue'].metrics()['daily_spend_usd'] == router['estimated_cost_usd']


def test_api_uses_server_authority_and_rejects_request_callbacks_and_contracts(governed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    arguments, _, calls, credentials, _, _ = governed
    # A first import may create its queue: explicitly isolate that path too.
    monkeypatch.setenv('PRIME_DATA_DIR', str(arguments['data']))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(arguments['data'] / 'import-queue.db'))
    monkeypatch.delenv('PRIME_PROVIDER_CATALOG', raising=False)
    from app import compute_queue_api as api
    monkeypatch.setattr(api, 'queue', arguments['queue'])
    monkeypatch.setattr(api, 'DATA', arguments['data'])
    monkeypatch.setattr(api, 'providers', lambda: arguments['available_providers'])
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    body = {key: arguments[key] for key in ('provider_id', 'agent_id', 'task_id',
        'context', 'question', 'data_classification', 'max_cost_usd')}
    assert client.post('/api/compute-queue/hf/qa', json=body).status_code == 401
    for field in ('admit', 'execute_hf_router', 'record_direct_rejection',
                  'serverless_qa', 'price_contract_sha256'):
        response = client.post('/api/compute-queue/hf/qa', json={**body, field: 'forged'},
                               headers={'Authorization': arguments['authorization']})
        assert response.status_code == 422
    for duration in (None, True, float('nan'), float('inf')):
        response = client.post('/api/compute-queue/hf/qa',
            content=json.dumps({**body, 'timeout_seconds': duration}), headers={
                'Authorization': arguments['authorization'], 'Content-Type': 'application/json'})
        assert response.status_code == 422
    assert not calls and not credentials and not arguments['queue'].list()
    response = client.post('/api/compute-queue/hf/qa', json=body,
                           headers={'Authorization': arguments['authorization']})
    assert response.status_code == 200 and calls == ['direct']


def test_held_caps_count_for_other_admission_and_expire_only_if_undispatched(tmp_path):
    q = JobQueue(tmp_path / 'held.db', QueuePolicy(cloud_wait_seconds=0, daily_cost_ceiling_usd=.015))
    p = Provider('fixed', 'cloud', 'fixed/model', 0, 0, 1, maximum_charge_usd='.01')
    held = q.reserve_cloud_chain(agent='a18', requests=[{'provider': p, 'prompt': 'public',
        'max_cost_usd': '.01'}], timeout_seconds=1, binding={'parent_task_id': str(uuid.uuid4())})[0]
    assert q.claim('ordinary', [p]) is None
    other = q.submit(agent='a20', prompt='public', model=p.model, allow_cloud=True,
        data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('ordinary', [p]) is None and q.get(other['id'])['status'] == 'budget_blocked'
    with q.connect() as db:
        db.execute('UPDATE compute_jobs SET lease_until=? WHERE id=?', (time.time() - 1, held['id']))
    assert q.claim('late', [p], held_job_id=held['id']) is None
    assert q.recover_expired() == 1
    assert q.get(held['id'])['actual_cost_usd'] == 0


def test_cloud_limit_is_bounded_independent_of_measured_global_policy(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_CLOUD_REQUEST_CAPACITY', '100')
    assert QueuePolicy.from_env().cloud_concurrency == 4
    monkeypatch.setenv('PRIME_CLOUD_REQUEST_CAPACITY', 'invalid')
    assert QueuePolicy.from_env().cloud_concurrency == 1
    q = JobQueue(tmp_path / 'bounded.db', QueuePolicy(global_concurrency=3, cloud_concurrency=1,
                                                     cloud_wait_seconds=0))
    p = Provider('hf', 'cloud', 'fixture/model:provider', 0, 0, 4, maximum_charge_usd='.001')
    for agent in ('a18', 'a20'):
        q.submit(agent=agent, prompt='public', model=p.model, allow_cloud=True,
                 data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('first', [p]) is not None and q.claim('second', [p]) is None
    assert len(q.metrics()['running']) == 1


def test_cancelled_cloud_request_occupies_capacity_until_worker_finishes(tmp_path):
    policy = QueuePolicy(global_concurrency=2, cloud_concurrency=1, cloud_wait_seconds=0)
    q = JobQueue(tmp_path / 'cancelled-inflight.db', policy)
    p = Provider('hf', 'cloud', 'fixture/model:provider', 0, 0, 2, maximum_charge_usd='.001')
    first = q.submit(agent='a18', prompt='public', model=p.model, allow_cloud=True,
                     data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('first', [p])['id'] == first['id']
    q.cancel(first['id'])
    second = q.submit(agent='a20', prompt='public', model=p.model, allow_cloud=True,
                      data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    # Another process must see pending HTTP cleanup even after status cancellation.
    observer = JobQueue(q.db_path, policy)
    assert observer.claim('second', [p]) is None
    assert q.get(second['id'])['status'] == 'queued'
    settled = q.finish(first['id'], error='CANCELLED', actual_cost_usd=None,
                       input_tokens=None, output_tokens=None, retryable=False)
    assert settled['status'] == 'cancelled' and settled['actual_cost_usd'] is None
    assert q.metrics()['daily_spend_usd'] == .001
    assert observer.claim('after-cleanup', [p])['id'] == second['id']


@pytest.mark.parametrize('cancelled', [False, True])
def test_lease_expiry_cannot_release_unsettled_cloud_request_or_unknown_cost(tmp_path, cancelled):
    policy = QueuePolicy(global_concurrency=2, cloud_concurrency=1, cloud_wait_seconds=0)
    q = JobQueue(tmp_path / 'expired-cloud.db', policy)
    p = Provider('hf', 'cloud', 'fixture/model:provider', 0, 0, 2, maximum_charge_usd='.001')
    first = q.submit(agent='a18', prompt='public', model=p.model, allow_cloud=True,
                     data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    q.claim('first', [p])
    if cancelled:
        q.cancel(first['id'])
    with q.connect() as db:
        db.execute('UPDATE compute_jobs SET lease_until=? WHERE id=?', (time.time() - 1, first['id']))
    q.recover_expired()
    uncertain = q.get(first['id'])
    assert uncertain['status'] == ('cancelled' if cancelled else 'failed')
    assert uncertain['cloud_inflight'] == 1 and uncertain['actual_cost_usd'] is None
    assert uncertain['provider'] == p.name
    second = q.submit(agent='a20', prompt='public', model=p.model, allow_cloud=True,
                      data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('second', [p]) is None
    assert len(q.metrics()['cloud_inflight']) == 1 and q.metrics()['daily_spend_usd'] == .001
    # Only this late trusted executor callback proves its client cleanup ended.
    q.finish(first['id'], error='CANCELLED' if cancelled else 'PROVIDER_TIMEOUT',
             actual_cost_usd=None, input_tokens=None, output_tokens=None, retryable=False)
    assert q.get(first['id'])['cloud_inflight'] == 0
    assert q.metrics()['daily_spend_usd'] == .001
    assert q.claim('after-proved-cleanup', [p])['id'] == second['id']


@pytest.mark.parametrize('legacy_provider', [None, 'ollama-fast'])
def test_legacy_unknown_dispatch_retains_cloud_slot_despite_local_name_collision(tmp_path, legacy_provider):
    policy = QueuePolicy(global_concurrency=2, cloud_concurrency=1, cloud_wait_seconds=0)
    q = JobQueue(tmp_path / 'legacy.db', policy)
    cloud_provider = Provider('hf', 'cloud', 'fixture/model:provider', 0, 0, 2,
                              maximum_charge_usd='.001')
    local_provider = Provider('ollama-fast', 'local', 'local/model', 32768, 0, 2)
    first = q.submit(agent='a18', prompt='public', model=cloud_provider.model,
        allow_cloud=True, data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    q.claim('first', [cloud_provider])
    with q.connect() as db:
        db.execute('UPDATE compute_jobs SET provider=? WHERE id=?', (legacy_provider, first['id']))
        db.execute('ALTER TABLE compute_jobs DROP COLUMN cloud_inflight')
    observer = JobQueue(q.db_path, policy)
    assert observer.get(first['id'])['cloud_inflight'] == 1
    observer.cancel(first['id'])
    second = observer.submit(agent='a20', prompt='public', model=cloud_provider.model,
        allow_cloud=True, data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert observer.claim('second', [local_provider, cloud_provider]) is None
    assert observer.get(second['id'])['status'] == 'queued'
    assert observer.metrics()['daily_spend_usd'] == .001


def test_post_dispatch_cancellation_state_fault_cannot_zero_direct_charge(governed, monkeypatch):
    arguments, _, calls, _, _, before = governed
    q = arguments['queue']
    original_get = q.get
    fault = {'armed': False, 'remaining': 1}
    before.append(lambda: fault.update(armed=True))
    def get(job_id):
        if fault['armed'] and fault['remaining']:
            fault['remaining'] -= 1
            raise RuntimeError('synthetic temporary queue read fault')
        return original_get(job_id)
    monkeypatch.setattr(q, 'get', get)
    with pytest.raises(ProviderFailure, match='CANCELLATION_STATE_UNAVAILABLE'):
        server.execute_governed_qa(**arguments)
    assert calls == ['direct'] and q.metrics()['daily_spend_usd'] == .001
    assert not q.metrics()['cloud_inflight']  # Actual coroutine cleanup completed.


@pytest.mark.parametrize('phase', ['direct', 'router'])
def test_contract_expiring_during_target_claim_denies_before_phase_credentials(governed, monkeypatch, phase):
    arguments, entry, calls, credentials, responses, _ = governed
    q, original_claim = arguments['queue'], arguments['queue'].claim
    clock = {'expired': False}
    expiry = datetime.fromisoformat(entry['serverless_qa']['valid_until_utc'])
    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, timezone=None):
            return expiry + timedelta(seconds=1) if clock['expired'] else datetime.now(timezone)
    def claim(worker_id, *args, **kwargs):
        job = original_claim(worker_id, *args, **kwargs)
        if worker_id == 'hf-qa-' + phase:
            clock['expired'] = True
        return job
    monkeypatch.setattr(server, 'datetime', ControlledDateTime)
    monkeypatch.setattr(q, 'claim', claim)
    if phase == 'router':
        responses[0] = httpx.Response(429, json={})
    with pytest.raises(ProviderFailure):
        server.execute_governed_qa(**arguments)
    assert calls == ([] if phase == 'direct' else ['direct'])
    assert len(credentials) == (0 if phase == 'direct' else 1)
    assert q.metrics()['daily_spend_usd'] == 0 and not q.metrics()['cloud_inflight']


def test_clean_direct_rejection_without_alternate_records_zero(governed):
    arguments, entry, calls, _, responses, _ = governed
    entry['serverless_qa']['router_fallback'] = False
    responses[0] = httpx.Response(429, json={})
    with pytest.raises(ProviderFailure, match='RATE_LIMIT'):
        server.execute_governed_qa(**arguments)
    jobs = arguments['queue'].list()
    assert calls == ['direct'] and len(jobs) == 1
    assert jobs[0]['actual_cost_usd'] == 0 and not jobs[0]['cloud_inflight']


def _api_client(governed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    arguments = governed[0]
    monkeypatch.setenv('PRIME_DATA_DIR', str(arguments['data']))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(arguments['data'] / 'api-import.db'))
    monkeypatch.delenv('PRIME_PROVIDER_CATALOG', raising=False)
    from app import compute_queue_api as api
    monkeypatch.setattr(api, 'queue', arguments['queue'])
    monkeypatch.setattr(api, 'DATA', arguments['data'])
    monkeypatch.setattr(api, 'providers', lambda: arguments['available_providers'])
    app = FastAPI()
    app.include_router(api.router)
    body = {key: arguments[key] for key in ('provider_id', 'agent_id', 'task_id',
        'context', 'question', 'data_classification', 'max_cost_usd')}
    return TestClient(app, raise_server_exceptions=False), body


@pytest.mark.parametrize('field', ['context', 'question'])
def test_invalid_unicode_is_sanitized_before_reservation(governed, monkeypatch, field):
    arguments, _, calls, credentials, _, _ = governed
    client, body = _api_client(governed, monkeypatch)
    body[field] = '\ud800'
    response = client.post('/api/compute-queue/hf/qa', content=json.dumps(body),
        headers={'Authorization': arguments['authorization'], 'Content-Type': 'application/json'})
    assert response.status_code == 422 and response.json() == {'detail': 'INVALID_QA_REQUEST'}
    assert not calls and not credentials and not arguments['queue'].list()


@pytest.mark.parametrize('denial', ['request_cap', 'daily', 'replay'])
def test_budget_and_replay_api_failures_are_sanitized(governed, monkeypatch, denial):
    arguments, _, calls, credentials, _, _ = governed
    client, body = _api_client(governed, monkeypatch)
    if denial == 'request_cap':
        body['max_cost_usd'] = '.0001'
    elif denial == 'daily':
        arguments['queue'].policy = replace(arguments['queue'].policy, daily_cost_ceiling_usd=.001)
    else:
        assert client.post('/api/compute-queue/hf/qa', json=body,
            headers={'Authorization': arguments['authorization']}).status_code == 200
    response = client.post('/api/compute-queue/hf/qa', json=body,
                           headers={'Authorization': arguments['authorization']})
    assert response.status_code == 503 and response.json() == {'detail': 'QA_BUDGET_NOT_RESERVED'}
    assert len(calls) == len(credentials) == (1 if denial == 'replay' else 0)


@pytest.mark.parametrize('field', ['context', 'question'])
def test_server_input_byte_validation_precedes_prompt_sizing(governed, field):
    arguments, _, calls, credentials, _, _ = governed
    arguments[field] = '\ud800'
    with pytest.raises(ProviderFailure, match='INVALID_QA_INPUT'):
        server.execute_governed_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


@pytest.fixture
def router_only(governed, monkeypatch):
    arguments, entry, calls, credentials, _, _ = governed
    entry.pop('serverless_qa')
    entry['allowed_task_classes'] = ['question_answering']
    responses, before = [_router_response()], []
    def handler(request):
        calls.append('router')
        payload = json.loads(request.content)
        assert payload['model'] == entry['model'] and payload['max_tokens'] == entry['output_tokens']
        assert payload['messages'][0]['content'] == qa_router_prompt(arguments['context'], arguments['question'])
        for callback in before:
            callback()
        if isinstance(responses[0], Exception):
            raise responses[0]
        return responses[0]
    def resolve(ref):
        credentials.append(ref)
        return 'offline-secret-fixture'
    def no_direct(**_kwargs):
        pytest.fail('Router-only QA must never instantiate the direct adapter')
    no_direct.validate_request = HFServerlessQA.validate_request
    no_direct.MODEL, no_direct.CIRCUIT_ID = HFServerlessQA.MODEL, HFServerlessQA.CIRCUIT_ID
    monkeypatch.setattr(server, 'HFServerlessQA', no_direct)
    monkeypatch.setattr(cloud, 'adapter_for', lambda item: HuggingFaceProvider(
        item['secret_ref'], secret_resolver=resolve, transport=httpx.MockTransport(handler)))
    return arguments, entry, calls, credentials, responses, before


def test_router_only_uses_one_metered_reservation_without_direct_contract(router_only):
    arguments, _, calls, credentials, _, _ = router_only
    result = server.execute_governed_router_qa(**arguments)
    assert calls == ['router'] and credentials == ['env:HF_TOKEN']
    assert result['route'] == 'HF_ROUTER_QA' and result['direct_qa_attempted'] is False
    assert result['answer'] == 'Clara' and result['model'] == 'fixture/span:provider'
    assert result['cost_usd'] == .0000018 and result['cost_measurement'] == 'USAGE_X_CATALOG_RATES_NOT_INVOICE'
    assert result['quality_oracle'] == 'CALLER_VERIFICATION_REQUIRED'
    assert not result['automatic_qualification'] and not result['l7_awarded']
    jobs = arguments['queue'].list()
    assert len(jobs) == 1 and jobs[0]['id'] == result['reservation_id'] == result['router_task_id']
    assert jobs[0]['task_class'] == 'question_answering' and jobs[0]['agent'] == arguments['agent_id']
    assert jobs[0]['prompt'] == qa_router_prompt(arguments['context'], arguments['question'])
    assert jobs[0]['status'] == 'completed' and jobs[0]['actual_cost_usd'] == result['cost_usd']
    assert jobs[0]['attempts'] == 1 and jobs[0]['max_retries'] == 0 and not jobs[0]['cloud_inflight']


@pytest.mark.parametrize('agent', ['prime', 'A18', 'A12', 'a999'])
def test_router_only_rejects_alias_or_non_permanent_owner_before_reservation(router_only, agent):
    arguments, _, calls, credentials, _, _ = router_only
    arguments['agent_id'] = agent
    with pytest.raises(ProviderFailure, match='QA_REQUEST_IDENTITY_OR_BUDGET_INVALID'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_router_only_requires_owner_authority_before_input_or_catalog(router_only):
    arguments, _, calls, credentials, _, _ = router_only
    arguments.update(authorization='Bearer wrong-fixture', context='')
    with pytest.raises(HTTPException) as failure:
        server.execute_governed_router_qa(**arguments)
    assert failure.value.status_code == 401
    assert not calls and not credentials and not arguments['queue'].list()


@pytest.mark.parametrize('scope', ['classification_only', 'wrong_prompt', 'wrong_agent'])
def test_router_only_does_not_inherit_unrelated_task_prompt_or_owner_scope(router_only, scope):
    arguments, entry, calls, credentials, _, _ = router_only
    if scope == 'classification_only':
        entry['allowed_task_classes'] = ['classification']
    else:
        entry['allowed_prompt_bindings'] = [{'agent': 'a20' if scope == 'wrong_agent' else 'a18',
            'prompt_sha256': server._digest('not-the-fixed-qa-prompt')}]
        if scope == 'wrong_agent':
            entry['allowed_prompt_bindings'][0]['prompt_sha256'] = server.hashlib.sha256(
                qa_router_prompt(arguments['context'], arguments['question']).encode()).hexdigest()
    with pytest.raises(ProviderFailure, match='PROVIDER_UNQUALIFIED'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_router_only_honors_exact_original_prompt_and_agent_scope(router_only):
    arguments, entry, _, _, _, _ = router_only
    entry['allowed_prompt_bindings'] = [{'agent': arguments['agent_id'],
        'prompt_sha256': server.hashlib.sha256(qa_router_prompt(arguments['context'], arguments['question']).encode()).hexdigest()}]
    result = server.execute_governed_router_qa(**arguments)
    assert result['task_class'] == 'question_answering' and result['answer'] == 'Clara'


@pytest.mark.parametrize('denial', ['request', 'daily'])
def test_router_only_cost_denial_happens_before_credentials(router_only, denial):
    arguments, _, calls, credentials, _, _ = router_only
    if denial == 'request':
        arguments['max_cost_usd'] = '.000000001'
    else:
        arguments['queue'].policy = replace(arguments['queue'].policy, daily_cost_ceiling_usd=.000000001)
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_router_only_parent_task_replay_never_creates_a_second_request(router_only):
    arguments, _, calls, credentials, _, _ = router_only
    server.execute_governed_router_qa(**arguments)
    with pytest.raises(ProviderFailure, match='QA_BUDGET_NOT_RESERVED'):
        server.execute_governed_router_qa(**arguments)
    assert calls == ['router'] and len(credentials) == 1 and len(arguments['queue'].list()) == 1


def test_router_only_cancellation_before_executor_is_proven_unspent(router_only, monkeypatch):
    arguments, _, calls, credentials, _, _ = router_only
    q, original_claim = arguments['queue'], arguments['queue'].claim
    def claim(*args, **kwargs):
        job = original_claim(*args, **kwargs)
        q.cancel(job['id'])
        return job
    monkeypatch.setattr(q, 'claim', claim)
    with pytest.raises(ProviderFailure, match='CANCELLED'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials
    job = q.list()[0]
    assert job['status'] == 'cancelled' and job['actual_cost_usd'] == 0 and not job['cloud_inflight']


@pytest.mark.parametrize('reported_usage', [False, True])
def test_router_only_cancelled_request_stays_occupied_until_real_client_cleanup(router_only, reported_usage):
    arguments, _, calls, _, responses, before = router_only
    if not reported_usage:
        responses[0] = httpx.ReadTimeout('offline cancellation race')
    q, p = arguments['queue'], arguments['available_providers'][0]
    def cancel_during_http():
        job = q.list()[0]
        q.cancel(job['id'])
        assert q.get(job['id'])['cloud_inflight'] == 1
        q.submit(agent='a20', prompt='public', model=p.model, preferred_provider=p.name,
            allow_cloud=True, data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
        assert q.claim('overlap-denied', [p]) is None
    before.append(cancel_during_http)
    with pytest.raises(ProviderFailure):
        server.execute_governed_router_qa(**arguments)
    job = next(job for job in q.list() if job['agent'] == 'a18')
    assert calls == ['router'] and job['status'] == 'cancelled'
    assert job['actual_cost_usd'] == (.0000018 if reported_usage else None)
    assert not job['cloud_inflight'] and q.metrics()['daily_spend_usd'] == (
        .0000018 if reported_usage else job['estimated_cost_usd'])


@pytest.mark.parametrize('failure', ['ambiguous', 'missing_usage', 'invalid_span'])
def test_router_only_controlled_failure_never_retries_or_erases_spend(router_only, failure):
    arguments, _, calls, _, responses, _ = router_only
    responses[0] = {'ambiguous': httpx.Response(503, json={}),
        'missing_usage': _router_response(include_usage=False),
        'invalid_span': _router_response('not-in-context')}[failure]
    with pytest.raises(ProviderFailure):
        server.execute_governed_router_qa(**arguments)
    job = arguments['queue'].list()[0]
    assert calls == ['router'] and job['status'] == 'failed' and not job['cloud_inflight']
    assert job['actual_cost_usd'] == (.0000018 if failure == 'invalid_span' else None)
    assert arguments['queue'].metrics()['daily_spend_usd'] == (
        .0000018 if failure == 'invalid_span' else job['estimated_cost_usd'])


@pytest.mark.parametrize('point', ['claim', 'dispatch'])
def test_router_only_original_deadline_covers_claim_wait_and_output(router_only, monkeypatch, point):
    arguments, _, calls, credentials, _, before = router_only
    clock = [100]
    monkeypatch.setattr(server, 'monotonic', lambda: clock[0])
    if point == 'claim':
        original_claim = arguments['queue'].claim
        def claim(*args, **kwargs):
            job = original_claim(*args, **kwargs)
            clock[0] = 131
            return job
        monkeypatch.setattr(arguments['queue'], 'claim', claim)
    else:
        before.append(lambda: clock.__setitem__(0, 131))
    with pytest.raises(ProviderFailure, match='TASK_TIMEOUT'):
        server.execute_governed_router_qa(**arguments)
    job = arguments['queue'].list()[0]
    assert len(calls) == len(credentials) == (0 if point == 'claim' else 1)
    assert job['actual_cost_usd'] == (0 if point == 'claim' else .0000018)


def test_api_router_mode_is_explicit_and_does_not_unlock_direct_without_contract(router_only, monkeypatch):
    arguments, _, calls, credentials, _, _ = router_only
    client, body = _api_client(router_only, monkeypatch)
    headers = {'Authorization': arguments['authorization']}
    assert client.post('/api/compute-queue/hf/qa', json={**body, 'route': 'HF_ROUTER'}).status_code == 401
    direct = client.post('/api/compute-queue/hf/qa', json=body, headers=headers)
    assert direct.status_code == 503 and direct.json() == {'detail': 'QA_PRICE_CONTRACT_UNAVAILABLE'}
    assert not calls and not credentials and not arguments['queue'].list()
    for injected in ({'route': 'auto'}, {'route': 'HF_ROUTER', 'task_class': 'classification'},
                     {'route': 'HF_ROUTER', 'execute_hf_router': 'forged'}):
        assert client.post('/api/compute-queue/hf/qa', json={**body, **injected}, headers=headers).status_code == 422
    response = client.post('/api/compute-queue/hf/qa', json={**body, 'route': 'HF_ROUTER'}, headers=headers)
    assert response.status_code == 200 and response.json()['route'] == 'HF_ROUTER_QA'
    assert calls == ['router'] and len(credentials) == 1


@pytest.mark.parametrize('change', [
    {'data_classification': 'SENSITIVE'}, {'context': 'password=offline-fixture'},
])
def test_router_only_preserves_privacy_denial_before_disclosure(router_only, change):
    arguments, _, calls, credentials, _, _ = router_only
    arguments.update(change)
    with pytest.raises(ProviderFailure, match='DATA_LOCALITY'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials and not arguments['queue'].list()


def test_router_only_backpressure_cancels_only_unused_hold(router_only):
    arguments, _, calls, credentials, _, _ = router_only
    q, p = arguments['queue'], arguments['available_providers'][0]
    busy = q.submit(agent='a20', prompt='public', model=p.model, preferred_provider=p.name,
        allow_cloud=True, data_classification='CLOUD_PERMITTED', max_cost_usd=.01)
    assert q.claim('occupied', [p])['id'] == busy['id']
    with pytest.raises(ProviderFailure, match='CAPACITY'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials and q.policy.cloud_concurrency == 1
    assert q.get(busy['id'])['status'] == 'running' and q.get(busy['id'])['cloud_inflight'] == 1
    held = next(job for job in q.list() if job['id'] != busy['id'])
    assert held['status'] == 'cancelled' and held['actual_cost_usd'] == 0


def test_router_only_postclaim_catalog_change_cannot_read_credentials(router_only, monkeypatch):
    arguments, entry, calls, credentials, _, _ = router_only
    q, original_claim = arguments['queue'], arguments['queue'].claim
    def claim(*args, **kwargs):
        job = original_claim(*args, **kwargs)
        entry['allowed_task_classes'] = ['classification']
        return job
    monkeypatch.setattr(q, 'claim', claim)
    with pytest.raises(ProviderFailure, match='QA_CATALOG_CHANGED'):
        server.execute_governed_router_qa(**arguments)
    assert not calls and not credentials
    assert q.metrics()['daily_spend_usd'] == 0 and not q.metrics()['cloud_inflight']


def test_router_only_postresponse_state_fault_preserves_reported_charge(router_only, monkeypatch):
    arguments, _, calls, _, _, before = router_only
    q, original_get = arguments['queue'], arguments['queue'].get
    fault = {'armed': False, 'remaining': 1}
    before.append(lambda: fault.update(armed=True))
    def get(job_id):
        if fault['armed'] and fault['remaining']:
            fault['remaining'] -= 1
            raise RuntimeError('synthetic temporary state read fault')
        return original_get(job_id)
    monkeypatch.setattr(q, 'get', get)
    with pytest.raises(ProviderFailure, match='QA_ROUTER_EXECUTION_FAILURE'):
        server.execute_governed_router_qa(**arguments)
    assert calls == ['router'] and q.metrics()['daily_spend_usd'] == .0000018
    assert q.list()[0]['actual_cost_usd'] == .0000018 and not q.metrics()['cloud_inflight']
