"""A19's distinct, zero-model initialization/contract inspection.

The owned Registry and the actual dispatch request model supply the definition
and input limits. No caller can supply an "initialized" verdict or replacement
contract. This report alone is not an Objective/artifact/action event join,
independent review, health observation, capability certification, or L7.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import uuid


CASE = 'baseline:initialization'
SCHEMA = 'jarvis.agent-initialization.v1'
ORACLE_ID = 'a19.owned-initialization.v1'
ACTION_TYPE = 'agent.certification.initialization.artifact'
OBJECTIVE = ('Inspect the current registered A19 role, advisory authority, owned '
             'input/output contracts and dispatch input bounds before beginning '
             'a reliability assessment; produce a zero-model initialization '
             'artifact and identify missing evidence without claiming health or certification.')
MAX_BYTES = 64 * 1024
MAX_REGISTRY_BYTES = 1024 * 1024
MAX_AGE_SECONDS = 300
_DEFINITION_FIELDS = (
    'agent_id', 'immutable_id', 'name', 'role', 'purpose', 'version',
    'lifecycle_status', 'status', 'authority', 'human_approval', 'can_delegate',
    'reports_to', 'capability_requirements', 'responsibilities',
    'non_responsibilities', 'input_contract', 'output_contract',
    'tool_eligibility', 'model_tier_eligibility', 'tap_relationship',
    'failure_fallback',
)


class InitializationError(ValueError):
    """Fixed, public-safe failure code; never raw Registry or request content."""


def _require(value, code):
    if value is not True:
        raise InitializationError(code) from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise InitializationError('INITIALIZATION_JSON_INVALID') from None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InitializationError('INITIALIZATION_DUPLICATE_FIELD')
        value[key] = item
    return value


def _finite(value):
    parsed = float(value)
    _require(math.isfinite(parsed), 'INITIALIZATION_NONFINITE_NUMBER')
    return parsed


def _constant(_):
    raise InitializationError('INITIALIZATION_NONFINITE_NUMBER')


def _parse(raw, limit):
    _require(type(raw) in (str, bytes), 'INITIALIZATION_BYTES_REQUIRED')
    try:
        encoded = raw.encode('utf-8') if type(raw) is str else raw
        _require(0 < len(encoded) <= limit, 'INITIALIZATION_SIZE_INVALID')
        value = json.loads(encoded.decode('utf-8'), object_pairs_hook=_unique,
                           parse_float=_finite, parse_constant=_constant)
        _require(type(value) is dict, 'INITIALIZATION_OBJECT_REQUIRED')
        return value
    except InitializationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise InitializationError('INITIALIZATION_JSON_INVALID') from None


def _instant(value):
    _require(type(value) is datetime and value.tzinfo is not None
             and value.utcoffset() is not None, 'INITIALIZATION_TIME_INVALID')
    return value.astimezone(timezone.utc)


def _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256):
    try:
        parsed = uuid.UUID(task_id) if type(task_id) is str else None
    except (ValueError, TypeError, AttributeError):
        parsed = None
    _require(parsed is not None and str(parsed) == task_id and parsed.version == 4,
             'INITIALIZATION_TASK_INVALID')
    _require(type(source_revision) is str
             and re.fullmatch('[0-9a-f]{40}', source_revision) is not None,
             'INITIALIZATION_SOURCE_INVALID')
    _require(type(runtime_image_id) is str
             and re.fullmatch('sha256:[0-9a-f]{64}', runtime_image_id) is not None,
             'INITIALIZATION_IMAGE_INVALID')
    _require(type(registry_sha256) is str
             and re.fullmatch('[0-9a-f]{64}', registry_sha256) is not None,
             'INITIALIZATION_REGISTRY_PIN_INVALID')
    _require(type(runtime) is dict
             and set(runtime) == {'host_id', 'source_revision', 'version', 'image_digest'},
             'INITIALIZATION_RUNTIME_INVALID')
    _require(type(runtime['host_id']) is str
             and runtime['host_id'] != 'UNKNOWN'
             and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}', runtime['host_id']) is not None
             and type(runtime['version']) is str and runtime['version'] != 'UNKNOWN'
             and 0 < len(runtime['version']) <= 100
             and runtime['source_revision'] == source_revision
             and runtime['image_digest'] == runtime_image_id,
             'INITIALIZATION_RUNTIME_UNBOUND')
    # Canonical round trip prevents later caller mutation of the report.
    return _parse(canonical(runtime), MAX_BYTES)


def is_initialization(objective, context):
    """Exact dedicated route, not a substring/alias of runtime identity."""
    return type(objective) is str and objective == OBJECTIVE and type(context) is str and context == ''


def _owned_domains(registry_sha256):
    """Read current domain-owned source internally, never caller projections."""
    from . import agent_registry
    # Lazy import allows the dispatcher to call this module after its request
    # class exists; neither import nor inspection executes a model or request.
    from .agent_dispatch_api import AgentRequest
    try:
        path = agent_registry.REGISTRY_PATH
        _require(path.is_file() and not path.is_symlink()
                 and path.stat().st_size <= MAX_REGISTRY_BYTES,
                 'INITIALIZATION_REGISTRY_UNAVAILABLE')
        with path.open('rb') as stream:
            raw = stream.read(MAX_REGISTRY_BYTES + 1)
        _require(sha(raw) == registry_sha256, 'INITIALIZATION_REGISTRY_MISMATCH')
        source = _parse(raw, MAX_REGISTRY_BYTES)
        loaded = agent_registry.load_agent_registry()
        _require(source.get('schema_version') == '2.0'
                 and source.get('registry_version') == loaded.get('registry_version')
                 and type(source.get('agents')) is list and len(source['agents']) == 21,
                 'INITIALIZATION_REGISTRY_INVALID')
        # The Registry loader caches its complete validated domain. Reconcile
        # the entire current strict source, not just A19: an unchanged A19 must
        # never borrow validity from a cached Registry while another agent or
        # lead has been corrupted. These are the loader's only transformations.
        normalized = _parse(canonical(source), MAX_REGISTRY_BYTES)
        leads = normalized.get('leads')
        _require(type(leads) is list and len(leads) == 6
                 and all(type(item) is dict for item in leads),
                 'INITIALIZATION_REGISTRY_INVALID')
        aliases = {item['id']: item['agent_id'] for item in leads}
        domains = {item['agent_id']: item['domain'] for item in leads}
        for item in normalized['agents']:
            _require(type(item) is dict, 'INITIALIZATION_REGISTRY_INVALID')
            item['id'] = item['agent_id']
            item['reports_to'] = aliases.get(item['reports_to'], item['reports_to'])
            item['division'] = domains.get(item['id'], domains.get(item['reports_to'], '')).title()
        _require(canonical(normalized) == canonical(loaded),
                 'INITIALIZATION_LOADED_REGISTRY_MISMATCH')
        records = [item for item in source['agents']
                   if type(item) is dict and item.get('agent_id') == 'a19']
        _require(len(records) == 1, 'INITIALIZATION_AGENT_INVALID')
        record = records[0]
        actual = agent_registry.agent_record('a19')
        _require(all(key in record and key in actual for key in _DEFINITION_FIELDS),
                 'INITIALIZATION_DEFINITION_INVALID')
        definition = {key: record[key] for key in _DEFINITION_FIELDS}
        # The loader canonically resolves public lead aliases. Only that exact
        # documented transformation is permitted; stale/mutated cache is denied.
        leads = source.get('leads')
        _require(type(leads) is list and len(leads) == 6,
                 'INITIALIZATION_REGISTRY_INVALID')
        aliases = {item['id']: item['agent_id'] for item in leads}
        definition['reports_to'] = aliases.get(record['reports_to'], record['reports_to'])
        _require(canonical(definition) == canonical({key: actual[key] for key in _DEFINITION_FIELDS}),
                 'INITIALIZATION_LOADED_DEFINITION_MISMATCH')
        _require(record['immutable_id'] == 'a19' and record['authority'] == 'advisory'
                 and type(record['can_delegate']) is bool and record['can_delegate'] is False
                 and record['capability_requirements'] == ['responsibility.a19']
                 and agent_registry.responsibility_owner('responsibility.a19') == 'a19'
                 and record['tap_relationship'].get('delegation_transfers_authority') is False
                 and record['tap_relationship'].get('execution_authority') == 'none inherited from Registry',
                 'INITIALIZATION_AUTHORITY_INVALID')
        request_schema = AgentRequest.model_json_schema()
        _require(type(request_schema) is dict and request_schema.get('type') == 'object',
                 'INITIALIZATION_REQUEST_SCHEMA_INVALID')
        properties = request_schema['properties']
        _require(type(properties) is dict, 'INITIALIZATION_REQUEST_SCHEMA_INVALID')
        bounds = {}
        for key in ('capability', 'objective', 'context'):
            prop = properties[key]
            _require(type(prop) is dict and prop.get('type') == 'string'
                     and type(prop.get('maxLength')) is int and 0 < prop['maxLength'] <= 100000
                     and (key == 'context' or type(prop.get('minLength')) is int
                          and 0 < prop['minLength'] <= prop['maxLength']),
                     'INITIALIZATION_REQUEST_SCHEMA_INVALID')
            bounds[key] = {name: prop[name] for name in ('minLength', 'maxLength') if name in prop}
        _require(type(properties['data_classification']['enum']) is list
                 and properties['data_classification']['enum'] ==
                 ['LOCAL_ONLY', 'CLOUD_PERMITTED', 'SENSITIVE', 'RESTRICTED'],
                 'INITIALIZATION_REQUEST_SCHEMA_INVALID')
        owned = {'registry': {'source': 'config/agent_registry.json',
                             'source_sha256': registry_sha256,
                             'schema_version': source['schema_version'],
                             'registry_version': source['registry_version'], 'agent_count': 21},
                 'definition': definition,
                 'definition_sha256': sha(canonical(definition)),
                 'request_contract': {'source': 'app.agent_dispatch_api.AgentRequest',
                                      'schema': request_schema,
                                      'schema_sha256': sha(canonical(request_schema)),
                                      'input_bounds': bounds}}
        _require(len(canonical(owned)) <= MAX_BYTES // 2, 'INITIALIZATION_DOMAINS_TOO_LARGE')
        return _parse(canonical(owned), MAX_BYTES)
    except InitializationError:
        raise
    except Exception:
        raise InitializationError('INITIALIZATION_OWNED_DOMAINS_UNAVAILABLE') from None


def build_initialization_report(task_id, *, runtime, source_revision, runtime_image_id,
                                registry_sha256, now=None):
    """Inspect real owned contracts, bound to a protected dispatch's runtime."""
    bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
    captured = _instant(datetime.now(timezone.utc) if now is None else now)
    owned = _owned_domains(registry_sha256)
    return {'schema_version': SCHEMA, 'case': CASE, 'oracle_id': ORACLE_ID,
            'task_id': task_id, 'agent_id': 'a19', 'capability_id': 'responsibility.a19',
            'captured_at': captured.isoformat(), 'runtime': bound, 'owned_domains': owned,
            'observation': 'ROLE_AUTHORITY_AND_INPUT_BOUNDS_READ',
            'evidence_gaps': {'service_map': 'NOT_SUPPLIED', 'health': 'NOT_MEASURED',
                              'runtime_activation': 'NOT_ESTABLISHED_BY_DEFINITION',
                              'role_completion': 'NOT_ESTABLISHED',
                              'event_verification': 'OBJECTIVE_ARTIFACT_ACTION_JOIN_REQUIRED',
                              'independent_review': 'NOT_PERFORMED',
                              'signed_attestation': 'NOT_PRESENT', 'l7': 'UNVERIFIED'},
            'execution': {'method': 'DETERMINISTIC_READ_ONLY', 'model_calls': 0,
                          'input_tokens': 0, 'output_tokens': 0,
                          'fresh_inference_performed': False},
            'certification': 'UNVERIFIED'}


def validate_initialization_report(raw, *, task_id, runtime, source_revision,
                                   runtime_image_id, registry_sha256, now=None):
    """Rebuild from current domains; never accept a caller's PASS or definition.

    The bounded timestamp and task binding are report checks only. The protected
    event reviewer still must join original Objective/artifact/action bytes and
    independently verify the actual execution window and current runtime.
    """
    report = _parse(raw, MAX_BYTES)
    _require(type(report.get('captured_at')) is str, 'INITIALIZATION_TIME_INVALID')
    try:
        captured = _instant(datetime.fromisoformat(report['captured_at']))
    except (ValueError, TypeError):
        raise InitializationError('INITIALIZATION_TIME_INVALID') from None
    current = _instant(datetime.now(timezone.utc) if now is None else now)
    _require(0 <= (current - captured).total_seconds() <= MAX_AGE_SECONDS,
             'INITIALIZATION_TIME_UNBOUND')
    expected = build_initialization_report(task_id, runtime=runtime,
        source_revision=source_revision, runtime_image_id=runtime_image_id,
        registry_sha256=registry_sha256, now=captured)
    _require(canonical(report) == canonical(expected), 'INITIALIZATION_REPORT_MISMATCH')
    original = raw.encode('utf-8') if type(raw) is str else raw
    return {'task_id': task_id, 'case': CASE, 'result_sha256': sha(original),
            'canonical_report_sha256': sha(canonical(report)),
            'source_revision': source_revision, 'runtime_image_id': runtime_image_id,
            'registry_sha256': registry_sha256, 'captured_at': report['captured_at'],
            'definition_sha256': report['owned_domains']['definition_sha256'],
            'request_schema_sha256': report['owned_domains']['request_contract']['schema_sha256'],
            'event_verification': 'OBJECTIVE_ARTIFACT_ACTION_JOIN_REQUIRED',
            'certification': 'UNVERIFIED'}
