import hashlib
import json
import sqlite3
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_snapshot_reads_store_counts_without_inventing_agent_or_host_health(monkeypatch, tmp_path):
    from app.interface_telemetry import snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID', 'ISOLATED-SOURCE-TEST')
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION', 'a' * 40)
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text,status text)')
        db.executemany('insert into compute_jobs values(?,?)', [('1', 'completed'), ('2', 'running'), ('3', 'failed')])
    report = snapshot()
    metrics = {m['metric_id']: m for m in report['metrics']}
    assert metrics['active_job_records']['value'] == 1
    assert metrics['registered_agents']['value'] == 21
    assert len({a['agent_id'] for a in report['agents']}) == 21
    assert all(a['availability'] == 'UNKNOWN' and a['heartbeat'] is None for a in report['agents'])
    assert report['ready_agent_count'] is None
    assert all(metrics[n]['value'] is None for n in ['cpu', 'memory', 'disk', 'network_latency'])
    assert report['source']['instance'] == 'ISOLATED-SOURCE-TEST'
    assert report['privacy']['private_tasks_exposed'] is False
    assert 'LIVE' not in json.dumps(report)


def test_missing_stores_are_unavailable_not_zero(monkeypatch, tmp_path):
    from app.interface_telemetry import snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    report = snapshot()
    active = next(m for m in report['metrics'] if m['metric_id'] == 'active_job_records')
    assert active['collection_status'] == 'UNAVAILABLE' and active['value'] is None


def test_focused_counts_do_not_read_unrelated_artifacts_or_action_history(monkeypatch, tmp_path):
    from app import interface_observations
    from app.interface_telemetry import snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    def forbidden():
        raise AssertionError('Telemetry must not scan unrelated evidence history')
    monkeypatch.setattr(interface_observations, 'evidence_aggregates', forbidden)
    (tmp_path / 'action-records.jsonl').write_text('malformed unrelated history')
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text, status text)')
        db.executemany('insert into compute_jobs values(?,?)', [('1','running'), ('2','queued'), ('3','completed')])
    db.close()
    metrics = {m['metric_id']: m for m in snapshot()['metrics']}
    assert metrics['active_job_records']['value'] == 2
    assert metrics['stored_objectives']['value'] is None


def test_large_telemetry_query_exceeding_budget_is_unavailable(monkeypatch, tmp_path):
    from app import interface_observations
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text, status text)')
        db.executemany('insert into compute_jobs values(?,?)', [(str(i),'running') for i in range(2000)])
    db.close()
    samples = iter([0, 2])
    monkeypatch.setattr(interface_observations.time, 'monotonic', lambda: next(samples, 2))
    assert interface_observations.telemetry_store_counts()['compute_jobs']['status_counts'] is None


def test_endpoint_preserves_auth_expiry_scope_and_no_store(monkeypatch, tmp_path):
    from app.interface_contract import router
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    policies = {n: {'token_sha256': hashlib.sha256(n.encode()).hexdigest(),
                   'expires_at': time.time() + 60, 'capabilities': ['health.read'], 'role': role}
                for n, role in [('owner', 'OWNER'), ('member', 'MEMBER')]}
    monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON', json.dumps(policies))
    app = FastAPI(); app.include_router(router)
    with TestClient(app, base_url='https://testserver') as client:
        assert client.get('/interface/v1/telemetry').status_code == 401
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'owner', 'Authorization': 'Bearer member'}).status_code == 401
        for name in ('owner', 'member'):
            response = client.get('/interface/v1/telemetry', headers={'X-Client-ID': name, 'Authorization': 'Bearer ' + name})
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'private, no-store'
            assert len(response.json()['agents']) == 21
            assert response.json()['privacy']['private_tasks_exposed'] is False
        policies['member']['expires_at'] = time.time() - 1
        monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON', json.dumps(policies))
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'member', 'Authorization': 'Bearer member'}).status_code == 403
        policies['owner']['capabilities'] = []
        monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON', json.dumps(policies))
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'owner', 'Authorization': 'Bearer owner'}).status_code == 403
    with TestClient(app, base_url='http://testserver') as client:
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'owner', 'Authorization': 'Bearer owner'}).status_code == 426
