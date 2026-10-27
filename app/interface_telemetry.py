"""Bounded workspace aggregates with evidence-bound runtime readiness."""
from datetime import datetime, timezone
import json
import math
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
    return timestamp_observation(value, now=now, max_age_seconds=max_age_seconds)['status'] == 'OBSERVED'


def _timestamp_epoch(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        epoch = stamp.timestamp()
        return epoch if math.isfinite(epoch) else None
    except (OverflowError, TypeError, ValueError):
        return None


def timestamp_observation(value, *, now, max_age_seconds):
    """Receipt time never repairs missing, naive, future or stale source time."""
    result = {'status': 'UNKNOWN', 'reason': 'TIMESTAMP_INVALID', 'age_seconds': None}
    if value is None:
        return {**result, 'reason': 'TIMESTAMP_NOT_RECORDED'}
    epoch = _timestamp_epoch(value)
    if epoch is None:
        return result
    age = now - epoch
    result['age_seconds'] = round(age, 3)
    if age < -5:
        return {**result, 'reason': 'TIMESTAMP_IN_FUTURE'}
    if type(max_age_seconds) is not int or max_age_seconds < 1:
        return {**result, 'reason': 'FRESHNESS_WINDOW_INVALID'}
    if age > max_age_seconds:
        return {**result, 'status': 'STALE', 'reason': 'ACTIVITY_STALE'}
    return {**result, 'status': 'OBSERVED', 'reason': None}


def queue_freshness_seconds():
    """Read the permanent queue-observation window, failing closed if malformed."""
    raw = os.getenv('ORQEVIA_READY_ACTIVITY_MAX_AGE_SECONDS', '3600').strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 60 <= value <= 86400 else None


def model_runtime_readiness(timeout=2.0):
    """Probe the local model runtime and require every configured model."""
    required = []
    for name in ('ORQEVIA_FAST_MODEL', 'ORQEVIA_DEEP_MODEL',
                 'ORQEVIA_EVALUATOR_MODEL', 'ORQEVIA_EMBED_MODEL'):
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
    root = Path(os.getenv('ORQEVIA_DATA_DIR', '/data')).resolve()

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
    """Project journal metadata only, ordered by actual transition time.

    A newly inserted row does not supersede an older job's later transition.
    An unorderable newest insertion remains explicit unknown evidence instead
    of falling back to an older successful row and claiming readiness.
    """
    root = Path(os.getenv('ORQEVIA_DATA_DIR', '/data')).resolve()
    path = root/'compute-queue.db'
    if not path.is_file():
        return None
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + 0.2
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        columns = {row[1] for row in db.execute('PRAGMA table_info(compute_jobs)')}
        if not {'agent', 'status'}.issubset(columns):
            return None
        names = ('id', 'agent', 'status', 'created_at', 'started_at', 'completed_at',
                 'updated_at', 'provider', 'model', 'task_class')
        projection = ','.join(f'j.{name}' if name in columns else f'NULL AS {name}' for name in names)
        # Free-text errors, inputs, outputs, leases and credentials never enter
        # the projection. Unknown errors retain a fixed classification only.
        error = ("CASE WHEN j.error IN ('LOCAL_EXECUTION_FAILED','LOCAL_EXECUTION_TIMEOUT',"
                 "'LOCAL_INFERENCE_FAILED','STRICT_JSON_CONTRACT_FAILED',"
                 "'EXTERNAL_EXECUTION_FAILED','worker lease expired',"
                 "'agent retired or unregistered','actual cost ceiling reached') THEN j.error "
                 "WHEN j.error IS NULL OR j.error='' THEN NULL ELSE 'EXECUTION_FAILURE' END"
                 if 'error' in columns else 'NULL')
        known = {agent['id'] for agent in load_agent_registry()['agents']}
        result = {}
        def order(task, field='updated_at'):
            epoch = _timestamp_epoch(task.get(field))
            if epoch is None and field == 'completed_at':
                epoch = _timestamp_epoch(task.get('updated_at'))
            return (epoch if epoch is not None else float('-inf'), task['_rowid'])
        def timestamp_order(field):
            if field not in columns:
                return 'NULL'
            # The journal writes offset-bearing ISO timestamps. A naive or
            # malformed row cannot outrank a valid transition as though UTC.
            return (f"CASE WHEN length({field}) BETWEEN 20 AND 64 AND "
                    f"(substr({field},-1)='Z' OR (substr({field},-6,1) IN ('+','-') "
                    f"AND substr({field},-3,1)=':')) THEN julianday({field}) END")
        transition_order = timestamp_order('updated_at')
        completion_order = f"COALESCE({timestamp_order('completed_at')},{transition_order})"
        # Rank the full history in SQLite, but decode/validate only the few
        # relevant candidates per role. Poll cost must not grow as Python
        # timestamp parsing over every historical job under the same budget.
        query = (
            "WITH times AS MATERIALIZED (SELECT rowid AS source_rowid,agent,status,"
            f"{transition_order} AS transition_time,{completion_order} AS terminal_time FROM compute_jobs),"
            "latest AS (SELECT agent,COUNT(*) AS history_count,MAX(source_rowid) AS inserted,"
            "MAX(transition_time) AS transition_time FROM times GROUP BY agent),"
            "terminal AS (SELECT agent,status,MAX(terminal_time) AS terminal_time FROM times "
            "WHERE status IN ('completed','failed','budget_blocked','blocked') GROUP BY agent,status),"
            "chosen AS (SELECT inserted AS source_rowid,history_count FROM latest UNION "
            "SELECT MAX(t.source_rowid),l.history_count FROM times t JOIN latest l ON t.agent=l.agent "
            "AND t.transition_time=l.transition_time GROUP BY t.agent UNION "
            "SELECT MAX(t.source_rowid),l.history_count FROM times t JOIN terminal x ON t.agent=x.agent "
            "AND t.status=x.status AND (t.terminal_time=x.terminal_time OR "
            "(t.terminal_time IS NULL AND x.terminal_time IS NULL)) "
            "JOIN latest l ON t.agent=l.agent GROUP BY t.agent,t.status) "
            f"SELECT j.rowid AS _rowid,{projection},{error} AS error_code,r.history_count AS _history_count "
            "FROM chosen r JOIN compute_jobs j ON j.rowid=r.source_rowid"
        )
        for raw in db.execute(query):
            if time.monotonic() >= deadline:
                return None
            task = dict(raw)
            history_count = task.pop('_history_count')
            aid = task['agent']
            if aid not in known:
                continue
            item = result.setdefault(aid, {'history_count': 0, '_inserted': None,
                                          'latest_task': None, 'last_success': None, 'last_failure': None})
            item['history_count'] = history_count
            if item['_inserted'] is None or task['_rowid'] > item['_inserted']['_rowid']:
                item['_inserted'] = task
            if item['latest_task'] is None or order(task) > order(item['latest_task']):
                item['latest_task'] = task
            category = 'last_success' if task['status'] == 'completed' else (
                'last_failure' if task['status'] in {'failed', 'budget_blocked', 'blocked'} else None)
            if category and (item[category] is None or order(task, 'completed_at') > order(item[category], 'completed_at')):
                item[category] = task
        for item in result.values():
            inserted = item.pop('_inserted')
            if _timestamp_epoch(inserted['updated_at']) is None:
                item['latest_task'] = inserted
                item['ordering'] = 'LATEST_INSERTED_TASK_TIMESTAMP_UNORDERABLE'
            else:
                item['ordering'] = 'MOST_RECENT_TASK_TRANSITION'
            item['status'] = item['latest_task']['status']
            item['observed_at'] = item['latest_task']['updated_at']
            for key in ('latest_task', 'last_success', 'last_failure'):
                task = item[key]
                if task is None:
                    continue
                task = item[key] = dict(task)
                task.pop('_rowid')
                task.pop('agent')
                task['job_id'] = task.pop('id')
                task['task_id'] = None
                task['task_id_status'] = 'OBJECTIVE_JOIN_NOT_OBSERVED'
                task['evidence_scope'] = 'COMPUTE_EXECUTION_NOT_OUTPUT_CORRECTNESS'
        _join_objective_ids(root, result)
        return result
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        if db is not None:
            db.close()


def _join_objective_ids(root, activity):
    """A journal job ID is not a parent objective ID; missing joins stay null."""
    tasks = [item[key] for item in activity.values() for key in
             ('latest_task', 'last_success', 'last_failure') if item[key] is not None]
    ids = {task['job_id'] for task in tasks if task['job_id'] is not None}
    path = root / 'objectives.db'
    if not ids or not path.is_file():
        return
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
        deadline = time.monotonic() + 0.2
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        placeholders = ','.join('?' for _ in ids)
        rows = db.execute(
            "SELECT o.id,json_extract(s.value,'$.dispatch.job.id') FROM objectives o,"
            f"json_each(o.steps_json) s WHERE json_extract(s.value,'$.dispatch.job.id') IN ({placeholders})",
            tuple(ids)).fetchall()
        joins = {}
        for task_id, job_id in rows:
            joins.setdefault(job_id, set()).add(task_id)
        for task in tasks:
            parents = joins.get(task['job_id'], set())
            if len(parents) == 1:
                task['task_id'] = next(iter(parents))
                task['task_id_status'] = 'OBJECTIVE_STORE_JOIN'
            elif len(parents) > 1:
                task['task_id_status'] = 'OBJECTIVE_JOIN_AMBIGUOUS'
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass
    finally:
        if db is not None:
            db.close()


def execution_configuration():
    flag = os.getenv('PRIME_REGISTRY_V1_ENABLED', os.getenv('ORQEVIA_REGISTRY_V1_ENABLED', ''))
    return {
        'dispatch_status': 'ENABLED' if flag == '1' else 'DISABLED' if flag == '0' else 'UNKNOWN',
        'execution_mode': os.getenv('ORQEVIA_OUTPUT_QUEUE_MODE', 'direct').strip().lower(),
        'runtime_model': 'LOGICAL_ON_DEMAND_SHARED_INFERENCE',
        'dedicated_worker_expected': False,
        'source': 'RUNTIME_CONFIGURATION',
    }


def role_observation(agent, record, *, collector_available, now, max_age_seconds,
                     model_runtime, configuration):
    latest = record['latest_task'] if record else None
    activity = timestamp_observation(latest['updated_at'] if latest else None,
                                     now=now, max_age_seconds=max_age_seconds)
    model_time = timestamp_observation(model_runtime.get('observed_at'), now=now, max_age_seconds=60)
    completion = timestamp_observation(latest.get('completed_at') if latest else None,
                                       now=now, max_age_seconds=max_age_seconds)
    status = latest['status'] if latest else None
    reason = None
    readiness = 'UNCONFIRMED'
    blocker = None
    if agent.get('lifecycle_status') != 'active':
        readiness, reason = 'DISABLED', 'ROLE_LIFECYCLE_NOT_ACTIVE'
    elif configuration['dispatch_status'] == 'DISABLED':
        readiness, reason = 'DISABLED', 'ADVISORY_DISPATCH_DISABLED'
    elif configuration['dispatch_status'] != 'ENABLED' or configuration['execution_mode'] not in {'direct', 'queued'}:
        reason = 'EXECUTION_CONFIGURATION_UNCONFIRMED'
    elif not collector_available:
        reason = 'COMPUTE_JOURNAL_UNAVAILABLE'
    elif not latest:
        reason = 'NO_RECORDED_TASK'
    elif activity['status'] != 'OBSERVED':
        reason = activity['reason']
    elif status in {'failed', 'budget_blocked', 'blocked', 'cancelled'}:
        reason = 'LATEST_TASK_' + status.upper()
    elif status != 'completed':
        reason = 'TASK_EXECUTION_IN_PROGRESS' if status == 'running' else 'TASK_COMPLETION_NOT_CONFIRMED'
    elif completion['status'] != 'OBSERVED':
        reason = 'COMPLETION_' + (completion['reason'] or 'UNCONFIRMED')
    elif not latest.get('job_id'):
        reason = 'JOB_ID_NOT_RECORDED'
    elif model_runtime.get('status') != 'OBSERVED' or model_time['status'] != 'OBSERVED':
        reason = 'CURRENT_MODEL_OBSERVATION_UNAVAILABLE'
    elif model_runtime.get('ready') is not True:
        reason = 'CONFIGURED_MODELS_UNAVAILABLE'
        readiness = 'BLOCKED'
        blocker = {'scope': 'CONFIGURED_MODEL_INFERENCE', 'reason_code': reason}
    else:
        readiness, reason = 'CONFIRMED', 'RECENT_SUCCESSFUL_EXECUTION_AND_CURRENT_MODEL_OBSERVATION'
    availability = ('RUNNING' if status == 'running' else 'QUEUED' if status in {'queued', 'awaiting_approval'}
                    else 'IDLE' if record else 'NOT_OBSERVED' if collector_available else 'COLLECTOR_UNAVAILABLE')
    return {
        'agent_id': agent['id'], 'name': agent['name'], 'registration': 'REGISTERED',
        'lifecycle_status': agent.get('lifecycle_status'), 'capability_ids': agent.get('capability_requirements', []),
        'availability': availability, 'availability_scope': 'LAST_RECORDED_TASK_STATE_NOT_PROCESS_LIVENESS',
        'runtime_model': configuration['runtime_model'], 'heartbeat': None,
        'heartbeat_status': 'NOT_COLLECTED', 'heartbeat_reason': 'LOGICAL_ON_DEMAND_ROLE_WITHOUT_DEDICATED_WORKER',
        'last_activity_at': latest['updated_at'] if latest else None,
        'activity_source': 'compute-queue', 'activity_freshness': activity,
        'last_task': latest, 'last_success': record['last_success'] if record else None,
        'last_failure': record['last_failure'] if record else None,
        'history_count': record['history_count'] if record else (0 if collector_available else None),
        'task_ordering': record['ordering'] if record else 'NO_TASK_OBSERVATION',
        'readiness_status': readiness, 'reason_code': reason, 'blocker': blocker,
        'dependency_summary': {
            'registry': 'OBSERVED', 'dispatch': configuration['dispatch_status'],
            'execution_mode': configuration['execution_mode'],
            'compute_journal': 'OBSERVED' if collector_available else 'UNAVAILABLE',
            'model_runtime': model_runtime.get('status', 'UNAVAILABLE'),
            'model_available': model_runtime.get('ready'),
            'model_observed_at': model_runtime.get('observed_at'), 'model_observation_freshness': model_time,
            'required_models': model_runtime.get('required_models', []),
            'missing_models': model_runtime.get('missing_models', []),
            'role_competence': 'NOT_ESTABLISHED_BY_EXECUTION_OR_COACHING_COUNT',
        },
    }


def snapshot(client_id, role, *, model_runtime_probe=None, work_observation=None):
    observed = datetime.now(timezone.utc).isoformat()
    registry = load_agent_registry()
    stores = telemetry_store_counts()
    from .coaching_observation import coaching_snapshot
    from .observability_health import operational_health_snapshot
    coaching = coaching_snapshot(Path(os.getenv('ORQEVIA_DATA_DIR','/data')))
    activity = agent_activity()
    model_runtime = model_runtime_probe or model_runtime_readiness()
    instance = os.getenv('ORQEVIA_INTERFACE_HOST_ID', 'UNKNOWN')
    revision = os.getenv('ORQEVIA_INTERFACE_RUNTIME_REVISION', 'UNKNOWN')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', instance):
        instance = 'UNKNOWN'
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        revision = 'UNKNOWN'

    def metric(name, value, status, producer, unit='count', *, event_timestamp=None,
               reason=None, source=None, age_seconds=None):
        return {'metric_id': name, 'value': value, 'unit': unit,
                'collection_status': status, 'source_system': 'ORQEVIA',
                'source_instance': instance, 'producer': producer,
                'scope': 'WORKSPACE_AGGREGATE', 'event_timestamp': event_timestamp,
                'observed_at': observed,
                'reason': reason, 'source': source, 'age_seconds': age_seconds,
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
        detail = host.get('field_status', {}).get(field, {})
        status = detail.get('collection_status', 'OBSERVED' if value is not None else 'UNAVAILABLE')
        captured = detail.get('captured_at', host.get('captured_at'))
        event_timestamp = None
        if type(captured) in (int, float) and math.isfinite(captured):
            try:
                event_timestamp = datetime.fromtimestamp(captured, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        metrics.append(metric(name, value if status == 'OBSERVED' else None, status, host_producer, unit,
                              event_timestamp=event_timestamp,
                              reason=detail.get('reason', host.get('reason')),
                              source=detail.get('source', host.get('source')),
                              age_seconds=host.get('age_seconds')))
    max_age_seconds = queue_freshness_seconds()
    now_epoch = datetime.fromisoformat(observed).timestamp()
    configuration = execution_configuration()
    agents = [role_observation(agent, activity.get(agent['id']) if activity is not None else None,
                              collector_available=activity is not None, now=now_epoch,
                              max_age_seconds=max_age_seconds, model_runtime=model_runtime,
                              configuration=configuration) for agent in registry['agents']]
    observed_count = sum(item['last_task'] is not None for item in agents) if activity is not None else None
    fresh_agent_ids = [item['agent_id'] for item in agents if item['activity_freshness']['status'] == 'OBSERVED']
    fresh_count = len(fresh_agent_ids) if activity is not None and max_age_seconds is not None else None
    model_time = timestamp_observation(model_runtime.get('observed_at'), now=now_epoch, max_age_seconds=60)
    readiness_observed = (fresh_count is not None and model_runtime.get('status') == 'OBSERVED'
                          and model_time['status'] == 'OBSERVED'
                          and configuration['dispatch_status'] in {'ENABLED', 'DISABLED'}
                          and configuration['execution_mode'] in {'direct', 'queued'})
    ready = sum(item['readiness_status'] == 'CONFIRMED' for item in agents) if readiness_observed else None
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
    work = work_observation if isinstance(work_observation, dict) else {
        'schema_version': 'orqevia.owned-work.v1', 'status': 'UNAVAILABLE',
        'scope': 'CLIENT', 'observed_at': observed, 'tasks': [], 'activity': [],
        'has_more': False, 'reason': 'OWNED_WORK_OBSERVER_NOT_AVAILABLE'}
    return {'schema_version': 'orqevia.telemetry.v1', 'snapshot_id': str(uuid.uuid4()),
            'observed_at': observed, 'freshness_seconds': 60,
            'audience': {'client_id': client_id, 'role': role},
            'source': {'system': 'ORQEVIA', 'instance': instance, 'revision': revision},
            'metrics': metrics,
            'host': host,
            'ready_agent_count': ready,
            'confirmed_readiness_count': ready,
            'observed_agent_count': observed_count,
            'fresh_agent_count': fresh_count,
            'unconfirmed_agent_count': sum(item['readiness_status'] == 'UNCONFIRMED' for item in agents),
            'disabled_agent_count': sum(item['readiness_status'] == 'DISABLED' for item in agents),
            'blocked_agent_count': sum(item['readiness_status'] == 'BLOCKED' for item in agents),
            'readiness_scope': 'RECENT_SUCCESSFUL_EXECUTION_WITH_CURRENT_MODEL_OBSERVATION_NOT_ROLE_COMPETENCE',
            'execution_configuration': configuration,
            'queue_freshness': {
                'status': 'OBSERVED' if fresh_count is not None else 'UNAVAILABLE',
                'max_age_seconds': max_age_seconds,
                'fresh_agent_count': fresh_count,
                'not_fresh_agent_count': len(not_fresh_agent_ids) if fresh_count is not None else None,
                'not_fresh_agent_ids': not_fresh_agent_ids,
                'rule': 'latest actual task transition must have an explicit timezone, be within max age, and no more than five seconds in the future; failures count as activity, never confirmed readiness',
            },
            'model_runtime': model_runtime,
            **operational_health_snapshot(),
            'agents': agents,
            'coaching': coaching,
            'work_observation': work,
            'privacy': {'aggregate_only': not bool(work.get('tasks')),
                        'private_tasks_exposed': bool(work.get('tasks')),
                        'authorized_task_metadata_only': True,
                        'unrelated_tasks_exposed': False,
                        'model_content_exposed': False, 'credentials_exposed': False}}
