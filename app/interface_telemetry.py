"""Bounded workspace aggregates with evidence-bound runtime readiness."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.request
import uuid

from .agent_registry import load_agent_registry


def activity_is_fresh(value, *, now, max_age_seconds):
    """Return true only for a timestamped observation inside the allowed clock window."""
    if not isinstance(value, str) or not isinstance(max_age_seconds, int):
        return False
    try:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = now - observed.timestamp()
    except (OverflowError, TypeError, ValueError):
        return False
    return -5 <= age <= max_age_seconds


def queue_freshness_seconds():
    """Read the permanent queue-observation window, failing closed if malformed."""
    raw = os.getenv('PRIME_READY_ACTIVITY_MAX_AGE_SECONDS', '3600').strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 60 <= value <= 86400 else None


def model_runtime_readiness(timeout=2.0):
    """Probe the local model runtime and require every configured model."""
    required = []
    for name in ('PRIME_FAST_MODEL', 'PRIME_DEEP_MODEL',
                 'PRIME_EVALUATOR_MODEL', 'PRIME_EMBED_MODEL'):
        value = os.getenv(name, '').strip()
        if value and value not in required:
            required.append(value)
    endpoint = os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434').rstrip('/')
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(endpoint + '/api/tags', timeout=timeout) as response:
            payload = json.loads(response.read(2_000_000).decode('utf-8'))
        available = {
            str(item.get('name'))
            for item in payload.get('models', [])
            if isinstance(item, dict) and item.get('name')
        }
        missing = [name for name in required if name not in available]
        return {
            'status': 'OBSERVED',
            'ready': response.status == 200 and not missing and bool(required),
            'endpoint': endpoint,
            'required_models': required,
            'missing_models': missing,
            'observed_at': observed_at,
            'network_probe_performed': True,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {
            'status': 'UNAVAILABLE',
            'ready': False,
            'endpoint': endpoint,
            'required_models': required,
            'missing_models': required,
            'observed_at': observed_at,
            'network_probe_performed': True,
        }


def telemetry_store_counts():
    root = Path(os.getenv('PRIME_DATA_DIR', '/data')).resolve()

    def query(path, statement):
        if not path.is_file():
            return None
        db = None
        try:
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
            deadline = time.monotonic() + 0.2
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            return db.execute(statement).fetchone()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None
        finally:
            if db is not None:
                db.close()

    objective_row = query(root/'objectives.db', 'SELECT COUNT(*) FROM objectives')
    job_row = query(root/'compute-queue.db',
        "SELECT COUNT(*),COALESCE(SUM(CASE WHEN status IN ('queued','running','awaiting_approval') "
        "THEN 1 ELSE 0 END),0) FROM compute_jobs")
    return {
        'objectives': {'status': 'OBSERVED' if objective_row is not None else 'UNAVAILABLE',
                       'count': objective_row[0] if objective_row is not None else None},
        'compute_jobs': {'status': 'OBSERVED' if job_row is not None else 'UNAVAILABLE',
                         'count': job_row[0] if job_row is not None else None,
                         'active_count': job_row[1] if job_row is not None else None},
    }


def agent_activity():
    """Collect bounded queue-backed activity without claiming process liveness."""
    root = Path(os.getenv('PRIME_DATA_DIR', '/data')).resolve()
    path = root/'compute-queue.db'
    if not path.is_file():
        return None
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
        columns = {row[1] for row in db.execute('PRAGMA table_info(compute_jobs)')}
        if not {'agent', 'status'}.issubset(columns):
            return None
        timestamp = 'updated_at' if 'updated_at' in columns else 'NULL'
        return {row[0]: {'status': row[1], 'observed_at': row[2]} for row in db.execute(
            f"SELECT agent,status,{timestamp} FROM compute_jobs WHERE rowid IN "
            "(SELECT MAX(rowid) FROM compute_jobs GROUP BY agent)")}
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        if db is not None:
            db.close()


def snapshot(client_id, role, *, model_runtime_probe=None):
    observed = datetime.now(timezone.utc).isoformat()
    registry = load_agent_registry()
    stores = telemetry_store_counts()
    from .coaching_observation import coaching_snapshot
    coaching = coaching_snapshot(Path(os.getenv('PRIME_DATA_DIR','/data')))
    activity = agent_activity()
    model_runtime = model_runtime_probe or model_runtime_readiness()
    instance = os.getenv('PRIME_INTERFACE_HOST_ID', 'UNKNOWN')
    revision = os.getenv('PRIME_INTERFACE_RUNTIME_REVISION', 'UNKNOWN')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', instance):
        instance = 'UNKNOWN'
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        revision = 'UNKNOWN'

    def metric(name, value, status, producer, unit='count'):
        return {'metric_id': name, 'value': value, 'unit': unit,
                'collection_status': status, 'source_system': 'ORQEVIA',
                'source_instance': instance, 'producer': producer,
                'scope': 'WORKSPACE_AGGREGATE', 'event_timestamp': None,
                'observed_at': observed,
                'provenance': 'READ_ONLY_STORE_OBSERVATION' if status == 'OBSERVED' else 'NO_MEASUREMENT'}

    active = stores['compute_jobs']['active_count']
    metrics = [metric('registered_agents', len(registry['agents']), 'OBSERVED', 'agent-registry'),
               metric('active_job_records', active, 'OBSERVED' if active is not None else 'UNAVAILABLE', 'compute-queue'),
               metric('stored_objectives', stores['objectives']['count'], stores['objectives']['status'], 'objective-store')]
    from .host_metrics import host_metrics
    host = host_metrics()
    host_producer = 'host-collector' if host['configured'] else 'HOST_COLLECTOR_NOT_CONFIGURED'
    for name, unit, field in [('cpu', 'percent', 'cpu_percent'), ('memory', 'percent', 'memory_percent'),
                              ('disk', 'percent', 'disk_percent'), ('network_latency', 'ms', 'network_latency_ms')]:
        value = host['values'].get(field)
        metrics.append(metric(name, value, 'OBSERVED' if value is not None else 'UNAVAILABLE', host_producer, unit))
    agents=[]
    for agent in registry['agents']:
        record=activity.get(agent['id']) if activity is not None else None
        status=record['status'] if record else None
        availability=('RUNNING' if status=='running' else 'QUEUED' if status in {'queued','awaiting_approval'}
                      else 'IDLE' if record else 'NOT_OBSERVED' if activity is not None else 'COLLECTOR_UNAVAILABLE')
        agents.append({'agent_id':agent['id'],'name':agent['name'],'registration':'REGISTERED',
                       'availability':availability,'heartbeat':record['observed_at'] if record else None,
                       'activity_source':'compute-queue'})
    observed_count = (
        sum(item['availability'] in {'RUNNING','QUEUED','IDLE'} for item in agents)
        if activity is not None else None
    )
    max_age_seconds = queue_freshness_seconds()
    now_epoch = datetime.fromisoformat(observed).timestamp()
    fresh_agent_ids = []
    if activity is not None and max_age_seconds is not None:
        fresh_agent_ids = [
            agent['agent_id']
            for agent in agents
            if agent['agent_id'] in activity
            and activity_is_fresh(
                activity[agent['agent_id']]['observed_at'],
                now=now_epoch,
                max_age_seconds=max_age_seconds,
            )
        ]
    fresh_count = len(fresh_agent_ids) if activity is not None and max_age_seconds is not None else None
    queue_ready = observed_count == len(registry['agents'])
    ready = (
        fresh_count
        if queue_ready and fresh_count == len(registry['agents']) and model_runtime['ready']
        else 0 if activity is not None and model_runtime['status'] == 'OBSERVED'
        else None
    )
    metrics.append(metric('observed_agents', observed_count,
                          'OBSERVED' if observed_count is not None else 'UNAVAILABLE',
                          'compute-queue'))
    metrics.append(metric('fresh_agents', fresh_count,
                          'OBSERVED' if fresh_count is not None else 'UNAVAILABLE',
                          'compute-queue'))
    metrics.append(metric('ready_agents', ready,
                          'OBSERVED' if ready is not None else 'UNAVAILABLE',
                          'agent-registry+compute-queue+model-runtime'))
    not_fresh_agent_ids = (
        [agent['agent_id'] for agent in agents if agent['agent_id'] not in fresh_agent_ids]
        if fresh_count is not None else []
    )
    return {'schema_version': 'orqevia.telemetry.v1', 'snapshot_id': str(uuid.uuid4()),
            'observed_at': observed, 'freshness_seconds': 60,
            'audience': {'client_id': client_id, 'role': role},
            'source': {'system': 'ORQEVIA', 'instance': instance, 'revision': revision},
            'metrics': metrics,
            'ready_agent_count': ready,
            'observed_agent_count': observed_count,
            'fresh_agent_count': fresh_count,
            'readiness_scope': 'CURRENT_MODEL_RUNTIME_AND_QUEUE_ROUTABLE',
            'queue_freshness': {
                'status': 'OBSERVED' if fresh_count is not None else 'UNAVAILABLE',
                'max_age_seconds': max_age_seconds,
                'fresh_agent_count': fresh_count,
                'not_fresh_agent_count': len(not_fresh_agent_ids) if fresh_count is not None else None,
                'not_fresh_agent_ids': not_fresh_agent_ids,
                'rule': 'latest queue observation must be timestamped, within max age, and no more than five seconds in the future',
            },
            'model_runtime': model_runtime,
            'agents': agents,
            'coaching': coaching,
            'privacy': {'aggregate_only': True, 'private_tasks_exposed': False,
                        'credentials_exposed': False}}
