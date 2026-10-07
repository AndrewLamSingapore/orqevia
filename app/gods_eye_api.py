"""Bounded read-only God’s Eye projection; domain stores retain their authority.

No prompts, generated text, credentials, filesystem paths or raw manifests leave
this boundary. A completed job is an observation, not a correct answer or L7.
The loopback control boundary is operator access, not an enrolled PWA identity.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from uuid import UUID

from .agent_registry import load_agent_registry

MAX_TASKS = 12
MAX_JOBS = 50
MAX_RESPONSE_BYTES = 262144
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REV = re.compile(r"[0-9a-f]{40}\Z")
_GATE = threading.BoundedSemaphore(1)
_CACHE = None
_CACHE_AT = 0.0
_CACHE_SCOPE = None


def _id(value):
    return value if type(value) is str and _SAFE_ID.fullmatch(value) else None


def _uuid(value):
    try:
        return value if type(value) is str and str(UUID(value)) == value else None
    except ValueError:
        return None


def _timestamp(value):
    try:
        if type(value) is not str or len(value) > 40:
            return None
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or not 2000 <= parsed.year <= 2100:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _enum(value, allowed, default='UNKNOWN'):
    return value if type(value) is str and value in allowed else default


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _safe_runtime(runtime):
    source = runtime.get('source_revision')
    image = runtime.get('image_digest')
    return {'status': 'OBSERVED', 'source_revision': source if type(source) is str and _REV.fullmatch(source) else 'UNKNOWN',
            'image_digest': image if type(image) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', image) else None,
            'environment': 'PRODUCTION_REPORTED', 'verification': 'UNVERIFIED',
            'source': 'RUNTIME_CONFIGURATION', 'currentness': 'OBSERVED_NOW',
            'identity_verification': 'UNVERIFIED',
            'disclosure': 'Configuration metadata is not independent deployment identity or acceptance.'}


def project_snapshot(*, runtime, certification_rows, jobs, objectives, lens, now=None, registry=None, hf_observation=None):
    """Pure explicit whitelist projection. Inputs are domain observations, not authority grants."""
    registry = registry or load_agent_registry()
    owned = {a['id']: a for a in registry['agents']}
    if len(owned) != 21 or len(registry['agents']) != 21:
        raise ValueError('GODS_EYE_REGISTRY_DIVERGENCE')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('GODS_EYE_TIME_REQUIRES_TIMEZONE')
    observed_at = now.astimezone(timezone.utc).isoformat()
    safe_runtime = _safe_runtime(runtime)
    cert = {r['agent_id']: r for r in certification_rows
            if type(r) is dict and type(r.get('agent_id')) is str}
    cert_consistent = len(cert) == 21 and set(cert) == set(owned) and len(certification_rows) == 21
    safe_jobs = []
    for row in jobs[:MAX_JOBS]:
        if type(row) is not dict or type(row.get('agent')) is not str or row['agent'] not in owned or not _uuid(row.get('id')):
            continue
        safe_jobs.append({'job_id': row['id'], 'agent_id': row['agent'],
            'state': _enum(row.get('status'), {'queued', 'running', 'completed', 'failed', 'cancelled', 'awaiting_approval'}),
            'created_at': _timestamp(row.get('created_at')), 'started_at': _timestamp(row.get('started_at')),
            'completed_at': _timestamp(row.get('completed_at')),
            'source': 'COMPUTE_QUEUE', 'currentness': 'OBSERVED_NOW'})
    tasks, results = [], []
    for row in objectives[:MAX_TASKS]:
        if type(row) is not dict or not _uuid(row.get('id')):
            continue
        metadata = row.get('execution_metadata')
        if type(metadata) is not dict or metadata.get('task_id') != row['id']:
            continue
        task_id = row['id']
        executions = metadata.get('agent_execution')
        executions = executions if type(executions) is list else []
        agent_ids = sorted({x.get('selected_agent_id') for x in executions[:50]
                            if type(x) is dict and x.get('registry_binding') == 'VERIFIED'
                            and type(x.get('selected_agent_id')) is str and x['selected_agent_id'] in owned})
        # A malformed/unknown selected identity is not quietly relabelled as a permanent agent.
        state = _enum(row.get('state'), {'RUNNING', 'WAITING FOR RESOURCE', 'COMPLETED', 'COMPLETED_WITH_FAILURES', 'reconciliation_required'})
        evidence = lens.get(task_id, {})
        evidence = evidence if type(evidence) is dict else {}
        expected_ref = f"objective:{task_id}:r{row.get('revision')}"
        bound = (type(evidence) is dict and evidence.get('task_id') == task_id
                 and evidence.get('record_id') == expected_ref and type(row.get('revision')) is int)
        integrity = _enum(evidence.get('integrity') if bound else None, {'VALID', 'INVALID'})
        currentness = _enum(evidence.get('currentness') if bound else None, {'CURRENT', 'STALE'})
        # Lens chain/snapshot equality never independently verifies a generated claim.
        verification = 'UNVERIFIED'
        task = {'id': task_id, 'task_id': task_id, 'state': state, 'agent_id': agent_ids[0] if len(agent_ids) == 1 else None,
                'created_at': _timestamp(metadata.get('created_at')), 'completed_at': _timestamp(metadata.get('completed_at')),
                'source': 'OBJECTIVE_STORE', 'currentness': 'OBSERVED_NOW', 'evidence_status': integrity}
        tasks.append(task)
        task_runtime = metadata.get('runtime')
        task_runtime = task_runtime if type(task_runtime) is dict else {}
        revision = task_runtime.get('source_revision')
        observed = evidence.get('observed')
        digest = observed.get('result_digest') if bound and type(observed) is dict else None
        # Lens owns a typed digest envelope; algorithm/canonical hex are required.
        digest = (digest.get('value') if type(digest) is dict and
                  set(digest) == {'algorithm', 'value'} and digest.get('algorithm') == 'sha256' else None)
        for agent_id in agent_ids:
            if len(results) >= 48:
                break
            results.append({'id': f"result:{task_id}:{agent_id}", 'task_id': task_id, 'agent_id': agent_id,
                'source_revision': revision if type(revision) is str and _REV.fullmatch(revision) else None,
                'environment': 'PRODUCTION', 'environment_verification': 'UNVERIFIED',
                'integrity': integrity, 'currentness': currentness, 'verification': verification,
                'evidence_ref': expected_ref if bound else None,
                'result_sha256': digest if type(digest) is str and _SHA.fullmatch(digest) else None,
                'result_state': state, 'source': 'EVIDENCE_LENS_OBJECTIVE_PROJECTION'})
    agents, metrics = [], []
    l7_count = 0
    for identity, row in sorted(owned.items()):
        observed = cert.get(identity, {}) if cert_consistent else {}
        level = _enum(observed.get('level'), {f'L{i}' for i in range(8)}, 'UNKNOWN')
        trust = _enum(observed.get('trust_state'), {'L7-CURRENT', 'CERTIFIED-HEALTHY', 'CERTIFIED-DEGRADED', 'REVALIDATION-REQUIRED', 'UNPROVEN'})
        l7 = level == 'L7' and trust == 'L7-CURRENT'
        l7_count += int(l7)
        recent = [j for j in safe_jobs if j['agent_id'] == identity]
        running = [j for j in recent if j['state'] == 'running']
        live = 'RUNNING' if running else 'QUEUED' if any(j['state'] == 'queued' for j in recent) else 'NO_ACTIVE_JOB_IN_OBSERVED_WINDOW' if recent else 'UNKNOWN'
        associated = [r for r in results if r['agent_id'] == identity]
        if associated:
            metrics.append({'metric_id': f'observed-task-count:{identity}', 'agent_id': identity,
                'name': 'observed_task_count', 'value': len(associated), 'unit': 'count',
                'result_ids': [r['id'] for r in associated], 'scope': f'LATEST_{MAX_TASKS}_OBJECTIVES_ONLY',
                'currentness': 'OBSERVED_NOW', 'source': 'OBJECTIVE_STORE_DERIVATION',
                'provenance': 'Count of registry-bound agent contributions, not correctness or lifetime productivity.'})
        missing = observed.get('missing') if type(observed.get('missing')) is dict else {}
        safe_missing = {cap: [case for case in cases[:100] if _id(case)]
                        for cap, cases in missing.items() if cap in row['capability_requirements'] and type(cases) is list}
        agents.append({'id': identity, 'agent_id': identity, 'name': row['name'], 'role': row['role'], 'version': row['version'],
            'capabilities': sorted(row['capability_requirements']), 'live_state': live, 'current_status': live,
            'current_task_id': next((r['task_id'] for r in associated), None), 'task_id': next((r['task_id'] for r in associated), None),
            'runtime_activation': 'OBSERVED_JOB' if recent else 'UNVERIFIED',
            'l7_status': 'L7-CURRENT' if l7 else 'NOT_L7' if cert_consistent else 'UNKNOWN',
            'trust_state': trust, 'intended': {'capabilities': sorted(row['capability_requirements'])},
            'proven': {'level': level, 'trust_state': trust}, 'missing_cases': safe_missing,
            'quality': 'UNKNOWN', 'latency_ms': 'UNKNOWN', 'cost_usd': 'UNKNOWN',
            'reliability': 'UNKNOWN', 'autonomy': 'UNKNOWN', 'currentness': 'OBSERVED_NOW',
            'provenance': {'source_revision': safe_runtime['source_revision'], 'registry_version': registry['registry_version'],
                'intended_domain': 'AGENT_REGISTRY', 'execution_domain': 'COMPUTE_QUEUE', 'proven_domain': 'AGENT_CERTIFICATION'}})
    gates = [{'id': 'l7-certification', 'status': 'VERIFIED' if l7_count == 21 else 'UNVERIFIED',
              'dependency': 'Independent current per-agent cases and attestations', 'source': 'AGENT_CERTIFICATION', 'currentness': 'OBSERVED_NOW'},
             {'id': 'host-stability', 'status': 'UNKNOWN', 'dependency': 'Host qualification evidence is not provided by process liveness', 'source': 'HOST_DOMAIN', 'currentness': 'UNKNOWN'},
             {'id': 'deployment-acceptance', 'status': 'UNVERIFIED', 'dependency': 'Independent deployment identity and acceptance receipt', 'source': 'DEPLOYMENT_DOMAIN', 'currentness': 'UNKNOWN'},
             {'id': 'owner-iphone', 'status': 'UNKNOWN', 'dependency': 'Real authenticated end-to-end Owner path', 'source': 'IDENTITY_INTERFACE_DOMAIN', 'currentness': 'UNKNOWN'},
             {'id': 'rollback', 'status': 'UNKNOWN', 'dependency': 'Exact operator-owned restoration receipt', 'source': 'RECOVERY_DOMAIN', 'currentness': 'UNKNOWN'}]
    snapshot = {'schema_version': 'jarvis.gods-eye.v1', 'status': 'OBSERVED', 'observed_at': observed_at,
        'source_revision': safe_runtime['source_revision'], 'runtime': safe_runtime,
        'access_scope': 'LOOPBACK_OPERATOR_NOT_PWA_IDENTITY_PROOF',
        'registry': {'count': 21, 'agent_ids': sorted(owned), 'authoritative_ids': sorted(owned),
            'registry_version': registry['registry_version'], 'source': 'AGENT_REGISTRY',
            'label_divergence': 'A01-A21 is a population shorthand; immutable registry IDs are not contiguous.'},
        'agents': agents, 'tasks': tasks, 'results': results, 'metrics': metrics,
        'certification': {'status': 'OBSERVED' if cert_consistent else 'UNAVAILABLE', 'l7_count': l7_count if cert_consistent else None,
                          'source': 'AGENT_CERTIFICATION', 'disclosure': 'Job completion and signing alone cannot award L7.'},
        'evidence': {'status': 'OBSERVED' if results else 'UNAVAILABLE', 'source': 'EVIDENCE_LENS',
                     'currentness': 'OBJECTIVE_SCOPED', 'records': results},
        'observatory': {'status': 'PARTIAL', 'source': 'BOUNDED_DOMAIN_DERIVATION', 'currentness': 'OBSERVED_NOW', 'metrics': metrics,
                       'unmeasured': ['correctness', 'P95_latency', 'autonomy', 'recovery', 'cost', 'memory_precision']},
        'memory': {'status': 'UNAVAILABLE', 'source': 'MEMORY_DOMAIN', 'currentness': 'UNKNOWN'},
        'gates': gates, 'domains': {'tasks': {'status': 'OBSERVED', 'source': 'OBJECTIVE_STORE'},
                                  'host': {'status': 'UNKNOWN', 'source': 'HOST_DOMAIN'}}}
    from .hf_operational_profile import project_hf_operational_profile
    snapshot['hugging_face'] = project_hf_operational_profile(hf_observation)
    return snapshot


def semantic_projection(snapshot):
    """Semantic engine receives only its narrow typed contract, not arbitrary dashboard data."""
    return {'source_revision': snapshot['source_revision'],
        'agents': [{k: row[k] for k in ('id', 'name', 'role', 'version', 'capabilities')} for row in snapshot['agents']],
        'results': [{k: row.get(k) for k in ('id', 'task_id', 'agent_id', 'source_revision', 'environment', 'integrity',
                                           'currentness', 'verification', 'evidence_ref', 'result_sha256')} for row in snapshot['results']],
        'metrics': [{k: row[k] for k in ('metric_id', 'agent_id', 'result_ids', 'name', 'value', 'unit')} for row in snapshot['metrics']]}


def _readonly(path):
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError()
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    # Bounded queries cannot monopolize the Owner thread on an oversized store.
    started = time.monotonic()
    connection.set_progress_handler(lambda: int(time.monotonic() - started > 0.25), 1000)
    return connection


def collect_snapshot(authorization, *, verifier=None, protected_domains=False):
    """No create/migrate/recover/materialize/model/embedding operation in the read path."""
    from .client_auth import authenticate_owner
    authenticate_owner(authorization)
    from . import objective_api, evidence_lens_api
    from .evidence_product import observation_remaining
    from .agent_certification import AgentCertificationRegistry
    root = Path(os.getenv('PRIME_DATA_DIR', '/data'))
    deadline = time.monotonic() + 2.0
    runtime = objective_api.runtime_snapshot()
    jobs, objectives, lens = [], [], {}
    try:
        with closing(_readonly(Path(os.getenv('PRIME_COMPUTE_QUEUE_DB', str(root / 'compute-queue.db'))))) as db:
            jobs = [dict(row) for row in db.execute('SELECT id,agent,status,created_at,started_at,completed_at FROM compute_jobs ORDER BY CASE WHEN status IN (\'running\',\'queued\') THEN 0 ELSE 1 END,created_at DESC LIMIT ?', (MAX_JOBS,))]
    except (OSError, sqlite3.Error):
        pass
    try:
        with closing(_readonly(root / 'objectives.db')) as db:
            ids = [row[0] for row in db.execute('SELECT id FROM objectives WHERE length(steps_json)<=196608 ORDER BY rowid DESC LIMIT ?', (MAX_TASKS,))]
        for identity in ids:
            if time.monotonic() >= deadline:
                break
            if not _uuid(identity):
                continue
            try:
                task = objective_api.get_read_only(identity, authorization, observation_deadline=deadline)
                observation_remaining(deadline)
                objectives.append(task)
                lens[identity] = evidence_lens_api.read(identity, authorization,
                    observation_deadline=deadline, task=task)
            except Exception:
                # Public fixed UNKNOWN: private API exceptions may contain sensitive data.
                continue
    except (OSError, sqlite3.Error):
        pass
    certification_rows, hf_observation = [], None
    # One already-read objective, bounded to this snapshot's observed window.
    # No repeated store read, model call or provider-health inference.
    identity = next((row['id'] for row in objectives if row['id'] in lens), None)
    if protected_domains is True:
        cert = AgentCertificationRegistry(root / 'agent-certification', source_revision=runtime['source_revision'], verify_record=verifier)
        try:
            certification_rows = cert.matrix()
        except Exception:
            pass
        from .hf_observation_api import inspect_hf
        try:
            hf_observation = inspect_hf(authorization, identity,
                lens_observation=lens.get(identity) if identity else None)
        except Exception:
            pass
    result = project_snapshot(runtime=runtime, certification_rows=certification_rows, jobs=jobs, objectives=objectives, lens=lens,
        hf_observation=hf_observation)
    result['hugging_face']['evidence_window'] = f'ONE_OF_LATEST_{MAX_TASKS}_OBJECTIVES_NOT_LIFETIME_OR_ALL_AGENT_PROOF'
    result['certification']['independent_verifier'] = ('CONFIGURED' if verifier else 'UNCONFIGURED') if protected_domains is True else 'UNKNOWN'
    result['protected_domain_access'] = 'EXPLICIT_BEARER' if protected_domains is True else 'NOT_REQUESTED'
    return result


def snapshot(authorization, *, verifier=None, semantics=True, protected_domains=False):
    """Small process-local five-second cache, never an authoritative store."""
    from .client_auth import authenticate_owner
    authenticate_owner(authorization)  # Authentication precedes cache access.
    global _CACHE, _CACHE_AT, _CACHE_SCOPE
    if type(protected_domains) is not bool:
        raise ValueError('GODS_EYE_ACCESS_SCOPE_INVALID')
    if not _GATE.acquire(blocking=False):
        from fastapi import HTTPException
        raise HTTPException(503, 'Observation is busy')
    try:
        if _CACHE is not None and _CACHE_SCOPE == protected_domains and time.monotonic() - _CACHE_AT < 5:
            return json.loads(json.dumps(_CACHE))
        result = collect_snapshot(authorization, verifier=verifier, protected_domains=protected_domains)
        if semantics:
            from .semantic_fabric import build_semantics, SemanticError
            try:
                result['semantics'] = build_semantics(semantic_projection(result))
            except SemanticError:
                result['semantics'] = {'status': 'UNAVAILABLE', 'source': 'SEMANTIC_FABRIC', 'currentness': 'UNKNOWN'}
        if len(json.dumps(result, ensure_ascii=True).encode()) > MAX_RESPONSE_BYTES:
            from fastapi import HTTPException
            raise HTTPException(503, 'Observation budget exceeded')
        _CACHE, _CACHE_AT, _CACHE_SCOPE = json.loads(json.dumps(result)), time.monotonic(), protected_domains
        return result
    finally:
        _GATE.release()


def drilldown(authorization, query_id, subject, *, verifier=None, protected_domains=False):
    from .semantic_fabric import query_semantics, SemanticError
    from fastapi import HTTPException
    current = snapshot(authorization, verifier=verifier, protected_domains=protected_domains)
    try:
        result = query_semantics(semantic_projection(current), query_id, subject)
        if query_id == 'why':
            result['metrics'] = [m for m in current['metrics'] if m['agent_id'] == subject]
        return result
    except SemanticError:
        raise HTTPException(422, 'Semantic subject unavailable or invalid') from None
