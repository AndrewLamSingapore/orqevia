import hashlib
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_snapshot_reads_store_counts_without_inventing_agent_or_host_health(monkeypatch, tmp_path):
    from app import interface_telemetry
    snapshot = interface_telemetry.snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID', 'ISOLATED-SOURCE-TEST')
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION', 'a' * 40)
    monkeypatch.setattr(interface_telemetry, 'model_runtime_readiness', lambda: {
        'status': 'UNAVAILABLE', 'ready': False, 'endpoint': 'test',
        'required_models': [], 'missing_models': [], 'observed_at': 'test',
        'network_probe_performed': False,
    })
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text,status text)')
        db.executemany('insert into compute_jobs values(?,?)', [('1', 'completed'), ('2', 'running'), ('3', 'failed')])
    report = snapshot('fixture-client', 'MEMBER')
    metrics = {m['metric_id']: m for m in report['metrics']}
    assert metrics['active_job_records']['value'] == 1
    assert metrics['registered_agents']['value'] == 21
    assert len({a['agent_id'] for a in report['agents']}) == 21
    assert all(a['availability'] == 'COLLECTOR_UNAVAILABLE' and a['heartbeat'] is None for a in report['agents'])
    assert report['ready_agent_count'] is None
    assert report['observed_agent_count'] is None
    assert report['readiness_scope'] == 'CURRENT_MODEL_RUNTIME_AND_QUEUE_ROUTABLE'
    assert all(metrics[n]['value'] is None for n in ['cpu', 'memory', 'disk', 'network_latency'])
    assert report['source']['instance'] == 'ISOLATED-SOURCE-TEST'
    assert report['privacy']['private_tasks_exposed'] is False
    assert 'LIVE' not in json.dumps(report)


def test_missing_stores_are_unavailable_not_zero(monkeypatch, tmp_path):
    from app import interface_telemetry
    monkeypatch.setattr(interface_telemetry, 'model_runtime_readiness', lambda: {
        'status': 'UNAVAILABLE', 'ready': False, 'endpoint': 'test',
        'required_models': [], 'missing_models': [], 'observed_at': 'test',
        'network_probe_performed': False,
    })
    snapshot = interface_telemetry.snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    report = snapshot('fixture-client', 'MEMBER')
    active = next(m for m in report['metrics'] if m['metric_id'] == 'active_job_records')
    assert active['collection_status'] == 'UNAVAILABLE' and active['value'] is None


def test_configured_host_collector_is_observed(monkeypatch, tmp_path):
    from app import interface_telemetry
    monkeypatch.setattr(interface_telemetry, 'model_runtime_readiness', lambda: {
        'status': 'UNAVAILABLE', 'ready': False, 'endpoint': 'test',
        'required_models': [], 'missing_models': [], 'observed_at': 'test',
        'network_probe_performed': False,
    })
    snapshot = interface_telemetry.snapshot
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID', 'ISOLATED-SOURCE-TEST')
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION', 'a' * 40)
    receipt = tmp_path / 'host-metrics.json'
    receipt.write_text(json.dumps({
        'schema': 'orqevia.host-metrics.v1',
        'host_id': 'ISOLATED-SOURCE-TEST',
        'boot_id': 'boot-1',
        'collector_id': 'abex-host-metrics-v1',
        'captured_at': time.time(),
        'cpu_percent': 10.0,
        'memory_percent': 20.0,
        'disk_percent': 30.0,
        'network_latency_ms': 2.0,
    }), encoding='utf-8')
    monkeypatch.setenv('PRIME_HOST_METRICS_RECEIPT', str(receipt))
    report = snapshot('fixture-client', 'MEMBER')
    metrics = {m['metric_id']: m for m in report['metrics']}
    assert metrics['cpu']['value'] == 10.0 and metrics['cpu']['collection_status'] == 'OBSERVED'
    assert metrics['cpu']['producer'] == 'host-collector'
    assert metrics['memory']['value'] == 20.0
    assert metrics['disk']['value'] == 30.0
    assert metrics['network_latency']['value'] == 2.0


def test_ready_agents_require_observed_queue_and_current_models(monkeypatch, tmp_path):
    from app import interface_telemetry
    from app.agent_registry import registered_agent_ids
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    agents = sorted(registered_agent_ids(include_orchestrator=False))
    current = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text,agent text,status text,updated_at text)')
        db.executemany(
            'insert into compute_jobs values(?,?,?,?)',
            [(str(i), agent, 'completed', current) for i, agent in enumerate(agents)],
        )
    ready_runtime = {
        'status': 'OBSERVED', 'ready': True, 'endpoint': 'test',
        'required_models': ['gemma3:1b'], 'missing_models': [],
        'observed_at': 'test', 'network_probe_performed': True,
    }
    report = interface_telemetry.snapshot(
        'fixture-client', 'MEMBER', model_runtime_probe=ready_runtime
    )
    assert report['observed_agent_count'] == 21
    assert report['fresh_agent_count'] == 21
    assert report['ready_agent_count'] == 21
    assert report['queue_freshness']['not_fresh_agent_ids'] == []

    missing_runtime = dict(ready_runtime, ready=False, missing_models=['gemma3:4b'])
    report = interface_telemetry.snapshot(
        'fixture-client', 'MEMBER', model_runtime_probe=missing_runtime
    )
    assert report['observed_agent_count'] == 21
    assert report['fresh_agent_count'] == 21
    assert report['ready_agent_count'] == 0


def test_ready_agents_require_fresh_timestamps_but_observed_history_remains(monkeypatch, tmp_path):
    from app import interface_telemetry
    from app.agent_registry import registered_agent_ids
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_READY_ACTIVITY_MAX_AGE_SECONDS', '60')
    agents = sorted(registered_agent_ids(include_orchestrator=False))
    current = datetime.now(timezone.utc)
    rows = []
    for index, agent in enumerate(agents):
        timestamp = (
            None if index == 20
            else (current - timedelta(seconds=120)).isoformat() if index == 19
            else (current + timedelta(seconds=10)).isoformat() if index == 18
            else current.isoformat()
        )
        rows.append((str(index), agent, 'completed', timestamp))
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text,agent text,status text,updated_at text)')
        db.executemany('insert into compute_jobs values(?,?,?,?)', rows)
    ready_runtime = {
        'status': 'OBSERVED', 'ready': True, 'endpoint': 'test',
        'required_models': ['gemma3:1b'], 'missing_models': [],
        'observed_at': 'test', 'network_probe_performed': True,
    }
    report = interface_telemetry.snapshot(
        'fixture-client', 'MEMBER', model_runtime_probe=ready_runtime
    )
    assert report['observed_agent_count'] == 21
    assert report['fresh_agent_count'] == 18
    assert report['ready_agent_count'] == 0
    assert set(report['queue_freshness']['not_fresh_agent_ids']) == set(agents[-3:])


def test_malformed_freshness_window_fails_closed(monkeypatch, tmp_path):
    from app import interface_telemetry
    from app.agent_registry import registered_agent_ids
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_READY_ACTIVITY_MAX_AGE_SECONDS', 'not-a-number')
    current = datetime.now(timezone.utc).isoformat()
    agents = sorted(registered_agent_ids(include_orchestrator=False))
    with sqlite3.connect(tmp_path / 'compute-queue.db') as db:
        db.execute('create table compute_jobs(id text,agent text,status text,updated_at text)')
        db.executemany(
            'insert into compute_jobs values(?,?,?,?)',
            [(str(i), agent, 'completed', current) for i, agent in enumerate(agents)],
        )
    ready_runtime = {
        'status': 'OBSERVED', 'ready': True, 'endpoint': 'test',
        'required_models': ['gemma3:1b'], 'missing_models': [],
        'observed_at': 'test', 'network_probe_performed': True,
    }
    report = interface_telemetry.snapshot(
        'fixture-client', 'MEMBER', model_runtime_probe=ready_runtime
    )
    assert report['observed_agent_count'] == 21
    assert report['fresh_agent_count'] is None
    assert report['ready_agent_count'] == 0
    assert report['queue_freshness']['status'] == 'UNAVAILABLE'


def test_container_packages_every_dashboard_shell_asset():
    from pathlib import Path
    root=Path(__file__).parents[1]
    dockerfile=(root/'Dockerfile').read_text(encoding='utf-8')
    copies=[line.split() for line in dockerfile.splitlines() if line.startswith('COPY clients/pwa/')]
    packaged={part for parts in copies for part in parts[1:-1]}
    for name in ('dashboard.mjs','dashboard.css'):
        assert f'clients/pwa/{name}' in packaged
        assert (root/'clients/pwa'/name).is_file()


def test_dashboard_styles_are_allowed_by_the_existing_real_csp(monkeypatch):
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from app import pwa_sessions
    pwa=Path(__file__).parents[1]/'clients/pwa'
    monkeypatch.setenv('PRIME_PWA_ORIGIN','https://testserver')
    app=FastAPI();app.add_middleware(pwa_sessions.PWASessionMiddleware)
    app.mount('/pwa',StaticFiles(directory=pwa,html=True))
    with TestClient(app,base_url='https://testserver') as client:response=client.get('/pwa/')
    assert response.status_code==200
    assert "default-src 'self'" in response.headers['content-security-policy']
    assert 'unsafe-inline' not in response.headers['content-security-policy']
    assert '<style' not in response.text
    assert 'style=' not in response.text
    assert '<link rel="stylesheet" href="/pwa/dashboard.css">' in response.text
    assert 'padding-top:max(env(safe-area-inset-top),0px)' in (pwa/'dashboard.css').read_text(encoding='utf-8')


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
            assert response.json()['audience'] == {'client_id': name, 'role': policies[name]['role']}
            assert all(m['scope']=='WORKSPACE_AGGREGATE' for m in response.json()['metrics'])
        policies['member']['expires_at'] = time.time() - 1
        monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON', json.dumps(policies))
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'member', 'Authorization': 'Bearer member'}).status_code == 403
        policies['owner']['capabilities'] = []
        monkeypatch.setenv('PRIME_INTERFACE_CLIENTS_JSON', json.dumps(policies))
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'owner', 'Authorization': 'Bearer owner'}).status_code == 403
    with TestClient(app, base_url='http://testserver') as client:
        assert client.get('/interface/v1/telemetry', headers={'X-Client-ID': 'owner', 'Authorization': 'Bearer owner'}).status_code == 426
