"""Bounded read-only observations; registry membership never means readiness."""
from datetime import datetime, timezone
import os
import re
import uuid

from .agent_registry import load_agent_registry


def snapshot():
    from .interface_observations import telemetry_store_counts
    observed = datetime.now(timezone.utc).isoformat()
    registry = load_agent_registry()
    stores = telemetry_store_counts()
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
                'event_timestamp': None, 'observed_at': observed,
                'provenance': 'READ_ONLY_STORE_OBSERVATION' if status == 'OBSERVED' else 'NO_MEASUREMENT'}
    jobs = stores['compute_jobs']
    counts = jobs.get('status_counts')
    active = sum(counts.get(s, 0) for s in ('queued', 'running', 'awaiting_approval')) if counts is not None else None
    metrics = [metric('registered_agents', len(registry['agents']), 'OBSERVED', 'agent-registry'),
               metric('active_job_records', active, 'OBSERVED' if active is not None else 'UNAVAILABLE', 'compute-queue'),
               metric('stored_objectives', stores['objectives']['count'], stores['objectives']['status'], 'objective-store')]
    metrics += [metric(n, None, 'UNAVAILABLE', 'No authorized host collector configured', u)
                for n, u in [('cpu', 'percent'), ('memory', 'percent'), ('disk', 'percent'), ('network_latency', 'ms')]]
    return {'schema_version': 'orqevia.telemetry.v1', 'observation_id': str(uuid.uuid4()),
            'observed_at': observed, 'freshness_seconds': 60,
            'source': {'instance': instance, 'revision': revision, 'scope': 'ORQEVIA_LOCAL_RUNTIME'},
            'metrics': metrics,
            'agents': [{'agent_id': a['id'], 'name': a['name'], 'role': a['role'],
                        'registration': 'REGISTERED', 'availability': 'UNKNOWN',
                        'heartbeat': None, 'last_success': None, 'last_failure': None,
                        'evidence_status': 'No per-agent live execution/heartbeat observation in this projection'}
                       for a in registry['agents']],
            'ready_agent_count': None, 'critical_issue_count': None, 'core_services_percent': None,
            'activity': {'status': 'UNAVAILABLE', 'reason': 'Use the existing owned-task event stream; no global private task projection'},
            'deadlines': {'status': 'UNAVAILABLE', 'reason': 'No authoritative deadline store is configured'},
            'controls': {'pause_all': 'UNAVAILABLE', 'emergency_stop': 'UNAVAILABLE',
                         'reboot_services': 'UNAVAILABLE', 'safe_mode': 'UNAVAILABLE'},
            'privacy': {'aggregate_only': True, 'private_tasks_exposed': False, 'credentials_exposed': False}}
