"""Read-only HF inspection over existing domain-owned catalog/circuit/Lens state.

This projection is not a provider probe, verifier, deployment attestation, or
universal authority. The HTTP caller must also enforce the existing local
same-origin boundary and explicit bearer authentication. No new store is owned.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from uuid import UUID

from fastapi import HTTPException

from . import cloud_execution
from .client_auth import authenticate_owner
from .compute_catalog import load_catalog
from .provider_circuit import PROVIDER_FAULTS
from .provider_runtime import HuggingFaceProvider

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z')
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ATTEMPT_FIELDS = frozenset(('attempt_id', 'queue_job_id', 'agent_id',
    'requested_provider', 'requested_model', 'selected_provider', 'selected_model',
    'tier', 'success', 'failure_code', 'fallback_route', 'error_classifications',
    'retries', 'total_tokens', 'cached_tokens', 'cost_usd', 'elapsed_seconds',
    'job_started_at', 'job_completed_at', 'evidence_sha256'))


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value, now):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError()
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.year < 2000 or (stamp - now).total_seconds() > 5:
        raise ValueError()
    return stamp


def _number(value, upper, *, integer=False):
    if value is None:
        return
    if (type(value) not in ((int,) if integer else (int, float)) or
            not math.isfinite(value) or not 0 <= value <= upper):
        raise ValueError()


def _circuit(value, provider_id):
    fields = {'provider_id', 'circuit_state', 'consecutive_provider_failures',
        'retry_after_seconds', 'active_permits', 'recovery_probe_inflight',
        'last_failure_code', 'last_failure_pre_execution', 'scope', 'replay_authorized'}
    if (not isinstance(value, dict) or set(value) != fields or
            value['provider_id'] != provider_id or value['circuit_state'] not in
            {'CLOSED', 'OPEN', 'HALF_OPEN'} or value['scope'] !=
            'PROCESS_LOCAL_ADMISSION_NOT_PROVIDER_HEALTH' or value['replay_authorized'] is not False or
            type(value['recovery_probe_inflight']) is not bool or
            value['last_failure_code'] is not None and value['last_failure_code'] not in PROVIDER_FAULTS or
            value['last_failure_pre_execution'] is not None and
            type(value['last_failure_pre_execution']) is not bool):
        raise ValueError()
    for key, upper, integer in (('consecutive_provider_failures', 10**9, True),
                               ('active_permits', 64, True), ('retry_after_seconds', 86400, False)):
        if value[key] is None:
            raise ValueError()
        _number(value[key], upper, integer=integer)
    return dict(value)


def _read_lens(task_id, authorization):
    # An inspection of a missing store must not initialize application storage.
    root = Path(os.getenv('PRIME_DATA_DIR', '/data'))
    if not (root / 'objectives.db').is_file() or not (root / 'evidence-lens.db').is_file():
        raise HTTPException(404, 'Objective evidence unavailable')
    from . import evidence_lens_api
    return evidence_lens_api.read(task_id, authorization)


def _lens(value, task_id, pairs, hf_ids, now):
    from .agent_registry import agent_record
    from .objective_api import _INFERENCE_CODES
    base = {'objective_id': task_id, 'verification': 'UNVERIFIED', 'time_freshness': 'UNKNOWN',
            'source': 'PRIME_OBJECTIVE_STORE', 'independent_signature': 'UNVERIFIED'}
    if (not isinstance(value, dict) or value.get('verification') != 'UNVERIFIED' or
            value.get('record_id') != f"objective:{task_id}:r{value.get('revision', 0)}"):
        raise ValueError()
    if value.get('integrity') == 'INVALID':
        if value.get('currentness') != 'UNKNOWN':
            raise ValueError()
        return {**base, 'status': 'INVALID', 'integrity': 'INVALID', 'currentness': 'UNKNOWN'}
    observed, proof = value.get('observed'), value.get('proof')
    revision = value.get('revision')
    if (type(revision) is not int or not 0 <= revision <= 10**9 or value.get('task_id') != task_id or
            value.get('integrity') != 'VALID' or value.get('currentness') not in {'CURRENT', 'STALE'} or
            value.get('source') != 'PRIME_OBJECTIVE_STORE' or not isinstance(observed, dict) or
            observed.get('task_id') != task_id or observed.get('revision') != revision or
            not isinstance(proof, dict) or proof.get('producer') != 'PRIME_OBJECTIVE_STORE' or
            proof.get('currentness_basis') != 'OBJECTIVE_SNAPSHOT_EQUALITY' or
            proof.get('time_freshness') != 'UNKNOWN' or
            not {'independent_claim_verification', 'production_acceptance',
                 'source_revision_binding', 'runtime_image_binding'} <= set(proof.get('unproven', []))):
        raise ValueError()
    captured = _timestamp(proof.get('captured_at'), now)
    agents = observed.get('agent_ids')
    if (not isinstance(agents, list) or len(agents) > 21 or len(set(agents)) != len(agents) or
            observed.get('execution_state') not in {'COMPLETED', 'COMPLETED_WITH_FAILURES'} or
            value.get('result_state') != observed['execution_state']):
        raise ValueError()
    for actor in agents:
        agent_record(actor)
    projection = observed.get('inference_attempts')
    if (not isinstance(projection, dict) or projection.get('schema_version') != 'jarvis.inference-attempts.v1' or
            projection.get('source') != 'COMPUTE_LEDGER' or projection.get('verification') != 'UNVERIFIED' or
            projection.get('digest_scope') != 'SANITIZED_PROJECTION_NOT_SIGNATURE' or
            projection.get('status') not in {'OBSERVED', 'PARTIAL', 'MISSING', 'UNAVAILABLE', 'INVALID', 'NOT_APPLICABLE'} or
            not isinstance(projection.get('attempts'), list) or len(projection['attempts']) > 64):
        raise ValueError()
    attempts, seen = [], set()
    for attempt in projection['attempts']:
        if not isinstance(attempt, dict) or set(attempt) != _ATTEMPT_FIELDS:
            raise ValueError()
        aid = attempt['attempt_id']
        if not isinstance(aid, str) or not re.fullmatch('[0-9a-f]{32}', aid) or aid in seen:
            raise ValueError()
        seen.add(aid)
        if str(UUID(attempt['queue_job_id'])) != attempt['queue_job_id']:
            raise ValueError()
        agent_record(attempt['agent_id'])
        if attempt['agent_id'] not in agents:
            raise ValueError()
        requested = (attempt['requested_provider'], attempt['requested_model'])
        selected = (attempt['selected_provider'], attempt['selected_model'])
        if requested not in pairs or selected not in pairs or attempt['tier'] not in {'NANO', 'MINI', 'FLAGSHIP'}:
            raise ValueError()
        if (type(attempt['success']) is not bool or
                attempt['failure_code'] is not None and attempt['failure_code'] not in _INFERENCE_CODES or
                attempt['success'] != (attempt['failure_code'] is None)):
            raise ValueError()
        codes, routes = attempt['error_classifications'], attempt['fallback_route']
        if (not isinstance(codes, list) or len(codes) > 16 or any(code not in _INFERENCE_CODES for code in codes) or
                not isinstance(routes, list) or len(routes) > 4):
            raise ValueError()
        route_providers = set()
        for route in routes:
            if (not isinstance(route, dict) or set(route) != {'provider', 'code'} or
                    route['provider'] not in {item[0] for item in pairs} or
                    route['provider'] in route_providers or
                    route['code'] not in _INFERENCE_CODES or route['code'] not in codes):
                raise ValueError()
            route_providers.add(route['provider'])
        if (not routes and selected != requested or routes and routes[0]['provider'] != requested[0] or
                attempt['success'] and selected[0] in route_providers or
                attempt['failure_code'] is not None and attempt['failure_code'] not in codes or
                len(set(codes)) != len(codes) or attempt['retries'] is None or attempt['elapsed_seconds'] is None):
            raise ValueError()
        for key, upper, integer in (('retries', 10, True), ('total_tokens', 10**9, True),
                                   ('cached_tokens', 10**9, True), ('cost_usd', 100, False),
                                   ('elapsed_seconds', 86400, False)):
            _number(attempt[key], upper, integer=integer)
        if (attempt['cached_tokens'] is not None and attempt['total_tokens'] is not None and
                attempt['cached_tokens'] > attempt['total_tokens']):
            raise ValueError()
        _timestamp(attempt['job_started_at'], now)
        _timestamp(attempt['job_completed_at'], now)
        unsigned = {key: item for key, item in attempt.items() if key != 'evidence_sha256'}
        digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        if digest != attempt['evidence_sha256']:
            raise ValueError()
        if requested[0] in hf_ids or selected[0] in hf_ids:
            attempts.append(dict(attempt))
    return {**base, 'status': projection['status'], 'integrity': 'VALID',
            'currentness': value['currentness'], 'currentness_basis': 'OBJECTIVE_SNAPSHOT_EQUALITY_NOT_TIME_FRESHNESS',
            'record_id': value['record_id'], 'revision': revision, 'captured_at': proof.get('captured_at'),
            'capture_age_seconds': max(0.0, (now - captured).total_seconds()) if captured else None,
            'hf_attempts': attempts, 'hf_scope_status': 'OBSERVED' if attempts else 'NOT_OBSERVED',
            'claim_verification': 'VERIFY_REQUIRED',
            'runtime_binding': 'UNVERIFIED', 'production_acceptance': 'UNVERIFIED'}


def inspect_hf(authorization, task_id=None):
    """No network probe, model invocation, materialization, or credential export."""
    authenticate_owner(authorization)
    if task_id is not None:
        try:
            if str(UUID(task_id)) != task_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(404, 'Objective evidence unavailable') from None
    now = _now()
    report = {'schema_version': 'jarvis.hf-observation.v1', 'inspection_at': now.isoformat(),
        'inspection_scope': 'READ_ONLY_DOMAIN_PROJECTION_NOT_PROVIDER_PROBE_OR_CERTIFICATION',
        'provider_health': 'UNMEASURED', 'network_probe_performed': False,
        'verification': 'UNVERIFIED', 'providers': [],
        'provenance': {'registration': 'MODEL_CATALOG', 'readiness': 'LOCAL_CREDENTIAL_PREFLIGHT',
                       'circuit': 'PROCESS_LOCAL_PROVIDER_ADMISSION',
                       'objective_evidence': 'PRIME_OBJECTIVE_STORE_AND_EVIDENCE_LENS'},
        'freshness': {'inspection': 'CURRENT_READ', 'upstream_provider': 'UNKNOWN',
                      'objective_evidence': 'UNKNOWN_NO_ADOPTED_TIME_FRESHNESS_POLICY'}}
    pairs, hf_ids = set(), set()
    try:
        entries = load_catalog()
        if not isinstance(entries, list) or len(entries) > 32:
            raise ValueError()
        for entry in entries:
            pid, model = entry['id'], entry['model']
            if (not isinstance(pid, str) or not _ID.fullmatch(pid) or not isinstance(model, str) or
                    not _MODEL.fullmatch(model) or '://' in model or pid in {pair[0] for pair in pairs}):
                raise ValueError()
            pairs.add((pid, model))
            if entry.get('provider_kind') != 'huggingface':
                continue
            if type(entry.get('enabled')) is not bool or not HuggingFaceProvider._PINNED_MODEL.fullmatch(model):
                raise ValueError()
            hf_ids.add(pid)
            observation = {'provider_id': pid, 'model': model, 'enabled': entry['enabled'],
                'catalog_qualification': 'DECLARED_NOT_INDEPENDENTLY_VERIFIED',
                'declared_qualification': entry.get('qualification_status')
                    if entry.get('qualification_status') in {'QUALIFIED', 'UNQUALIFIED', 'CANDIDATE', 'DISABLED'}
                    else 'UNKNOWN',
                'provider_health': 'UNMEASURED', 'network_probe_performed': False}
            try:
                readiness = cloud_execution.adapter_for(entry).health() if entry['enabled'] else {
                    'readiness': 'DISABLED', 'provider_health': 'UNMEASURED', 'network_probe_performed': False}
                if (not isinstance(readiness, dict) or set(readiness) !=
                        {'readiness', 'provider_health', 'network_probe_performed'} or
                        readiness['readiness'] not in {'READY', 'CREDENTIAL_UNAVAILABLE', 'DISABLED'} or
                        readiness['provider_health'] != 'UNMEASURED' or readiness['network_probe_performed'] is not False):
                    raise ValueError()
                observation['readiness'] = readiness['readiness']
                observation['circuit'] = _circuit(cloud_execution.PROVIDER_CIRCUITS.snapshot(pid), pid)
            except Exception:
                observation.update(readiness='UNKNOWN', circuit={'status': 'UNAVAILABLE'},
                                   observation_error='INVALID_OR_UNAVAILABLE_READINESS')
            report['providers'].append(observation)
        report['registration_status'] = 'CONFIGURED' if hf_ids else 'NOT_CONFIGURED'
    except Exception:
        report.update(registration_status='UNAVAILABLE', providers=[], registration_error='MODEL_CATALOG_UNAVAILABLE')
        pairs, hf_ids = set(), set()
    if task_id is not None:
        try:
            report['objective_evidence'] = _lens(_read_lens(task_id, authorization), task_id, pairs, hf_ids, now)
        except HTTPException as exc:
            if exc.status_code in {401, 403}:
                raise
            report['objective_evidence'] = {'status': 'MISSING', 'verification': 'UNVERIFIED',
                                            'error_code': 'OBJECTIVE_OR_LENS_UNAVAILABLE'}
        except Exception:
            report['objective_evidence'] = {'status': 'INVALID', 'verification': 'UNVERIFIED',
                                            'error_code': 'UNBOUND_OR_UNSAFE_OBJECTIVE_EVIDENCE'}
    return report
