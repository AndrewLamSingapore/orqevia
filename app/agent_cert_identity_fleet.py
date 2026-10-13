"""Registered-owned zero-model identity events; never worker health or L7.

The frozen A19 runtime identity route remains separate. Every other owned
capability needs its own original Objective, artifact and durable action span,
then a different registered reviewer joins those original owning domains.
"""
from datetime import datetime, timezone
import json
import hashlib
import re
from pathlib import Path

from .agent_cert_identity_review import canonical, parse, require, sha, utc, valid_uuid, action_span
from .agent_cert_initialization import (
    _bindings, _owned_pair, _owned_domains, initialization_reviewer,
)

CASE = 'baseline:identity'
VERSION = 'registered.owned-identity.v1'
SCHEMA = 'jarvis.agent-owned-identity.v1'
REVIEW_SCHEMA = 'prime.agent-cert-owned-identity-review.v1'
ACTION_TYPE = 'agent.certification.owned_identity.artifact'
REVIEW_ACTION = 'agent.certification.owned_identity.review'
PREFIX = 'Inspect current registered-owned identity '
MAX_BYTES = 1024 * 1024


def owned_pair(agent_id, capability_id):
    require((agent_id, capability_id) != ('a19', 'responsibility.a19'),
            'LEGACY_A19_IDENTITY_ROUTE_REQUIRED')
    return _owned_pair(agent_id, capability_id)


def identity_objective(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return (PREFIX + f'{agent_id} / {capability_id}; bind the immutable agent ID '
            'and unique responsibility owner to the current Registry and runtime '
            'source/image in a zero-model artifact. Do not claim a live worker, '
            'health, additional authority or certification.')


def identity_reviewer(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return initialization_reviewer(agent_id, capability_id)


def identity_review_objective(agent_id, capability_id):
    identity_reviewer(agent_id, capability_id)
    return (f'Independently review one recorded owned-identity event for {agent_id} / '
            f'{capability_id} against its original Objective, current Registry, '
            'runtime, artifact and durable action records; do not certify or sign.')


def canonical_identity_case(*, agent_id, capability_id):
    return {'agent_id': agent_id, 'capability_id': capability_id, 'case': CASE,
        'request': {'capability': capability_id,
            'objective': identity_objective(agent_id, capability_id), 'context': '',
            'classification': 'R0', 'data_classification': 'LOCAL_ONLY',
            'minimum_tier': 'NANO', 'priority': 'low', 'task_class': 'classification',
            'max_cost_usd': 0, 'response_format': 'strict_json'},
        'independent_review': ('authenticated_owner', 'registered_owned_identity_v1',
            'original_objective_artifact_action_join', 'distinct_registered_reviewer'),
        'expected_discriminants': ('Identity and ownership come from the exact current Registry',
            'Current source/image are bound to the actual immutable Objective',
            'Registration is not worker activation, health or certification'),
        'certification': 'UNVERIFIED'}


def build_identity_report(task_id, *, runtime, source_revision, runtime_image_id,
                          registry_sha256, agent_id, capability_id, now=None):
    owned_pair(agent_id, capability_id)
    runtime = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
    now = now or datetime.now(timezone.utc)
    require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
            'OWNED_IDENTITY_TIME_INVALID')
    # Reuse the strict whole-Registry source/cache reconciliation, without
    # publishing an initialization report or its unrelated input-bound claims.
    domains = _owned_domains(registry_sha256, agent_id, capability_id)
    definition, selected = domains['definition'], domains['selected_capability']
    identity = {'agent_id': agent_id, 'immutable_id': definition['immutable_id'],
        'capability_id': capability_id, 'responsibility_owner': agent_id,
        'authority_scope': definition['authority'], 'reports_to': definition['reports_to'],
        'definition_sha256': domains['definition_sha256'],
        'selected_capability_sha256': sha(canonical(selected)),
        'registry_sha256': registry_sha256}
    return {'schema_version': SCHEMA, 'oracle_id': VERSION, 'task_id': task_id,
        'agent_id': agent_id, 'capability_id': capability_id, 'identity': identity,
        'runtime': runtime, 'captured_at': now.astimezone(timezone.utc).isoformat(),
        'execution': {'method': 'DETERMINISTIC_READ_ONLY', 'model_calls': 0,
                      'input_tokens': 0, 'output_tokens': 0},
        'scope': {'worker_activation': 'NOT_ESTABLISHED', 'health': 'NOT_MEASURED',
                  'authority_added': False, 'certification': 'UNVERIFIED'}}


def validate_identity_report(raw, *, task_id, runtime, source_revision,
                             runtime_image_id, registry_sha256, now, agent_id, capability_id):
    report = parse(raw)
    captured = utc(report.get('captured_at'))
    require(captured <= now, 'OWNED_IDENTITY_FUTURE_REPORT')
    expected = build_identity_report(task_id, runtime=runtime, source_revision=source_revision,
        runtime_image_id=runtime_image_id, registry_sha256=registry_sha256,
        agent_id=agent_id, capability_id=capability_id, now=captured)
    require(canonical(report) == canonical(expected), 'OWNED_IDENTITY_REPORT_UNBOUND')
    return {'captured_at': captured.isoformat(), 'agent_id': agent_id,
            'capability_id': capability_id, 'certification': 'UNVERIFIED'}


def read_action_span(path, task_id, action_type, max_bytes=8 * 1024 * 1024):
    """Read only either new owned event; preserve the original ledger bytes."""
    from .agent_cert_artifact_events import _path
    require(valid_uuid(task_id) and action_type in {ACTION_TYPE, REVIEW_ACTION}
            and type(max_bytes) is int and 1 <= max_bytes <= 8 * 1024 * 1024,
            'OWNED_IDENTITY_ACTION_READER_INVALID')
    path = _path(Path(path))
    with path.open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    require(0 < len(raw) <= max_bytes and raw.endswith(b'\n'), 'OWNED_IDENTITY_LEDGER_BOUND')
    lines, owned = raw.decode('utf-8').splitlines(keepends=True), []
    for index, line in enumerate(lines):
        require(len(line.encode()) <= 65536, 'OWNED_IDENTITY_LEDGER_BOUND')
        event = parse(line.encode())
        if event.get('task_id') == task_id and event.get('action_type') == action_type:
            owned.append(index)
    require(len(owned) == 2 and 2 <= owned[-1] - owned[0] + 1 <= 128,
            'OWNED_IDENTITY_ACTION_PAIR_REQUIRED')
    return lines[owned[0]:owned[-1] + 1]


def observe_identity_artifact(spec, base, *, dispatch, get_artifact, get_runtime,
                                     expected_source_revision, expected_registry_sha256,
                                     started, timeout_seconds, monotonic, wall_clock):
    """Observe one original registered-owned identity artifact without inference."""
    from .agent_cert_execution import _canonical, _runtime_identity, _time
    agent, capability = spec.get('agent_id'), spec.get('capability_id')
    if _canonical(spec) != _canonical(canonical_identity_case(agent_id=agent, capability_id=capability)):
        return {**base, 'state': 'REJECTED', 'reason': 'owned_identity_case_source_mismatch'}
    if (not callable(get_artifact) or not callable(get_runtime)
            or type(expected_source_revision) is not str
            or re.fullmatch('[0-9a-f]{40}', expected_source_revision) is None
            or type(expected_registry_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', expected_registry_sha256) is None):
        return {**base, 'state': 'REJECTED', 'reason': 'owned_identity_evidence_reader_missing'}
    began = wall_clock()
    if type(began) is not datetime or began.tzinfo is None or began.utcoffset() is None:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_missing'}
    before = _runtime_identity(get_runtime(), expected_source_revision)
    if before is None:
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_missing'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    reply = dispatch(spec['request'])
    if (type(reply) is not dict or set(reply) != {'task_id', 'state', 'artifact', 'model_calls',
            'execution_model', 'agent_id', 'capability', 'runtime_source_revision'}
            or reply.get('state') != 'COMPLETED' or reply.get('execution_model') != 'DETERMINISTIC'
            or reply.get('agent_id') != agent or reply.get('capability') != capability
            or reply.get('runtime_source_revision') != expected_source_revision
            or type(reply.get('model_calls')) is not int or reply['model_calls'] != 0):
        return {**base, 'state': 'REJECTED', 'reason': 'deterministic_dispatch_invalid'}
    task, declared = reply.get('task_id'), reply.get('artifact')
    if (type(task) is not str
            or re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', task) is None
            or type(declared) is not dict):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_identity_mismatch'}
    artifact_id = declared.get('artifact_id')
    if type(artifact_id) is not str or re.fullmatch('[0-9a-f]{32}', artifact_id) is None:
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_identity_mismatch'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    retrieved = get_artifact(artifact_id)
    if (type(retrieved) is not tuple or len(retrieved) != 2
            or type(retrieved[0]) is not dict or type(retrieved[1]) is not bytes):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_read_invalid'}
    metadata, raw = retrieved
    if monotonic() - started >= timeout_seconds:
        return {**base, 'task_id': task, 'artifact_id': artifact_id,
                'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    if (not 0 < len(raw) <= MAX_BYTES or len(_canonical(metadata)) > 16384
            or _canonical(metadata) != _canonical(declared)
            or metadata.get('artifact_id') != artifact_id or metadata.get('task_id') != task
            or metadata.get('creator_agents') != [agent] or metadata.get('type') != 'json'
            or metadata.get('runtime_revision') != expected_source_revision
            or metadata.get('validation_state') != 'STRUCTURE_VALIDATED'
            or metadata.get('delivery_state') != 'AVAILABLE' or metadata.get('location') != 'artifact.json'
            or type(metadata.get('bytes')) is not int or metadata['bytes'] != len(raw)
            or metadata.get('sha256') != hashlib.sha256(raw).hexdigest()):
        return {**base, 'state': 'REJECTED', 'reason': 'artifact_binding_mismatch'}
    after = _runtime_identity(get_runtime(), expected_source_revision)
    ended = wall_clock()
    if after is None or _canonical(before) != _canonical(after):
        return {**base, 'state': 'REJECTED', 'reason': 'runtime_identity_changed'}
    if type(ended) is not datetime or ended.tzinfo is None or ended.utcoffset() is None:
        return {**base, 'state': 'REJECTED', 'reason': 'observation_time_invalid'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'task_id': task, 'artifact_id': artifact_id,
                'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    joined = validate_identity_report(raw, task_id=task, runtime=before,
        source_revision=expected_source_revision, runtime_image_id=before['image_digest'],
        registry_sha256=expected_registry_sha256, now=ended, agent_id=agent, capability_id=capability)
    captured, artifact_time = _time(joined['captured_at']), _time(metadata.get('timestamp'))
    if captured is None or artifact_time is None or not began <= captured <= artifact_time <= ended:
        return {**base, 'state': 'REJECTED', 'reason': 'owned_identity_report_time_unbound'}
    if monotonic() - started >= timeout_seconds:
        return {**base, 'state': 'INCOMPLETE', 'reason': 'bounded_timeout'}
    return {**base, 'state': 'EXECUTED', 'execution_model': 'DETERMINISTIC',
            'task_id': task, 'artifact_id': artifact_id, 'model_calls': 0,
            'source_revision': expected_source_revision, 'registry_sha256': expected_registry_sha256,
            'runtime_identity_sha256': hashlib.sha256(_canonical(before)).hexdigest(),
            'result_sha256': metadata['sha256'],
            'artifact_metadata_sha256': hashlib.sha256(_canonical(metadata)).hexdigest(),
            'started_at': began.isoformat(), 'completed_at': ended.isoformat(),
            'captured_at': captured.isoformat(), 'case_review': 'OWNED_IDENTITY_ARTIFACT_CHECK_PASS',
            'review_errors': ()}


def validate_identity_execution(execution, *, source_revision, runtime_image_id,
                                registry_sha256, now, agent_id, capability_id):
    """Bind one new identity event to its actual immutable owning domains."""
    from .agent_cert_execution import observe_cert_case
    from .objective_api import inference_attempt_projection
    from .agent_cert_identity_review import IdentityReviewError
    try:
        owned_pair(agent_id, capability_id)
        require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision) is not None
                and type(runtime_image_id) is str and re.fullmatch('sha256:[0-9a-f]{64}', runtime_image_id) is not None
                and type(registry_sha256) is str and re.fullmatch('[0-9a-f]{64}', registry_sha256) is not None
                and type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
                'PROTECTED_EVENT_BINDINGS_REQUIRED')
        value = parse(canonical(execution))
        require(set(value) == {'case_spec', 'runtime', 'submission', 'dispatch', 'artifact_metadata',
            'artifact_content_utf8', 'observation', 'objective_read', 'action_records', 'action_chain_join'},
            'IDENTITY_FIELDS_INVALID')
        spec = canonical_identity_case(agent_id=agent_id, capability_id=capability_id)
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
        require(canonical(immutable.get('inference_attempts')) ==
                canonical(inference_attempt_projection([])),
                'ZERO_MODEL_EVENT_REQUIRED')
        validate_identity_report(raw, task_id=task, runtime=runtime,
            source_revision=source_revision, runtime_image_id=runtime_image_id,
            registry_sha256=registry_sha256, now=now, agent_id=agent_id, capability_id=capability_id)
        chain = action_span(value['action_records'], task_id=task, agent_id=agent_id,
            action_type=ACTION_TYPE, schema=SCHEMA, metadata=metadata,
            began=utc(observation['captured_at']), ended=ended)
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
        raise IdentityReviewError('OWNED_IDENTITY_EVENT_REJECTED') from None
