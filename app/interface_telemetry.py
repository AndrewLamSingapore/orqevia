"""Bounded workspace aggregates, never agent readiness or private task content."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .agent_registry import load_agent_registry


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


def snapshot(client_id, role):
    observed = datetime.now(timezone.utc).isoformat()
    registry = load_agent_registry()
    stores = telemetry_store_counts()
    from .coaching_observation import coaching_snapshot
    coaching = coaching_snapshot(Path(os.getenv('PRIME_DATA_DIR','/data')))
    activity = agent_activity()
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
    for name, unit in [('cpu', 'percent'), ('memory', 'percent'), ('disk', 'percent'), ('network_latency', 'ms')]:
        metrics.append(metric(name, None, 'UNAVAILABLE', 'HOST_COLLECTOR_NOT_CONFIGURED', unit))
    agents=[]
    for agent in registry['agents']:
        record=activity.get(agent['id']) if activity is not None else None
        status=record['status'] if record else None
        availability=('RUNNING' if status=='running' else 'QUEUED' if status in {'queued','awaiting_approval'}
                      else 'IDLE' if record else 'NOT_OBSERVED' if activity is not None else 'COLLECTOR_UNAVAILABLE')
        agents.append({'agent_id':agent['id'],'name':agent['name'],'registration':'REGISTERED',
                       'availability':availability,'heartbeat':record['observed_at'] if record else None,
                       'activity_source':'compute-queue'})
    ready=sum(item['availability'] in {'RUNNING','QUEUED','IDLE'} for item in agents) if activity is not None else None
    return {'schema_version': 'orqevia.telemetry.v1', 'snapshot_id': str(uuid.uuid4()),
            'observed_at': observed, 'freshness_seconds': 60,
            'audience': {'client_id': client_id, 'role': role},
            'source': {'system': 'ORQEVIA', 'instance': instance, 'revision': revision},
            'metrics': metrics, 'ready_agent_count': ready,
            'agents': agents,
            'coaching': coaching,
            'privacy': {'aggregate_only': True, 'private_tasks_exposed': False,
                        'credentials_exposed': False}}
