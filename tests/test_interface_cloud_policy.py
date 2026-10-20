"""Server-owned thin-client cloud policy; all providers/data are isolated fixtures."""
import hashlib
import json
import time
from dataclasses import replace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def interface(monkeypatch, tmp_path):
    from app import agent_dispatch_api, interface_contract as contract, compute_queue_api as compute
    from app.action_records import close_ledgers
    from app.job_queue import JobQueue, QueuePolicy
    # This policy fixture isolates cloud routing. Collapse the local deep tier so
    # the only MINI backend is the server-authorized cloud fixture.
    local_only = replace(agent_dispatch_api.SETTINGS, fast_model='gemma3:1b', deep_model='gemma3:1b')
    local_backends = agent_dispatch_api.local_model_backends
    monkeypatch.setattr(agent_dispatch_api, 'local_model_backends', lambda: local_backends(local_only))
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'fixture-owner')
    monkeypatch.setenv('ORQEVIA_REGISTRY_V1_ENABLED', '1')
    monkeypatch.setenv('FIXTURE_INTERFACE_CLOUD_KEY', 'fixture-only-key')
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'models': [{'id': 'fixture-cloud', 'model': 'fixture-model',
        'tier': 'MINI', 'location': 'cloud', 'enabled': True,
        'endpoint': 'https://fixture.invalid/v1/chat/completions',
        'secret_ref': 'env:FIXTURE_INTERFACE_CLOUD_KEY', 'output_tokens': 128,
        'context_tokens': 4096, 'input_usd_million': 1, 'output_usd_million': 1}]}))
    monkeypatch.setenv('ORQEVIA_PROVIDER_CATALOG', str(catalog))
    monkeypatch.setattr(compute, 'queue', JobQueue(tmp_path / 'queue.db',
        QueuePolicy(global_concurrency=1, per_agent_concurrency=1, max_job_cost_usd=1,
                    daily_cost_ceiling_usd=2, cloud_wait_seconds=0)))
    policy = {'token_sha256': hashlib.sha256(b'fixture-client').hexdigest(),
              'expires_at': time.time()+300, 'capabilities': ['health.read', 'objective.submit', 'task.read']}
    def configure(**values):
        policy.update(values)
        monkeypatch.setenv('ORQEVIA_INTERFACE_CLIENTS_JSON', json.dumps({'dell': policy}))
    configure()
    app = FastAPI()
    app.include_router(contract.router)
    app.include_router(contract.node.router)
    client = TestClient(app, base_url='https://fixture.invalid',
                        headers={'X-Client-ID': 'dell', 'Authorization': 'Bearer fixture-client'})
    close_ledgers()
    yield client, configure, compute, contract.node
    close_ledgers()


def test_default_local_only_and_no_caller_overrides(interface, monkeypatch):
    client, _, _, node = interface
    requests=[]
    monkeypatch.setattr(node.objective_api, 'submit', lambda body, authorization: requests.append(body) or {'id': 'fixture-task'})
    response=client.post('/interface/v1/objectives', json={'objective': 'Write a note', 'idempotency_key': 'one',
        'data_classification': 'CLOUD_PERMITTED', 'max_cost_usd': 100, 'model': 'override', 'minimum_tier': 'FLAGSHIP',
        'classification': 'R3', 'capability': 'responsibility.a17'})
    assert response.status_code == 202, response.text
    body=requests[0]
    assert body.data_classification == 'LOCAL_ONLY' and body.max_cost_usd == 0
    assert body.minimum_tier == 'NANO' and body.classification == 'R0' and body.capability == 'auto'
    health=client.get('/interface/v1/health').json()
    assert health['cloud_configuration_ready'] is True and health['cloud_enabled'] is False
    assert health['cloud_provider_health'] == 'UNMEASURED' and health['cloud_network_probe_performed'] is False


def test_server_permission_routes_into_shared_queue_without_network(interface):
    client, configure, compute, _ = interface
    configure(data_classification='CLOUD_PERMITTED', max_cost_usd=1)
    health=client.get('/interface/v1/health').json()
    assert health['cloud_enabled'] is True
    assert 'fixture-only-key' not in json.dumps(health)
    result=client.post('/interface/v1/objectives', json={'objective': 'Write a concise note', 'idempotency_key': 'cloud'})
    assert result.status_code == 202, result.text
    task=client.get('/interface/v1/tasks/'+result.json()['task_id']).json()
    job=task['steps'][0]['dispatch']['job']
    assert job['preferred_provider'] == 'fixture-cloud'
    assert job['allow_cloud'] and job['data_classification'] == 'CLOUD_PERMITTED' and job['max_cost_usd'] == 1
    claimed=compute.queue.claim('fixture-worker', compute.providers())
    assert claimed['id'] == job['id'] and claimed['estimated_cost_usd'] > 0
    assert claimed['harness_envelope'] is None
    # No worker pool is started and the claimed job is deliberately not executed.


def test_secrets_still_excluded_by_core_dispatcher(interface):
    client, configure, compute, _ = interface
    configure(data_classification='CLOUD_PERMITTED', max_cost_usd=1)
    result=client.post('/interface/v1/objectives', json={'objective': 'Write a concise note',
        'context': 'api_key=fixture-secret-do-not-send', 'idempotency_key': 'secret'})
    assert result.status_code == 202
    task=client.get('/interface/v1/tasks/'+result.json()['task_id']).json()
    assert task['state'] == 'COMPLETED_WITH_FAILURES'
    assert all(step['state'] == 'blocked' for step in task['steps'])
    assert compute.queue.list() == []


@pytest.mark.parametrize('values', [
    {'data_classification': 'public'}, {'data_classification': None}, {'data_classification': []},
    {'max_cost_usd': -1}, {'max_cost_usd': 101}, {'max_cost_usd': float('nan')},
    {'max_cost_usd': float('inf')}, {'max_cost_usd': True}, {'max_cost_usd': '1'},
])
def test_malformed_policy_fails_closed(interface, values):
    client, configure, compute, _ = interface
    configure(**values)
    assert client.get('/interface/v1/health').status_code == 503
    assert client.post('/interface/v1/objectives', json={'objective': 'Write a note', 'idempotency_key': 'bad'}).status_code == 503
    assert compute.queue.list() == []


def test_health_requires_credentials_budget_and_scope(interface, monkeypatch):
    client, configure, _, _ = interface
    configure(data_classification='CLOUD_PERMITTED', max_cost_usd=1)
    monkeypatch.delenv('FIXTURE_INTERFACE_CLOUD_KEY')
    health=client.get('/interface/v1/health').json()
    assert health['cloud_client_permitted'] and not health['cloud_configuration_ready'] and not health['cloud_enabled']
    monkeypatch.setenv('FIXTURE_INTERFACE_CLOUD_KEY', 'fixture-key')
    configure(max_cost_usd=0)
    assert not client.get('/interface/v1/health').json()['cloud_enabled']
    configure(max_cost_usd=1, capabilities=['health.read'])
    assert not client.get('/interface/v1/health').json()['cloud_enabled']
