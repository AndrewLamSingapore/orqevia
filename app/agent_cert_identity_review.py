"""One original A19 identity event, not model reasoning, health or L7.

The runtime reviewer must join these bytes to its owned Objective, artifact and
persisted action span. Protected signing must separately pin both evidence
files and the reviewed code. No submitted digest or PASS supplies authority.
This module performs no dispatch, signing, credential loading or state writes.
"""
from datetime import datetime
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

CASE = 'baseline:identity'
ORACLE_ID = 'a19.runtime-identity.v1'
SCHEMA = 'prime.agent-cert-identity-review.v1'
MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _TrustedEventAdapter:
    """Internal fixed adapters, never a caller-supplied oracle/action mapping."""
    case: str
    action_type: str
    report_schema: str


_IDENTITY_ADAPTER = _TrustedEventAdapter(CASE, 'runtime.status.artifact', 'jarvis.runtime-status.v1')
_INITIALIZATION_ADAPTER = _TrustedEventAdapter('baseline:initialization',
    'agent.certification.initialization.artifact', 'jarvis.agent-initialization.v1')
_OWNED_IDENTITY_ADAPTER = _TrustedEventAdapter(CASE,
    'agent.certification.owned_identity.artifact', 'jarvis.owned-agent-identity.v1')


class IdentityReviewError(ValueError):
    """Fixed public errors only; never disclose retained content or paths."""


def require(value, code):
    if value is not True:
        raise IdentityReviewError(code) from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_FIELD')
        result[key] = value
    return result


def _finite(text):
    value = float(text)
    require(math.isfinite(value), 'NONFINITE_NUMBER')
    return value


def parse(raw):
    try:
        require(type(raw) is bytes and 1 <= len(raw) <= MAX_BYTES, 'EVENT_SIZE_INVALID')
        value = json.loads(raw, object_pairs_hook=_unique, parse_float=_finite,
            parse_constant=lambda _: require(False, 'NONFINITE_NUMBER'))
        require(type(value) is dict, 'EVENT_OBJECT_REQUIRED')
        return value
    except IdentityReviewError:
        raise
    except Exception:
        raise IdentityReviewError('EVENT_JSON_INVALID') from None


def utc(value):
    try:
        require(type(value) is str and 1 <= len(value) <= 40, 'EVENT_TIME_INVALID')
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(stamp.tzinfo is not None and stamp.utcoffset() is not None,
                'EVENT_TIME_INVALID')
        return stamp
    except IdentityReviewError:
        raise
    except Exception:
        raise IdentityReviewError('EVENT_TIME_INVALID') from None


def valid_uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def action_span(lines, *, task_id, agent_id, action_type, schema, metadata,
                began, ended, action_id=None, duration_limit_ms=5000):
    """Verify original hash-chained lines, including intervening other actions."""
    require(type(lines) is list and 2 <= len(lines) <= 128, 'ACTION_SPAN_REQUIRED')
    events = []
    for line in lines:
        require(type(line) is str and 1 <= len(line.encode('utf-8')) <= 65536,
                'ACTION_SPAN_INVALID')
        event = parse(line.encode('utf-8'))
        require(type(event.get('sequence')) is int and 1 <= event['sequence'] < 2 ** 63
                and type(event.get('sha256')) is str
                and re.fullmatch('[0-9a-f]{64}', event['sha256']) is not None
                and type(event.get('previous_sha256')) is str
                and re.fullmatch('[0-9a-f]{64}', event['previous_sha256']) is not None
                and sha(canonical({k: v for k, v in event.items() if k != 'sha256'})) == event['sha256'],
                'ACTION_SPAN_INVALID')
        if events:
            require(event['sequence'] == events[-1]['sequence'] + 1 and
                    event['previous_sha256'] == events[-1]['sha256'], 'ACTION_SPAN_INVALID')
        events.append(event)
    owned = [e for e in events if e.get('task_id') == task_id and e.get('action_type') == action_type]
    require(len(owned) == 2 and owned[0] is events[0] and owned[-1] is events[-1],
            'ACTION_PAIR_REQUIRED')
    first, last = owned
    aid = first.get('action_id')
    require(valid_uuid(aid) and (action_id is None or aid == action_id) and
            [e for e in events if e.get('action_id') == aid] == owned, 'ACTION_BINDING_INVALID')
    base = dict(task_id=task_id, agent_id=agent_id, action_type=action_type,
        tool='artifact-factory', target='', classification='R0',
        parameters_summary={'schema_version': schema, 'read_only_observations': True},
        model_backend='deterministic', execution_location='local', parent_agent=None,
        workflow_id=None, action_id=aid)
    common = set(base) | {'phase', 'timestamp', 'sequence', 'previous_sha256', 'sha256'}
    require(set(first) == common and set(last) == common | {'success', 'duration_ms', 'result_summary'}
            and all(canonical(e.get(k)) == canonical(v) for e in owned for k, v in base.items())
            and first['phase'] == 'started' and last['phase'] == 'completed'
            and last['success'] is True and type(last['duration_ms']) in (int, float)
            and math.isfinite(last['duration_ms']) and 0 <= last['duration_ms'] <= duration_limit_ms
            and canonical(last['result_summary']) == canonical({'type': 'dict',
                'artifact_id': metadata['artifact_id'], 'sha256': metadata['sha256'],
                'location': 'artifact.json'})
            and began <= utc(first['timestamp']) <= utc(metadata['timestamp']) <= utc(last['timestamp']) <= ended,
            'ACTION_BINDING_INVALID')
    return dict(action_id=aid, first_sequence=first['sequence'], last_sequence=last['sequence'],
        first_sha256=first['sha256'], last_sha256=last['sha256'], record_count=len(lines))


def read_action_span(path, task_id, action_type, max_bytes=8 * 1024 * 1024):
    """Bounded read of the existing ledger; no flush, rewrite or alternate path."""
    try:
        require(valid_uuid(task_id) and action_type in {'runtime.status.artifact',
            'agent.certification.identity.review', 'agent.certification.initialization.artifact',
            'agent.certification.initialization.review', 'agent.certification.owned_identity.artifact',
            'agent.certification.owned_identity.review'} and type(max_bytes) is int and
            1 <= max_bytes <= 8 * 1024 * 1024, 'ACTION_READER_BINDING_INVALID')
        path = Path(path)
        require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
                'ACTION_READER_PATH_INVALID')
        with path.open('rb') as stream:
            raw = stream.read(max_bytes + 1)
        require(0 < len(raw) <= max_bytes and raw.endswith(b'\n'), 'ACTION_READER_BOUND_EXCEEDED')
        lines = raw.decode('utf-8').splitlines(keepends=True)
        owned = []
        for index, line in enumerate(lines):
            require(len(line.encode('utf-8')) <= 65536, 'ACTION_READER_BOUND_EXCEEDED')
            event = parse(line.encode('utf-8'))
            if event.get('task_id') == task_id and event.get('action_type') == action_type:
                owned.append(index)
        require(len(owned) == 2 and 2 <= owned[-1] - owned[0] + 1 <= 128, 'ACTION_PAIR_REQUIRED')
        return lines[owned[0]:owned[-1] + 1]
    except IdentityReviewError:
        raise
    except Exception:
        raise IdentityReviewError('ACTION_READER_UNAVAILABLE') from None


def validate_identity_execution(execution, *, source_revision, runtime_image_id,
                                registry_sha256, now):
    """Recompute the exact existing identity oracle from original event evidence."""
    return _validate_event_execution(execution, source_revision=source_revision,
        runtime_image_id=runtime_image_id, registry_sha256=registry_sha256, now=now,
        _adapter=_IDENTITY_ADAPTER)


def _validate_event_execution(execution, *, source_revision, runtime_image_id,
                              registry_sha256, now, _adapter, agent_id='a19',
                              capability_id='responsibility.a19'):
    """Reuse joins only for the explicit fixed source-owned event adapters."""
    try:
        require(any(_adapter is item for item in (_IDENTITY_ADAPTER, _INITIALIZATION_ADAPTER, _OWNED_IDENTITY_ADAPTER)),
                'TRUSTED_EVENT_ADAPTER_REQUIRED')
        # Legacy identity retains its A19-only contract. Only explicit owned
        # initialization/identity adapters inspect another registered pair;
        # schema/action/oracle selection remains fixed in source.
        if _adapter is _INITIALIZATION_ADAPTER:
            from .agent_cert_initialization import initialization_objective
            initialization_objective(agent_id, capability_id)
        elif _adapter is _OWNED_IDENTITY_ADAPTER:
            from .agent_cert_owned_identity import owned_pair
            owned_pair(agent_id, capability_id)
        else:
            require((agent_id, capability_id) == ('a19', 'responsibility.a19'),
                    'TRUSTED_EVENT_ADAPTER_REQUIRED')
        require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision) is not None
                and type(runtime_image_id) is str and re.fullmatch('sha256:[0-9a-f]{64}', runtime_image_id) is not None
                and type(registry_sha256) is str and re.fullmatch('[0-9a-f]{64}', registry_sha256) is not None
                and type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
                'PROTECTED_EVENT_BINDINGS_REQUIRED')
        value = parse(canonical(execution))
        require(set(value) == {'case_spec', 'runtime', 'submission', 'dispatch', 'artifact_metadata',
            'artifact_content_utf8', 'observation', 'objective_read', 'action_records', 'action_chain_join'},
            'IDENTITY_FIELDS_INVALID')
        from .agent_cert_cases import challenge
        from .agent_cert_execution import observe_cert_case
        spec = challenge(_adapter.case, agent_id=agent_id, capability_id=capability_id)
        require(canonical(value['case_spec']) == canonical(spec), 'CANONICAL_IDENTITY_CASE_REQUIRED')
        runtime = value['runtime']
        require(type(runtime) is dict and set(runtime) == {'host_id', 'version', 'source_revision', 'image_digest'}
                and runtime['source_revision'] == source_revision and runtime['image_digest'] == runtime_image_id,
                'IDENTITY_RUNTIME_INVALID')
        metadata, dispatch, observation = value['artifact_metadata'], value['dispatch'], value['observation']
        require(type(metadata) is dict and len(canonical(metadata)) <= 16384 and type(dispatch) is dict
                and type(observation) is dict and type(value['artifact_content_utf8']) is str,
                'IDENTITY_ARTIFACT_REQUIRED')
        task = dispatch.get('task_id')
        require(valid_uuid(task), 'CANONICAL_IDENTITY_TASK_REQUIRED')
        raw = value['artifact_content_utf8'].encode('utf-8')
        report = parse(raw)  # Reject duplicates, nonfinite and literal type laundering.
        require(all(type(report.get('execution', {}).get(key)) is int for key in
                    ('model_calls', 'input_tokens', 'output_tokens')), 'ZERO_MODEL_EVENT_REQUIRED')
        began, ended = utc(observation.get('started_at')), utc(observation.get('completed_at'))
        require(0 <= (ended - began).total_seconds() <= 5 and ended <= now, 'IDENTITY_EVENT_TIME_INVALID')
        clock = iter((began, ended))
        observed = observe_cert_case(spec, dispatch=lambda _: dispatch,
            get_job=lambda _: require(False, 'NO_IDENTITY_QUEUE_ALLOWED'),
            get_artifact=lambda _: (metadata, raw), get_runtime=lambda: runtime,
            expected_source_revision=source_revision, expected_registry_sha256=registry_sha256,
            wall_clock=lambda: next(clock), monotonic=lambda: 0, timeout_seconds=5)
        require(observed.get('state') == 'EXECUTED' and canonical(observed) == canonical(observation),
                'IDENTITY_ORACLE_FAILED')
        require(set(metadata) == {'artifact_id', 'task_id', 'type', 'creator_agents', 'timestamp',
            'version', 'provenance', 'runtime_revision', 'validation_state', 'content_validation',
            'location', 'sha256', 'bytes', 'delivery_state'} and metadata['version'] == '1.0.0'
            and metadata['provenance'] == 'Deterministic computation; zero model calls'
            and metadata['content_validation'] == 'Not independently established by structural validation',
            'IDENTITY_ARTIFACT_CONTRACT_INVALID')
        submission, read = value['submission'], value['objective_read']
        require(type(submission) is list and len(submission) == 2 and type(submission[0]) is int
                and submission[0] == 202 and type(submission[1]) is dict
                and submission[1].get('id') == task and type(submission[1].get('steps')) is list
                and len(submission[1]['steps']) == 1
                and type(submission[1]['steps'][0]) is dict
                and submission[1]['steps'][0].get('capability') == capability_id
                and canonical(submission[1]['steps'][0].get('dispatch')) == canonical(dispatch),
                'IDENTITY_SUBMISSION_JOIN_INVALID')
        require(type(read) is list and len(read) == 2 and type(read[0]) is int and read[0] == 200
                and type(read[1]) is dict, 'IDENTITY_OBJECTIVE_READ_REQUIRED')
        objective = read[1]
        immutable, steps = objective.get('execution_metadata'), objective.get('steps')
        require(objective.get('id') == task and type(objective.get('revision')) is int
                and objective['revision'] == 0 and objective.get('state') == 'COMPLETED'
                and type(steps) is list and len(steps) == 1 and type(steps[0]) is dict
                and steps[0].get('capability') == capability_id
                and type(steps[0].get('revision')) is int and steps[0]['revision'] == 0
                and steps[0].get('state') == 'completed' and 'job' not in steps[0]
                and canonical(steps[0].get('dispatch')) == canonical(dispatch), 'IDENTITY_OBJECTIVE_JOIN_INVALID')
        require(type(immutable) is dict and immutable.get('schema_version') == 'jarvis.authoritative-execution.v1'
                and immutable.get('authoritative') is True and immutable.get('task_id') == task
                and type(immutable.get('revision')) is int and immutable['revision'] == 0
                and immutable.get('state') == 'COMPLETED' and canonical(immutable.get('runtime')) == canonical(runtime)
                and canonical(immutable.get('jobs')) == b'[]' and canonical(immutable.get('agent_execution')) == b'[]'
                and immutable.get('model_content_is_authoritative_metadata') is False
                and immutable.get('provenance', {}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME',
                'IDENTITY_IMMUTABLE_RUNTIME_REQUIRED')
        if _adapter is _INITIALIZATION_ADAPTER or _adapter is _OWNED_IDENTITY_ADAPTER:
            from .objective_api import inference_attempt_projection
            require(canonical(immutable.get('inference_attempts')) ==
                    canonical(inference_attempt_projection([])),
                    'ZERO_MODEL_EVENT_REQUIRED')
            if _adapter is _OWNED_IDENTITY_ADAPTER:
                from .agent_cert_owned_identity import validate_identity_report as validate_report
            else:
                from .agent_cert_initialization import validate_initialization_report as validate_report
            validate_report(raw, task_id=task, runtime=runtime,
                source_revision=source_revision, runtime_image_id=runtime_image_id,
                registry_sha256=registry_sha256, now=now, agent_id=agent_id, capability_id=capability_id)
        chain = action_span(value['action_records'], task_id=task, agent_id=agent_id,
            action_type=_adapter.action_type, schema=_adapter.report_schema, metadata=metadata,
            # Owned identity is captured inside the already-started artifact
            # action. Its dispatch observation bounds that whole action.
            began=began if _adapter is _OWNED_IDENTITY_ADAPTER else utc(observation['captured_at']),
            ended=ended)
        require(canonical(chain) == canonical(value['action_chain_join'])
                and began <= utc(immutable.get('created_at')) <= utc(observation['captured_at'])
                and utc(parse(value['action_records'][-1].encode())['timestamp']) <=
                    utc(immutable.get('completed_at')) <= utc(immutable.get('updated_at')) <= ended,
                'IDENTITY_ACTION_TIME_JOIN_INVALID')
        return dict(task_id=task, artifact_id=metadata['artifact_id'], result_sha256=sha(raw),
            case_spec_sha256=sha(canonical(spec)), runtime=runtime, registry_sha256=registry_sha256,
            subject_action_sha256=chain['last_sha256'], execution_metadata_sha256=sha(canonical(immutable)),
            completed_at=ended.isoformat())
    except IdentityReviewError:
        raise
    except Exception:
        raise IdentityReviewError('IDENTITY_EVENT_REJECTED') from None
