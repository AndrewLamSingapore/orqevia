"""Local shell security and actual deterministic API roundtrip; no providers run."""
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def shell(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'fixture-owner-secret')
    monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED', '1')
    from app import production_entry as entry
    from app import compute_queue_api as compute
    from app.job_queue import JobQueue
    from app.action_records import close_ledgers
    monkeypatch.setattr(compute, 'queue', JobQueue(str(tmp_path / 'queue.db'), compute.POLICY))
    close_ledgers()
    yield entry, TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 43210))
    close_ledgers()


def test_minimal_health_and_static_no_secrets(shell, monkeypatch):
    entry, client = shell
    assert client.get('/health').json() == {'ok': True}
    for path in ['/control', '/control/app.js']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'fixture-owner-secret' not in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-frame-options'] == 'DENY'
    monkeypatch.delenv('PRIME_SPINE_TOKEN')
    assert client.get('/health').status_code == 503
    assert client.get('/health').json() == {'ok': False}
    assert client.get('/control').status_code == 503


def test_phone_pairing_only_local_same_origin(shell):
    entry, client = shell
    assert client.post('/control/api/pwa-pairing').status_code == 403
    headers = {'Origin': 'http://127.0.0.1:8000', 'X-Jarvis-PWA': '1'}
    result = client.post('/control/api/pwa-pairing', headers=headers)
    assert result.status_code == 200
    assert set(result.json()) == {'code', 'expiresAt', 'role'}
    assert result.json()['role'] == 'MEMBER'
    assert result.headers['cache-control'] == 'no-store'
    assert 'fixture-owner-secret' not in result.text


@pytest.mark.parametrize('headers', [
    {'Host': 'evil.example'}, {'Origin': 'http://evil.example'},
    {'Origin': 'http://localhost:8000'}, {'Origin': 'http://127.0.0.1:9999'},
    {'Origin': 'https://127.0.0.1:8000'}, {'Origin': 'null'},
    {'Sec-Fetch-Site': 'cross-site'}, {'Host': '127.0.0.1@evil.example'},
])
def test_untrusted_local_reads_rejected(shell, headers):
    _, client = shell
    for path in ['/health', '/control', '/control/api/jobs']:
        assert client.get(path, headers=headers).status_code == 403


def test_remote_peer_cannot_use_spoofed_host_or_forwarding(shell):
    entry, _ = shell
    client = TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('192.0.2.10', 50000))
    for path in ['/health', '/control', '/control/api/jobs']:
        assert client.get(path, headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403


def test_exact_configured_docker_gateway_can_reach_loopback_owner_binding(shell, monkeypatch):
    entry, _ = shell
    monkeypatch.setenv('PRIME_OWNER_TRUSTED_PEERS', '172.30.9.1')
    client = TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('172.30.9.1', 50000))
    assert client.get('/health').json() == {'ok': True}
    assert client.get('/control').status_code == 200
    other = TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('172.30.9.2', 50001))
    assert other.get('/health').status_code == 403


def test_mutations_require_exact_origin_before_dispatch(shell, monkeypatch):
    entry, client = shell
    def forbidden(*args, **kwargs):
        raise AssertionError('Mutation reached API')
    monkeypatch.setattr(entry.agent_dispatch_api, 'dispatch', forbidden)
    body = {'objective': 'fixture', 'capability': 'responsibility.a02'}
    for headers in [{}, {'Origin': 'http://127.0.0.1:8001'}, {'Origin': 'http://attacker.invalid'}]:
        assert client.post('/control/api/dispatch', json=body, headers=headers).status_code == 403


def test_real_objective_artifact_roundtrip_and_protected_apis(shell, monkeypatch):
    entry, client = shell
    from app.action_harness import ActionHarness
    def forbidden(*args, **kwargs):
        raise AssertionError('Legacy gate invoked')
    monkeypatch.setattr(ActionHarness, 'authorize', forbidden)
    headers = {'Origin': 'http://127.0.0.1:8000'}
    body = {'objective': 'Hash supplied text', 'context': 'hello',
            'capability': 'responsibility.a02', 'deterministic_operation': 'sha256'}
    response = client.post('/control/api/objectives', json=body, headers=headers)
    assert response.status_code == 202, response.text
    task_id = response.json()['id']
    result = client.get('/control/api/objectives/' + task_id)
    assert result.status_code == 200 and result.json()['state'] == 'COMPLETED'
    artifact_id = result.json()['steps'][0]['dispatch']['artifact']['artifact_id']
    download = client.get('/control/api/artifacts/' + artifact_id)
    assert download.status_code == 200 and hashlib.sha256(b'hello').hexdigest() in download.text
    assert download.headers['content-disposition'] == 'attachment'
    materialized = client.post('/control/api/artifacts/from-task/' + task_id, json={}, headers=headers)
    assert materialized.status_code == 201, materialized.text
    assert client.get('/control/api/jobs').json() == {'jobs': []}
    for path in ['/api/compute-queue/jobs', '/api/agents/objectives/' + task_id, '/api/artifacts/' + artifact_id]:
        assert client.get(path).status_code == 401
    assert client.post('/api/agents/dispatch', json=body).status_code == 401
    dispatch = client.post('/control/api/dispatch', json=body, headers=headers)
    assert dispatch.status_code == 202 and dispatch.json()['state'] == 'COMPLETED'


def test_same_candidate_lifespan(shell, monkeypatch):
    entry, _ = shell
    calls = []
    monkeypatch.setattr(entry.direct_entry, 'start_compute_queue', lambda: calls.append('start'))
    monkeypatch.setattr(entry.direct_entry, 'stop_compute_queue', lambda: calls.append('stop'))
    monkeypatch.setattr(entry.direct_entry, 'close_ledgers', lambda: calls.append('close'))
    with TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 40000)) as client:
        assert client.get('/health').status_code == 200
    assert calls == ['start', 'stop', 'close']


def test_survival_queue_is_real_durable_and_fail_closed(shell):
    _, client = shell
    headers = {'Origin': 'http://127.0.0.1:8000'}
    status = client.get('/control/api/survival/status')
    assert status.status_code == 200
    assert status.json()['queue_durable'] is True
    assert status.json()['internet'] == 'UNKNOWN'
    assert status.json()['cloud_model'] == 'UNKNOWN'
    assert status.json()['mode'] == 'CAPABILITY_UNVERIFIED'
    assert status.json()['remote_execution'].startswith('DISABLED_')

    body = {
        'objective_id': 'offline-fixture',
        'operation_type': 'github.push',
        'payload_ref': 'refs/heads/fixture',
        'idempotency_key': 'fixture-idempotency-0001',
        'authorization_ref': 'owner-lease-fixture',
        'payload': {'repository': 'fixture/repository'},
    }
    queued = client.post('/control/api/survival/queue', json=body, headers=headers)
    assert queued.status_code == 202, queued.text
    assert queued.json()['operation_type'] == 'github.push'
    assert queued.json()['state'] in {'PENDING', 'DEFERRED_OFFLINE'}
    duplicate = client.post('/control/api/survival/queue', json=body, headers=headers)
    assert duplicate.status_code == 202
    assert duplicate.json()['id'] == queued.json()['id']

    listed = client.get('/control/api/survival/queue').json()['operations']
    assert [item['id'] for item in listed] == [queued.json()['id']]

    unknown = {**body, 'operation_type': 'danger.unknown', 'idempotency_key': 'fixture-idempotency-0002'}
    assert client.post('/control/api/survival/queue', json=unknown, headers=headers).status_code == 422
    nested_secret = {**body, 'idempotency_key': 'fixture-idempotency-0003',
                     'payload': {'items': [{'api_token': 'must-not-persist'}]}}
    assert client.post('/control/api/survival/queue', json=nested_secret, headers=headers).status_code == 422
    assert 'must-not-persist' not in Path(status.json()['queue_path']).read_bytes().decode('latin1')


def test_survival_mutation_requires_local_same_origin(shell):
    _, client = shell
    body = {
        'objective_id': 'offline-fixture', 'operation_type': 'github.push',
        'payload_ref': 'refs/heads/fixture', 'idempotency_key': 'fixture-idempotency-0004',
        'authorization_ref': 'owner-lease-fixture',
    }
    assert client.post('/control/api/survival/queue', json=body).status_code == 403
