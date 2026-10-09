"""Fixed A19 artifact exercises and original Objective/artifact/action joins.

Importing this module performs no I/O. The producer is explicit, bounded and
NEVER authenticates its caller: an owning authenticated dispatcher must supply
its actual data mount, existing ledger and independently observed runtime pins.
The existing owning dispatch/collection/review/signing paths supply its inputs;
this module does not authenticate them. Generic
answer text, a returned digest or this validator cannot establish origin,
independent acceptance, health, certification or L7.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import uuid


AGENT_ID = 'a19'
CAPABILITY_ID = 'responsibility.a19'
SUPPORTED_CASES = ('general:artifact_consume', 'general:artifact_produce', 'general:review', 'general:handoff')
CASE_VERSION = 'a19.artifact-events.v1'
ORACLE_ID = 'a19.original-artifact-events.v1'
INPUT_SCHEMA = 'prime.a19-artifact-input.v1'
RESULT_SCHEMA = 'prime.a19-artifact-result.v1'
EVENT_SCHEMA = 'prime.a19-artifact-event.v1'
OPERATION = 'certification_artifact_event'
MAX_BYTES = 65536
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_AGE_SECONDS = 300
PROVENANCE = 'Source-owned public synthetic artifact exercise; zero model calls'
_slot = threading.BoundedSemaphore(1)
_TASKS = {
    SUPPORTED_CASES[0]: 'Read the source-owned synthetic health JSON artifact from the immutable artifact store and interpret its limits.',
    SUPPORTED_CASES[1]: 'Create and read back a compact structured resilience assessment artifact from the source-owned synthetic observations.',
    SUPPORTED_CASES[2]: 'Read the source-owned proposed recovery-plan artifact and reject unsupported assumptions against its included evidence.',
    SUPPORTED_CASES[3]: 'Create a bounded v1.1 advisory handoff packet from the original source-owned evidence artifact for separate Owner-authorized A26 review; do not delegate or transfer authority.',
}
_FACTS = {
    SUPPORTED_CASES[0]: {'source_id': 'AC1', 'checks': 20, 'failures': 1,
        'continuous_observation': False, 'cause_evidence': False},
    SUPPORTED_CASES[1]: {'source_id': 'AP1', 'observations': ['FAILED_CHECK', 'HEALTHY_RETRY'],
        'later_observations': [], 'restart_authorized': False},
    SUPPORTED_CASES[2]: {'source_id': 'AR1', 'checks': 20, 'failures': 1,
        'continuous_observation': False, 'restart_authorized': False,
        'proposal': {'success_basis_points': 10000, 'recovery_proven': True, 'restart_now': True}},
    SUPPORTED_CASES[3]: {'source_id': 'AH1', 'observations': ['FAILED_CHECK', 'HEALTHY_RETRY'],
        'later_observations': [], 'cause_evidence': False, 'restart_authorized': False},
}


class ArtifactEventError(ValueError):
    """Fixed public-safe codes, not retained content, paths or exception text."""


def _require(value, code):
    if value is not True:
        raise ArtifactEventError(code) from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ArtifactEventError('ARTIFACT_JSON_INVALID') from None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'ARTIFACT_DUPLICATE_FIELD')
        result[key] = value
    return result


def _finite(text):
    value = float(text)
    _require(math.isfinite(value), 'ARTIFACT_NONFINITE_NUMBER')
    return value


def parse(raw, limit=MAX_BYTES):
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= limit, 'ARTIFACT_SIZE_INVALID')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
            parse_float=_finite, parse_constant=lambda _: _require(False, 'ARTIFACT_NONFINITE_NUMBER'))
        _require(type(value) is dict, 'ARTIFACT_OBJECT_REQUIRED')
        return value
    except ArtifactEventError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ArtifactEventError('ARTIFACT_JSON_INVALID') from None


def _utc(value):
    try:
        _require(type(value) is str and 0 < len(value) <= 40, 'ARTIFACT_TIME_INVALID')
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, 'ARTIFACT_TIME_INVALID')
        return stamp.astimezone(timezone.utc)
    except ArtifactEventError:
        raise
    except (TypeError, ValueError, OverflowError):
        raise ArtifactEventError('ARTIFACT_TIME_INVALID') from None


def _case(case_id):
    _require(type(case_id) is str and case_id in SUPPORTED_CASES, 'ARTIFACT_CASE_UNSUPPORTED')
    return case_id


def _uuid(value):
    try:
        parsed = uuid.UUID(value) if type(value) is str else None
        return parsed is not None and str(parsed) == value and parsed.version == 4
    except ValueError:
        return False


def _input_bytes(case_id):
    case_id = _case(case_id)
    return canonical({'schema_version': INPUT_SCHEMA, 'case_version': CASE_VERSION,
        'case': case_id, 'data_scope': 'PUBLIC_SYNTHETIC_ONLY', 'facts': _FACTS[case_id]})


def expected_artifact_bytes(case_id, *, task_id=None, input_artifact=None):
    """Exact source-owned output bytes; no caller-provided PASS or output oracle."""
    return _result_bytes(_case(case_id), _input_bytes(case_id),
        task_id=task_id, input_artifact=input_artifact)


def _result_bytes(case_id, raw, *, task_id=None, input_artifact=None):
    parsed = parse(raw)
    _require(raw == _input_bytes(case_id), 'ARTIFACT_SOURCE_INPUT_DRIFT')
    facts = parsed['facts']
    if case_id == SUPPORTED_CASES[0]:
        assessment = {'source_id': facts['source_id'], 'failure_basis_points':
            facts['failures'] * 10000 // facts['checks'], 'window_status': 'ONE_WINDOW_HAS_FAILURE',
            'continuous_health_proven': False, 'cause_known': False,
            'proposed_action': 'READ_ONE_ADDITIONAL_WINDOW', 'restart_authorized': False}
    elif case_id == SUPPORTED_CASES[1]:
        assessment = {'source_id': facts['source_id'], 'observations': facts['observations'],
            'latest_observation': facts['observations'][-1], 'continuous_health_proven': False,
            'proposed_action': 'READ_ONE_LATER_TREND_WINDOW', 'restart_authorized': facts['restart_authorized']}
    elif case_id == SUPPORTED_CASES[2]:
        assessment = {'source_id': facts['source_id'], 'observed_success_basis_points':
            (facts['checks'] - facts['failures']) * 10000 // facts['checks'],
            'unsupported_claims': ['success_basis_points', 'recovery_proven', 'restart_now'],
            'proposal_accepted': False, 'restart_authorized': facts['restart_authorized'],
            'proposed_action': 'OBTAIN_ONE_INDEPENDENT_RECOVERY_OBSERVATION'}
    else:
        # Dynamic origin cannot be manufactured from a static answer template.
        # The producer has already retrieved these original Factory bytes;
        # validation and A26's separate owning-domain review rejoin them again.
        _require(_uuid(task_id) and type(input_artifact) is dict
            and type(input_artifact.get('artifact_id')) is str
            and re.fullmatch('[0-9a-f]{32}', input_artifact['artifact_id']) is not None
            and input_artifact.get('task_id') == task_id
            and input_artifact.get('sha256') == sha(raw), 'HANDOFF_ORIGINAL_BINDINGS_REQUIRED')
        assessment = {'schema_version': '1.1', 'task_id': task_id,
            'objective': _TASKS[case_id],
            'facts': ['PUBLIC_SYNTHETIC_SOURCE:' + facts['source_id'],
                'FAILED_CHECK followed by HEALTHY_RETRY; no later trend observation',
                'No cause evidence and no restart authorization'],
            'results': ['CONTINUOUS_HEALTH_NOT_PROVEN', 'CAUSE_UNKNOWN',
                'PROPOSE_READ_ONE_LATER_TREND_WINDOW_ONLY'],
            'evidence_refs': [input_artifact['sha256']],
            'artifact_refs': [input_artifact['artifact_id']],
            'constraints': ['REGISTERED_RECIPIENT:a26/responsibility.a26',
                'ADVISORY_ONLY_NO_DELEGATION_OR_AUTHORITY_TRANSFER',
                'OWNER_AUTHENTICATED_COLLECTOR_DISPATCHES_SEPARATE_REVIEW',
                'PUBLIC_SYNTHETIC_ONLY_ZERO_MODEL_CALLS_NO_RUNTIME_QUALIFICATION'],
            'changed_state': ['ONLY_ORIGINAL_INPUT_AND_HANDOFF_ARTIFACTS_PERSISTED',
                'NO_PROVIDER_SERVICE_OR_PRODUCTION_CONFIGURATION_CHANGED'],
            'open_questions': ['Later trend observation is absent', 'Cause remains unknown'],
            'acceptance_criteria': ['JOIN_ACTUAL_OBJECTIVE_AND_ORIGINAL_INPUT_ID_SHA256',
                'RETRIEVE_ORIGINAL_HANDOFF_AND_DURABLE_ACTIONS_FROM_OWNING_DOMAINS',
                'JOIN_DISTINCT_REGISTERED_A26_ORIGINAL_REVIEW_RECEIPT',
                'DO_NOT_CLAIM_RECOVERY_HEALTH_AUTHORITY_TRANSFER_SIGNATURE_OR_L7']}
        from .handoff import validate_handoff
        try:
            _require(validate_handoff(assessment) == assessment, 'HANDOFF_PACKET_INVALID')
        except ValueError:
            raise ArtifactEventError('HANDOFF_PACKET_INVALID') from None
    return canonical({'schema_version': RESULT_SCHEMA, 'case_version': CASE_VERSION, 'case': case_id,
        'input_sha256': sha(raw), 'assessment': assessment, 'evidence_scope': 'PUBLIC_SYNTHETIC_ONLY',
        'certification': 'UNVERIFIED'})


def canonical_artifact_case(case_id, *, agent_id=AGENT_ID, capability_id=CAPABILITY_ID):
    """Fixed bounded request, not registration, authorization or runtime readiness."""
    _case(case_id)
    _require((agent_id, capability_id) == (AGENT_ID, CAPABILITY_ID), 'ARTIFACT_OWNER_INVALID')
    return {'agent_id': AGENT_ID, 'capability_id': CAPABILITY_ID, 'case': case_id,
        'case_version': CASE_VERSION, 'oracle_id': ORACLE_ID, 'case_input_sha256': sha(_input_bytes(case_id)),
        'request': {'capability': CAPABILITY_ID, 'objective': _TASKS[case_id],
            'context': _input_bytes(case_id).decode('utf-8'), 'classification': 'R0',
            'data_classification': 'LOCAL_ONLY', 'minimum_tier': 'NANO', 'priority': 'low',
            'task_class': 'classification', 'max_cost_usd': 0.0, 'preferred_provider': None,
            'response_format': 'strict_json', 'deterministic_operation': OPERATION},
        'independent_review': ['authenticated_owning_dispatch', 'original_immutable_artifacts',
            'original_objective_action_join', 'independent_verifier', ORACLE_ID],
        'expected_discriminants': ['exact_source_owned_input', 'exact_derived_artifact_bytes',
            'durable_owned_action_events', 'immutable_objective_runtime'],
        'evidence_scope': 'ORIGINAL_PUBLIC_SYNTHETIC_ARTIFACT_EVENTS_ONLY', 'certification': 'UNVERIFIED'}


def artifact_action_type(case_id, *, setup=False):
    _case(case_id)
    _require(type(setup) is bool and (not setup or case_id != SUPPORTED_CASES[1]), 'ARTIFACT_ACTION_INVALID')
    return ('agent.certification.artifact.fixture.' if setup else 'agent.certification.artifact.') + case_id.split(':')[1]


def _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256):
    _require(_uuid(task_id), 'ARTIFACT_TASK_INVALID')
    _require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision) is not None
        and type(runtime_image_id) is str and re.fullmatch('sha256:[0-9a-f]{64}', runtime_image_id) is not None
        and type(registry_sha256) is str and re.fullmatch('[0-9a-f]{64}', registry_sha256) is not None,
        'ARTIFACT_PROTECTED_PINS_REQUIRED')
    value = parse(canonical(runtime))
    _require(set(value) == {'host_id', 'source_revision', 'version', 'image_digest'}
        and value['source_revision'] == source_revision and value['image_digest'] == runtime_image_id
        and all(type(value[key]) is str and value[key] != 'UNKNOWN'
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}', value[key]) is not None
            for key in ('host_id', 'version')), 'ARTIFACT_RUNTIME_UNBOUND')
    return value


def _path(value):
    path = Path(value)
    _require(path.is_absolute(), 'ARTIFACT_DOMAIN_PATH_INVALID')
    for part in (path, *path.parents):
        try:
            attributes = getattr(part.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError:
            attributes = 0
        _require(not attributes & 0x400, 'ARTIFACT_DOMAIN_PATH_INVALID')
        _require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(),
            'ARTIFACT_DOMAIN_PATH_INVALID')
    return path.resolve()


def _registry(registry_sha256):
    # Lazy Registry import is intentionally outside the module import path.
    from . import agent_registry
    path = _path(agent_registry.REGISTRY_PATH)
    _require(path.is_file() and path.stat().st_size <= 1024 * 1024, 'ARTIFACT_REGISTRY_UNAVAILABLE')
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    _require(sha(raw) == registry_sha256, 'ARTIFACT_REGISTRY_PIN_MISMATCH')
    source = parse(raw, 1024 * 1024)
    normalized = parse(canonical(source), 1024 * 1024)
    aliases = {item['id']: item['agent_id'] for item in source['leads']}
    domains = {item['agent_id']: item['domain'] for item in source['leads']}
    for item in normalized['agents']:
        item['id'] = item['agent_id']
        item['reports_to'] = aliases.get(item['reports_to'], item['reports_to'])
        item['division'] = domains.get(item['id'], domains.get(item['reports_to'], '')).title()
    _require(canonical(normalized) == canonical(agent_registry.load_agent_registry()),
        'ARTIFACT_LOADED_REGISTRY_MISMATCH')
    record = agent_registry.agent_record(AGENT_ID)
    _require(agent_registry.responsibility_owner(CAPABILITY_ID) == AGENT_ID
        and record['immutable_id'] == AGENT_ID and record['authority'] == 'advisory'
        and CAPABILITY_ID in record['capability_requirements']
        and 'provided_context.read' in record['tool_eligibility']
        and record['tap_relationship']['delegation_transfers_authority'] is False,
        'ARTIFACT_REGISTERED_OWNER_INVALID')


def _objective_preflight(root, task, spec, runtime, now):
    """Actual existing Objective DB, mode=ro; never manufacture an Objective."""
    path = _path(root / 'objectives.db')
    _require(path.is_file(), 'ARTIFACT_OBJECTIVE_REQUIRED')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
        row = db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?', (task,)).fetchone()
        turns = db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1', (task,)).fetchone()
        times = db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2', (task,)).fetchall()
        pins = db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2', (task,)).fetchall()
    _require(row is not None and row[0] == sha(spec['request']['objective'].encode('utf-8'))
        and row[1] == 'dispatching' and row[2] == json.dumps([CAPABILITY_ID]) and turns is None
        and len(times) == 1 and type(times[0][0]) is int and times[0][0] == 0
        and times[0][1] == times[0][2] and 0 <= (now - _utc(times[0][1])).total_seconds() <= MAX_AGE_SECONDS
        and pins == [(0, runtime['host_id'], runtime['source_revision'], runtime['version'], runtime['image_digest'])],
        'ARTIFACT_OBJECTIVE_OWNER_OR_SPEC_DRIFT')


def _ledger_lines(root):
    path = _path(root / 'action-records.jsonl')
    if not path.exists():
        return []
    with path.open('rb') as stream:
        raw = stream.read(MAX_LEDGER_BYTES + 1)
    _require(len(raw) <= MAX_LEDGER_BYTES and (not raw or raw.endswith(b'\n')), 'ARTIFACT_LEDGER_BOUND_EXCEEDED')
    lines = raw.decode('utf-8').splitlines(keepends=True)
    _require(all(len(line.encode('utf-8')) <= MAX_BYTES for line in lines), 'ARTIFACT_LEDGER_BOUND_EXCEEDED')
    return lines


def read_artifact_action_span(data_root, task_id, case_id, *, setup=False):
    """Original newline-preserving ledger bytes; no flush or arbitrary action selector."""
    try:
        _require(_uuid(task_id), 'ARTIFACT_TASK_INVALID')
        selected = artifact_action_type(case_id, setup=setup)
        lines = _ledger_lines(_path(data_root))
        owned = [index for index, line in enumerate(lines)
            if (event := parse(line.encode('utf-8'))).get('task_id') == task_id
            and event.get('action_type') == selected]
        _require(len(owned) == 2 and 2 <= owned[-1] - owned[0] + 1 <= 128, 'ARTIFACT_ACTION_PAIR_REQUIRED')
        return lines[owned[0]:owned[-1] + 1]
    except ArtifactEventError:
        raise
    except Exception:
        raise ArtifactEventError('ARTIFACT_ACTION_READ_UNAVAILABLE') from None


def _original_lines(lines):
    _require(type(lines) is list and 2 <= len(lines) <= 128
        and all(type(line) is str and line.endswith('\n') and 0 < len(line.encode('utf-8')) <= MAX_BYTES
            for line in lines) and sum(len(line.encode('utf-8')) for line in lines) <= 1024 * 1024,
        'ARTIFACT_ORIGINAL_ACTION_LINES_REQUIRED')


def _metadata(metadata, raw, task, source, *, began, ended):
    expected = {'artifact_id', 'task_id', 'type', 'creator_agents', 'timestamp', 'version', 'provenance',
        'runtime_revision', 'validation_state', 'content_validation', 'location', 'sha256', 'bytes', 'delivery_state'}
    _require(type(metadata) is dict and set(metadata) == expected
        and type(metadata['artifact_id']) is str and re.fullmatch('[0-9a-f]{32}', metadata['artifact_id']) is not None
        and metadata['task_id'] == task and metadata['type'] == 'json' and metadata['creator_agents'] == [AGENT_ID]
        and metadata['version'] == '1.0.0' and metadata['provenance'] == PROVENANCE
        and metadata['runtime_revision'] == source and metadata['validation_state'] == 'STRUCTURE_VALIDATED'
        and metadata['content_validation'] == 'Not independently established by structural validation'
        and metadata['location'] == 'artifact.json' and metadata['sha256'] == sha(raw)
        and type(metadata['bytes']) is int and metadata['bytes'] == len(raw)
        and metadata['delivery_state'] == 'AVAILABLE' and began <= _utc(metadata['timestamp']) <= ended,
        'ARTIFACT_METADATA_UNBOUND')


def execute_artifact_case(spec, task_id, *, submitted_request, data_root, ledger,
        runtime, read_runtime, source_revision, runtime_image_id, registry_sha256):
    """Explicit fixed operation; owning authenticated dispatch integration REQUIRED.

    Only application artifacts and the existing action ledger are written. No
    Objective update, network, model, queue, service operation or implicit retry.
    A failure leaves original artifacts/actions for reconciliation, not replay.
    """
    _require(_slot.acquire(blocking=False), 'ARTIFACT_PRODUCER_BUSY')
    try:
        bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
        supplied = parse(canonical(spec))
        fixed = canonical_artifact_case(supplied.get('case'))
        _require(canonical(supplied) == canonical(fixed)
            and canonical(submitted_request) == canonical(fixed['request']), 'ARTIFACT_SUBMITTED_SPEC_DRIFT')
        _require(callable(read_runtime) and canonical(read_runtime()) == canonical(bound),
            'ARTIFACT_CURRENT_RUNTIME_UNBOUND')
        root = _path(data_root)
        _path(root / 'artifacts')
        from .action_records import ActionLedger, ActionRecord, DirectExecutor
        _require(type(ledger) is ActionLedger and _path(ledger.path) == root / 'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'ARTIFACT_OWNING_LEDGER_REQUIRED')
        _registry(registry_sha256)
        began = datetime.now(timezone.utc)
        _objective_preflight(root, task_id, fixed, bound, began)
        # qsize() omits the writer's currently dequeued event. Require a
        # quiescent original ledger before scanning for prior attempts; never
        # replay while a failed attempt's started/completed records are pending.
        # This check performs no flush or additional state write.
        with ledger.pending.all_tasks_done:
            _require(ledger.pending.unfinished_tasks == 0, 'ARTIFACT_PRIOR_ACTION_PENDING')
        for line in _ledger_lines(root):
            event = parse(line.encode('utf-8'))
            _require(not (event.get('task_id') == task_id
                and str(event.get('action_type', '')).startswith('agent.certification.artifact.')),
                'ARTIFACT_TASK_ALREADY_ATTEMPTED')
        from .artifact_factory import ArtifactFactory
        factory = ArtifactFactory(root / 'artifacts')
        executor = DirectExecutor(ledger)
        case_id = fixed['case']
        def record(setup=False):
            return ActionRecord(task_id, AGENT_ID, artifact_action_type(case_id, setup=setup), 'artifact-factory',
                parameters_summary={'schema_version': INPUT_SCHEMA if setup else RESULT_SCHEMA,
                    'read_only_observations': True})
        def create(raw):
            metadata = factory.create(kind='json', content=raw.decode('utf-8'), task_id=task_id,
                creator=AGENT_ID, provenance=PROVENANCE, runtime_revision=source_revision)
            reread, actual = factory.retrieve(metadata['artifact_id'])
            _require(canonical(reread) == canonical(metadata) and actual == raw, 'ARTIFACT_READBACK_DRIFT')
            _metadata(reread, actual, task_id, source_revision, began=began, ended=datetime.now(timezone.utc))
            return metadata
        input_metadata, input_action = None, None
        if case_id != SUPPORTED_CASES[1]:
            input_action = record(True)
            input_metadata = executor.execute(input_action, lambda: create(_input_bytes(case_id)))
        subject_action = record()
        def operation():
            raw = _input_bytes(case_id)
            if input_metadata is not None:
                read_metadata, raw = factory.retrieve(input_metadata['artifact_id'])
                _require(canonical(read_metadata) == canonical(input_metadata), 'ARTIFACT_INPUT_READBACK_DRIFT')
            return create(_result_bytes(case_id, raw, task_id=task_id, input_artifact=input_metadata))
        result = executor.execute(subject_action, operation)
        _require(ledger.flush(timeout=1) is True, 'ARTIFACT_DURABLE_ACTION_REQUIRED')
        _require(canonical(read_runtime()) == canonical(bound), 'ARTIFACT_RUNTIME_CHANGED')
        ended = datetime.now(timezone.utc)
        _require(0 <= (ended - began).total_seconds() <= 5, 'ARTIFACT_EXECUTION_BOUND_EXCEEDED')
        event = {'schema_version': EVENT_SCHEMA, 'case': case_id, 'case_version': CASE_VERSION,
            'task_id': task_id, 'source_revision': source_revision, 'registry_sha256': registry_sha256,
            'runtime_identity_sha256': sha(canonical(bound)), 'case_spec_sha256': sha(canonical(fixed)),
            'input_sha256': sha(_input_bytes(case_id)), 'input_artifact_metadata': input_metadata,
            'input_action_id': input_action.action_id if input_action else None,
            'subject_action_id': subject_action.action_id, 'started_at': began.isoformat(),
            'completed_at': ended.isoformat(), 'durable_action_delivery': True, 'certification': 'UNVERIFIED'}
        return {'task_id': task_id, 'state': 'COMPLETED', 'artifact': result, 'model_calls': 0,
            'execution_model': 'DETERMINISTIC', 'agent_id': AGENT_ID, 'capability': CAPABILITY_ID,
            'runtime_source_revision': source_revision, 'artifact_event': event}
    except ArtifactEventError:
        raise
    except Exception:
        raise ArtifactEventError('ARTIFACT_EXECUTION_FAILED') from None
    finally:
        _slot.release()


def validate_artifact_execution(execution, *, source_revision, runtime_image_id, registry_sha256, now):
    """Recompute original joined evidence, not authentication or an award.

    Caller must independently read these bytes from the CURRENT owning domains
    and pin reviewed code/source/image. Submitted JSON/hash chains alone are
    forgeable. Owning collection and separate authenticated review/signing must
    independently bind the original records; this validator grants none of them.
    V1 supplies no cross-operation bridging span: setup completion and subject
    start must be adjacent in the original ledger. A gap needs original bridge
    evidence in a later collector contract, never an assumed predecessor.
    """
    try:
        _require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
            'ARTIFACT_TIME_INVALID')
        value = parse(canonical(execution), 1024 * 1024)
        _require(set(value) == {'case_spec', 'runtime', 'runtime_after', 'runtime_current', 'submission', 'dispatch', 'artifact_metadata',
            'artifact_content_utf8', 'input_content_utf8', 'objective_read', 'action_records',
            'action_chain_join', 'input_action_records', 'input_action_chain_join', 'observation'},
            'ARTIFACT_EVENT_FIELDS_INVALID')
        fixed = canonical_artifact_case(value['case_spec'].get('case'))
        _require(canonical(value['case_spec']) == canonical(fixed), 'ARTIFACT_CASE_SPEC_DRIFT')
        dispatch = value['dispatch']
        task = dispatch.get('task_id')
        runtime = _bindings(task, value['runtime'], source_revision, runtime_image_id, registry_sha256)
        _require(canonical(value['runtime_after']) == canonical(runtime)
            and canonical(value['runtime_current']) == canonical(runtime), 'ARTIFACT_RUNTIME_CHANGED')
        _require(set(dispatch) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model',
            'agent_id', 'capability', 'runtime_source_revision', 'artifact_event'}
            and dispatch['state'] == 'COMPLETED' and dispatch['execution_model'] == 'DETERMINISTIC'
            and dispatch['agent_id'] == AGENT_ID and dispatch['capability'] == CAPABILITY_ID
            and dispatch['runtime_source_revision'] == source_revision
            and type(dispatch['model_calls']) is int and dispatch['model_calls'] == 0,
            'ARTIFACT_DISPATCH_UNBOUND')
        event = dispatch['artifact_event']
        began, ended = _utc(event['started_at']), _utc(event['completed_at'])
        _require(0 <= (ended - began).total_seconds() <= 5 and 0 <= (now - ended).total_seconds() <= MAX_AGE_SECONDS,
            'ARTIFACT_EVENT_STALE_OR_UNBOUNDED')
        observation = value['observation']
        _require(type(observation) is dict and set(observation) == {'started_at', 'completed_at'}
            and _utc(observation['started_at']) <= began <= ended <= _utc(observation['completed_at']) <= now
            and 0 <= (_utc(observation['completed_at']) - _utc(observation['started_at'])).total_seconds() <= 5,
            'ARTIFACT_OBSERVATION_UNBOUND')
        case_id = fixed['case']
        expected_event = {'schema_version': EVENT_SCHEMA, 'case': case_id, 'case_version': CASE_VERSION,
            'task_id': task, 'source_revision': source_revision, 'registry_sha256': registry_sha256,
            'runtime_identity_sha256': sha(canonical(runtime)), 'case_spec_sha256': sha(canonical(fixed)),
            'input_sha256': sha(_input_bytes(case_id)), 'input_artifact_metadata': event['input_artifact_metadata'],
            'input_action_id': event['input_action_id'], 'subject_action_id': event['subject_action_id'],
            'started_at': event['started_at'], 'completed_at': event['completed_at'],
            'durable_action_delivery': True, 'certification': 'UNVERIFIED'}
        _require(canonical(event) == canonical(expected_event) and _uuid(event['subject_action_id']),
            'ARTIFACT_EVENT_UNBOUND')
        metadata = value['artifact_metadata']
        _require(type(value['artifact_content_utf8']) is str, 'ARTIFACT_ORIGINAL_BYTES_REQUIRED')
        raw = value['artifact_content_utf8'].encode('utf-8')
        parse(raw)
        _require(raw == expected_artifact_bytes(case_id, task_id=task,
            input_artifact=event['input_artifact_metadata']) and canonical(dispatch['artifact']) == canonical(metadata),
            'ARTIFACT_RESULT_OR_READBACK_DRIFT')
        _metadata(metadata, raw, task, source_revision, began=began, ended=ended)
        from .agent_cert_identity_review import action_span
        _original_lines(value['action_records'])
        chain = action_span(value['action_records'], task_id=task, agent_id=AGENT_ID,
            action_type=artifact_action_type(case_id), schema=RESULT_SCHEMA, metadata=metadata,
            began=began, ended=ended, action_id=event['subject_action_id'])
        _require(canonical(chain) == canonical(value['action_chain_join']), 'ARTIFACT_ACTION_JOIN_DRIFT')
        input_chain = None
        if case_id == SUPPORTED_CASES[1]:
            _require(event['input_artifact_metadata'] is None and event['input_action_id'] is None
                and value['input_content_utf8'] is None and value['input_action_records'] == []
                and value['input_action_chain_join'] is None, 'ARTIFACT_PRODUCE_INPUT_EVENT_INVALID')
        else:
            _require(type(value['input_content_utf8']) is str and _uuid(event['input_action_id'])
                and event['input_action_id'] != event['subject_action_id'], 'ARTIFACT_INPUT_EVENT_REQUIRED')
            input_raw = value['input_content_utf8'].encode('utf-8')
            parse(input_raw)
            _require(input_raw == _input_bytes(case_id), 'ARTIFACT_SOURCE_INPUT_DRIFT')
            input_metadata = event['input_artifact_metadata']
            _metadata(input_metadata, input_raw, task, source_revision, began=began, ended=ended)
            _require(input_metadata['artifact_id'] != metadata['artifact_id'], 'ARTIFACT_DISTINCT_EVENTS_REQUIRED')
            _original_lines(value['input_action_records'])
            input_chain = action_span(value['input_action_records'], task_id=task, agent_id=AGENT_ID,
                action_type=artifact_action_type(case_id, setup=True), schema=INPUT_SCHEMA, metadata=input_metadata,
                began=began, ended=ended, action_id=event['input_action_id'])
            _require(canonical(input_chain) == canonical(value['input_action_chain_join'])
                and input_chain['last_sequence'] < chain['first_sequence']
                and _utc(parse(value['input_action_records'][-1].encode('utf-8'))['timestamp']) <=
                    _utc(parse(value['action_records'][0].encode('utf-8'))['timestamp']), 'ARTIFACT_INPUT_ACTION_JOIN_DRIFT')
            _require(input_chain['last_sequence'] + 1 == chain['first_sequence'],
                'ARTIFACT_ORIGINAL_BRIDGE_REQUIRED')
            _require(parse(value['action_records'][0].encode('utf-8'))['previous_sha256'] == input_chain['last_sha256'],
                'ARTIFACT_CROSS_OPERATION_CHAIN_INVALID')
        submission, read = value['submission'], value['objective_read']
        _require(type(submission) is list and len(submission) == 2 and type(submission[0]) is int and submission[0] == 202
            and type(submission[1]) is dict and submission[1].get('id') == task
            and canonical(submission[1].get('steps')) == canonical([{'capability': CAPABILITY_ID, 'dispatch': dispatch}]),
            'ARTIFACT_OBJECTIVE_SUBMISSION_UNBOUND')
        _require(type(read) is list and len(read) == 2 and type(read[0]) is int and read[0] == 200
            and type(read[1]) is dict, 'ARTIFACT_OBJECTIVE_READ_REQUIRED')
        objective = read[1]
        immutable = objective.get('execution_metadata')
        _require(objective.get('id') == task and type(objective.get('revision')) is int and objective['revision'] == 0
            and objective.get('state') == 'COMPLETED'
            and canonical(objective.get('steps')) == canonical([{'capability': CAPABILITY_ID, 'dispatch': dispatch,
                'revision': 0, 'state': 'completed'}]), 'ARTIFACT_OBJECTIVE_READ_UNBOUND')
        zero = {'schema_version': 'jarvis.inference-attempts.v1', 'source': 'COMPUTE_LEDGER',
            'status': 'NOT_APPLICABLE', 'attempts': [], 'missing_job_ids': [], 'verification': 'UNVERIFIED',
            'timestamp_source': 'QUEUE_JOB_LIFECYCLE', 'attempt_timestamp': 'NOT_RECORDED',
            'digest_scope': 'SANITIZED_PROJECTION_NOT_SIGNATURE'}
        _require(type(immutable) is dict and immutable.get('schema_version') == 'jarvis.authoritative-execution.v1'
            and immutable.get('authoritative') is True and immutable.get('task_id') == task
            and type(immutable.get('revision')) is int and immutable['revision'] == 0
            and immutable.get('state') == 'COMPLETED' and canonical(immutable.get('runtime')) == canonical(runtime)
            and canonical(immutable.get('jobs')) == b'[]' and canonical(immutable.get('agent_execution')) == b'[]'
            and canonical(immutable.get('inference_attempts')) == canonical(zero)
            and immutable.get('model_content_is_authoritative_metadata') is False
            and immutable.get('provenance', {}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME'
            and _utc(observation['started_at']) <= _utc(immutable.get('created_at')) <= began
            and _utc(parse(value['action_records'][-1].encode('utf-8'))['timestamp']) <=
                _utc(immutable.get('completed_at')) <= _utc(immutable.get('updated_at')) <= _utc(observation['completed_at']),
            'ARTIFACT_IMMUTABLE_OBJECTIVE_UNBOUND')
        return {'task_id': task, 'case': case_id, 'artifact_id': metadata['artifact_id'], 'result_sha256': sha(raw),
            'case_spec_sha256': sha(canonical(fixed)), 'runtime': runtime, 'registry_sha256': registry_sha256,
            'subject_action_sha256': chain['last_sha256'], 'input_action_sha256': input_chain['last_sha256'] if input_chain else None,
            'execution_metadata_sha256': sha(canonical(immutable)), 'certification': 'UNVERIFIED',
            'event_verification': 'JOIN_VALIDATED_ORIGIN_AND_INDEPENDENT_ACCEPTANCE_REQUIRED'}
    except ArtifactEventError:
        raise
    except Exception:
        raise ArtifactEventError('ARTIFACT_EVENT_REJECTED') from None
