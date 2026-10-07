"""Pure HF applicability view, not routing policy or certification authority.

Inputs are the source registry and an optional already-sanitized HF domain
observation. This view resolves no credential, reads no runtime store, performs
no probe and grants no model/tool access. A digest is provenance, not a signature.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
from uuid import UUID

from .agent_registry import load_agent_registry

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z')
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ATTEMPT_FIELDS = frozenset(('attempt_id', 'queue_job_id', 'agent_id',
    'requested_provider', 'requested_model', 'selected_provider', 'selected_model',
    'tier', 'success', 'failure_code', 'fallback_route', 'error_classifications',
    'retries', 'total_tokens', 'cached_tokens', 'cost_usd', 'elapsed_seconds',
    'job_started_at', 'job_completed_at', 'evidence_sha256'))
_UNKNOWN = 'UNKNOWN'


def _uuid(value):
    return type(value) is str and len(value) == 36 and str(UUID(value)) == value


def _stamp(value):
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ValueError('Invalid timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.year < 2000:
        raise ValueError('Invalid timestamp')
    return result


def _number(value, maximum, integer=False):
    return value is None or (type(value) in ((int,) if integer else (int, float))
        and math.isfinite(value) and 0 <= value <= maximum)


def _providers(observation):
    if (type(observation) is not dict or observation.get('schema_version') != 'jarvis.hf-observation.v1'
        or observation.get('inspection_scope') != 'READ_ONLY_DOMAIN_PROJECTION_NOT_PROVIDER_PROBE_OR_CERTIFICATION'
        or observation.get('verification') != 'UNVERIFIED'
        or observation.get('provider_health') != 'UNMEASURED'
        or observation.get('network_probe_performed') is not False):
        raise ValueError('Invalid observation contract')
    _stamp(observation.get('inspection_at'))
    rows = observation.get('providers')
    if type(rows) is not list or len(rows) > 32:
        raise ValueError('Invalid provider projection')
    result, seen, pairs = [], set(), set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('Invalid provider projection')
        pid, model = row.get('provider_id'), row.get('model')
        if (type(pid) is not str or not _ID.fullmatch(pid) or pid in seen
            or type(model) is not str or not _MODEL.fullmatch(model) or '://' in model
            or type(row.get('enabled')) is not bool
            or row.get('catalog_qualification') != 'DECLARED_NOT_INDEPENDENTLY_VERIFIED'
            or row.get('provider_health') != 'UNMEASURED'
            or row.get('network_probe_performed') is not False):
            raise ValueError('Invalid provider projection')
        seen.add(pid)
        pairs.add((pid, model))
        circuit = row.get('circuit')
        circuit_state = _UNKNOWN
        if (type(circuit) is dict and circuit.get('provider_id') == pid
            and circuit.get('scope') == 'PROCESS_LOCAL_ADMISSION_NOT_PROVIDER_HEALTH'
            and circuit.get('replay_authorized') is False
            and circuit.get('circuit_state') in {'CLOSED', 'OPEN', 'HALF_OPEN'}):
            circuit_state = circuit['circuit_state']
        result.append({'provider_id': pid, 'model': model, 'configured': True,
            'enabled': row['enabled'], 'readiness': row.get('readiness')
                if row.get('readiness') in {'READY', 'CREDENTIAL_UNAVAILABLE', 'DISABLED', 'UNKNOWN'} else _UNKNOWN,
            'declared_qualification': row.get('declared_qualification')
                if row.get('declared_qualification') in {'QUALIFIED', 'UNQUALIFIED', 'CANDIDATE', 'DISABLED'} else _UNKNOWN,
            'qualification_verification': 'UNVERIFIED', 'provider_health': 'UNMEASURED',
            'circuit_state': circuit_state, 'circuit_scope': 'PROCESS_LOCAL_ADMISSION_NOT_PROVIDER_HEALTH'})
    registration = observation.get('registration_status')
    if (registration not in {'CONFIGURED', 'NOT_CONFIGURED', 'UNAVAILABLE'}
        or registration == 'CONFIGURED' and not rows
        or registration != 'CONFIGURED' and rows):
        raise ValueError('Invalid registration binding')
    return result, pairs, registration


def _attempt(row, agents, pairs, captured):
    if type(row) is not dict or set(row) != _ATTEMPT_FIELDS:
        raise ValueError('Invalid attempt contract')
    if (type(row['attempt_id']) is not str or not re.fullmatch(r'[0-9a-f]{32}', row['attempt_id'])
        or not _uuid(row['queue_job_id']) or type(row['agent_id']) is not str or row['agent_id'] not in agents
        or type(row['success']) is not bool or row['tier'] not in {'NANO', 'MINI', 'FLAGSHIP'}):
        raise ValueError('Invalid attempt binding')
    requested = (row['requested_provider'], row['requested_model'])
    selected = (row['selected_provider'], row['selected_model'])
    # HF inspection publishes HF registrations only. A domain-validated explicit
    # non-HF alternate may appear in dated evidence, never as configured here.
    if (any(type(item) is not str for item in requested + selected)
        or not _ID.fullmatch(requested[0]) or not _ID.fullmatch(selected[0])
        or not _MODEL.fullmatch(requested[1]) or not _MODEL.fullmatch(selected[1])
        or '://' in requested[1] or '://' in selected[1]
        or requested not in pairs and selected not in pairs
        or row['success'] != (row['failure_code'] is None)):
        raise ValueError('Invalid route binding')
    codes, routes = row['error_classifications'], row['fallback_route']
    if (type(codes) is not list or len(codes) > 16
        or any(type(code) is not str or not re.fullmatch(r'[A-Z][A-Z_]{0,79}', code) for code in codes)
        or len(set(codes)) != len(codes) or type(routes) is not list or len(routes) > 4
        or row['failure_code'] is not None and row['failure_code'] not in codes):
        raise ValueError('Invalid failure projection')
    failed = []
    for route in routes:
        if (type(route) is not dict or set(route) != {'provider', 'code'}
            or type(route['provider']) is not str or not _ID.fullmatch(route['provider'])
            or route['provider'] in failed or route['code'] not in codes):
            raise ValueError('Invalid failure projection')
        failed.append(route['provider'])
    if (not routes and selected != requested or routes and failed[0] != requested[0]
        or row['success'] and selected[0] in failed):
        raise ValueError('Invalid failover binding')
    for field, upper, integer in (('retries', 10, True), ('total_tokens', 10**9, True),
        ('cached_tokens', 10**9, True), ('cost_usd', 100, False), ('elapsed_seconds', 86400, False)):
        if not _number(row[field], upper, integer):
            raise ValueError('Invalid accounting')
    if (row['retries'] is None or row['elapsed_seconds'] is None
        or row['cached_tokens'] is not None and row['total_tokens'] is not None
            and row['cached_tokens'] > row['total_tokens']):
        raise ValueError('Invalid accounting')
    started, ended = _stamp(row['job_started_at']), _stamp(row['job_completed_at'])
    if ended < started or ended > captured:
        raise ValueError('Invalid dated evidence')
    unsigned = {key: value for key, value in row.items() if key != 'evidence_sha256'}
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    if type(row['evidence_sha256']) is not str or not _SHA.fullmatch(row['evidence_sha256']) or digest != row['evidence_sha256']:
        raise ValueError('Invalid evidence digest')
    return dict(row)


def _evidence(observation, agents, pairs):
    evidence = observation.get('objective_evidence')
    if evidence is None:
        return None, []
    if type(evidence) is not dict:
        raise ValueError('Invalid evidence projection')
    if evidence.get('status') in {'MISSING', 'INVALID'}:
        return {'status': evidence['status'], 'verification': 'UNVERIFIED'}, []
    task, revision = evidence.get('objective_id'), evidence.get('revision')
    if (not _uuid(task) or type(revision) is not int or not 0 <= revision <= 10**9
        or evidence.get('record_id') != f'objective:{task}:r{revision}'
        or evidence.get('source') != 'PRIME_OBJECTIVE_STORE'
        or evidence.get('status') not in {'OBSERVED', 'PARTIAL', 'MISSING', 'UNAVAILABLE', 'INVALID', 'NOT_APPLICABLE'}
        or evidence.get('integrity') != 'VALID' or evidence.get('currentness') not in {'CURRENT', 'STALE'}
        or evidence.get('verification') != 'UNVERIFIED'
        or evidence.get('independent_signature') != 'UNVERIFIED'
        or evidence.get('currentness_basis') != 'OBJECTIVE_SNAPSHOT_EQUALITY_NOT_TIME_FRESHNESS'
        or evidence.get('time_freshness') != 'UNKNOWN'
        or evidence.get('runtime_binding') != 'UNVERIFIED'
        or evidence.get('production_acceptance') != 'UNVERIFIED'):
        raise ValueError('Invalid evidence binding')
    captured = _stamp(evidence.get('captured_at'))
    if captured > _stamp(observation['inspection_at']):
        raise ValueError('Capture exceeds observation')
    rows = evidence.get('hf_attempts')
    if type(rows) is not list or len(rows) > 64:
        raise ValueError('Invalid attempt projection')
    attempts = [_attempt(row, agents, pairs, captured) for row in rows]
    if len({row['attempt_id'] for row in attempts}) != len(attempts):
        raise ValueError('Duplicate attempt evidence')
    return {'status': evidence['status'], 'objective_id': task, 'record_id': evidence['record_id'],
        'revision': revision, 'source': 'PRIME_OBJECTIVE_STORE_AND_EVIDENCE_LENS',
        'integrity': 'VALID', 'currentness': evidence['currentness'],
        'time_freshness': 'UNKNOWN', 'captured_at': evidence['captured_at'],
        'verification': 'UNVERIFIED', 'independent_signature': 'UNVERIFIED'}, attempts


def project_hf_operational_profile(hf_observation=None):
    """Expose declared role applicability separately from observed dated work.

    All current permanent roles can make provided-context text contributions.
    None declares a Hugging Face-specific requirement. This does not qualify a
    model for that role, override task tiers, or authorize disclosure or effects.
    """
    registry = load_agent_registry()
    ids = {agent['id'] for agent in registry['agents']}
    if len(ids) != 21 or len(registry['agents']) != 21:
        raise ValueError('Permanent registry contract invalid')
    providers, evidence, attempts, registration, observation_status = [], None, [], _UNKNOWN, 'UNAVAILABLE'
    if hf_observation is not None:
        try:
            providers, pairs, registration = _providers(hf_observation)
            evidence, attempts = _evidence(hf_observation, ids, pairs)
            observation_status = 'OBSERVED_DOMAIN_METADATA_UNVERIFIED'
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            providers, evidence, attempts, registration, observation_status = [], None, [], _UNKNOWN, 'INVALID_DOMAIN_OBSERVATION'
    agents = []
    for agent in registry['agents']:
        eligible = 'provided_context.read' in agent['tool_eligibility'] and bool(agent['model_tier_eligibility'])
        dated = [row for row in attempts if row['agent_id'] == agent['id']]
        successful = [row for row in dated if row['success'] is True]
        last = max(successful, key=lambda row: _stamp(row['job_completed_at'])) if successful else None
        success = None
        if last:
            success = {key: last[key] for key in ('attempt_id', 'queue_job_id', 'selected_provider',
                'selected_model', 'tier', 'job_completed_at', 'evidence_sha256', 'total_tokens', 'cost_usd')}
            success.update(status='OBSERVED_DATED_EXECUTION_NOT_QUALITY_OR_HEALTH',
                objective_id=evidence['objective_id'], evidence_ref=evidence['record_id'],
                currentness=evidence['currentness'], verification='UNVERIFIED',
                selected_provider_configuration='DECLARED_HF_ENTRY' if any(
                    row['provider_id'] == last['selected_provider'] and row['model'] == last['selected_model']
                    for row in providers) else 'UNKNOWN_NOT_IN_HF_PROVIDER_PROJECTION')
        agents.append({'agent_id': agent['id'], 'name': agent['name'], 'role': agent['role'],
            'applicability': 'OPTIONAL' if eligible else 'NOT_APPLICABLE',
            'applicability_basis': 'REGISTRY_PROVIDED_CONTEXT_TEXT_ADVISORY_ELIGIBILITY_NOT_HF_REQUIREMENT',
            'responsibilities': [row['id'] for row in agent['responsibilities']],
            'model_tier_eligibility': list(agent['model_tier_eligibility']),
            'authorization': 'NOT_GRANTED_BY_PROFILE',
            'last_dated_success': success,
            'failover_observation': 'OBSERVED_DATED_UNVERIFIED' if any(row['success'] and row['fallback_route'] for row in dated) else _UNKNOWN,
            'provider_health': 'UNMEASURED', 'role_quality': _UNKNOWN,
            'independent_attestation': 'UNVERIFIED', 'l7_status': 'NOT_ASSESSED_BY_THIS_PROFILE'})
    return {'schema_version': 'jarvis.hf-operational-profile.v1',
        'source': 'REGISTRY_AND_HF_DOMAIN_PROJECTION_NOT_POLICY_AUTHORITY',
        'registry_version': registry['registry_version'], 'permanent_agent_count': len(agents),
        'authoritative_agent_ids': [row['agent_id'] for row in agents],
        'observation_status': observation_status, 'registration_status': registration,
        'providers': providers, 'agents': agents, 'persisted_lens_evidence': evidence,
        'required_admission': ['AUTHENTICATED_DISPATCH', 'PERMITTED_CONTEXT', 'EXPLICIT_HF_SELECTION',
            'CLOUD_PERMITTED', 'SUFFICIENT_QUALIFIED_TIER', 'ALLOWED_TASK_CLASS', 'RESERVED_COST'],
        'not_applicable': ['MODEL_FREE_DETERMINISTIC_OPERATION', 'MODEL_AS_TOOL_EXECUTION_AUTHORITY'],
        'certification': 'SEPARATE_AGENT_CERTIFICATION_DOMAIN_NOT_ASSESSED',
        'network_probe_performed': False, 'model_calls': 0, 'verification': 'UNVERIFIED'}
