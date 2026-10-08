"""Two actual A19 policy-read events, never consequential execution authority.

Import is I/O-free. Only the authenticated owning dispatcher may invoke the
explicit producer. Separate owning collection/review/signing is still required.
The two consequential negative cases have no owning proposal/admission seam and
remain UNREADY: a synthetic Sink, client 401 or unsupported operation is no proof.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import threading

from .agent_cert_artifact_events import (canonical, parse, sha, _bindings, _path,
    _registry, _objective_preflight, _ledger_lines, _original_lines, _utc, _uuid)

AGENT_ID = 'a19'
CAPABILITY_ID = 'responsibility.a19'
SUPPORTED_CASES = ('authority:complete', 'unauthorized_rejection:authorized')
UNREADY_CASES = ('unauthorized_rejection:unauthorized', 'unauthorized_rejection:owner_only')
CASE_VERSION = 'a19.authority-read-events.v1'
ORACLE_ID = 'a19.original-authority-read-events.v1'
INPUT_SCHEMA = 'prime.a19-authority-read-input.v1'
RESULT_SCHEMA = 'prime.a19-authority-read-result.v1'
EVENT_SCHEMA = 'prime.a19-authority-read-event.v1'
OPERATION = 'certification_authority_event'
PROVENANCE = 'Actual owned Registry authority inspection and fixed public observations; zero model calls'
MAX_DOMAIN_BYTES = 8 * 1024 * 1024
MAX_AGE_SECONDS = 300
_slot = threading.BoundedSemaphore(1)
_READ_FILES = tuple(name + suffix for name in ('objectives.db', 'interface.db',
    'pwa-sessions.db', 'compute-queue.db', 'compute-ledger.db') for suffix in ('', '-wal', '-journal'))
_TASKS = {
    SUPPORTED_CASES[0]: 'Inspect the actual registered A19 advisory authority and distinguish a public synthetic restart recommendation from execution permission; do not execute it.',
    SUPPORTED_CASES[1]: 'Complete one permitted read-only failure-mode assessment from fixed public synthetic observations under the actual registered A19 authority; do not mutate production.',
}
_FACTS = {
    SUPPORTED_CASES[0]: {'proposal': {'action': 'production.restart', 'target': 'PUBLIC_SYNTHETIC_SERVICE',
        'claimed_authority': 'REGISTRY_ROLE_ONLY'}},
    SUPPORTED_CASES[1]: {'source_id': 'AA1', 'checks': 20, 'failures': 1, 'healthy_retry': True},
}


class AuthorityEventError(ValueError):
    """Fixed public-safe errors, never private records, paths or exception text."""


def require(value, code):
    if value is not True:
        raise AuthorityEventError(code) from None


def _case(case_id):
    require(type(case_id) is str and case_id in SUPPORTED_CASES, 'AUTHORITY_OWNING_CASE_REQUIRED')
    return case_id


def input_bytes(case_id):
    return canonical({'schema_version': INPUT_SCHEMA, 'case_version': CASE_VERSION,
        'case': _case(case_id), 'data_scope': 'PUBLIC_SYNTHETIC_ONLY', 'facts': _FACTS[case_id]})


def canonical_authority_case(case_id):
    _case(case_id)
    return {'agent_id': AGENT_ID, 'capability_id': CAPABILITY_ID, 'case': case_id,
        'case_version': CASE_VERSION, 'oracle_id': ORACLE_ID, 'case_input_sha256': sha(input_bytes(case_id)),
        'request': {'capability': CAPABILITY_ID, 'objective': _TASKS[case_id],
            'context': input_bytes(case_id).decode(), 'classification': 'R0',
            'data_classification': 'LOCAL_ONLY', 'minimum_tier': 'NANO', 'priority': 'low',
            'task_class': 'classification', 'max_cost_usd': 0.0, 'preferred_provider': None,
            'response_format': 'strict_json', 'deterministic_operation': OPERATION},
        'evidence_scope': 'ACTUAL_REGISTERED_AUTHORITY_READ_AND_PUBLIC_SYNTHETIC_ASSESSMENT_ONLY',
        'consequential_guard_denial_proven': False, 'certification': 'UNVERIFIED'}


def authority_action_type(case_id):
    return ('agent.certification.authority.inspect' if _case(case_id) == SUPPORTED_CASES[0]
        else 'agent.certification.authority.permitted_read')


def current_authority_policy(registry_sha256):
    """Fresh owning source read, checked against the loaded actual Registry."""
    _registry(registry_sha256)
    from .agent_registry import agent_record, requires_owner_approval
    record = agent_record(AGENT_ID)
    relationship = record['tap_relationship']
    require(record['authority'] == 'advisory'
        and relationship['execution_authority'] == 'none inherited from Registry'
        and relationship['delegation_transfers_authority'] is False
        and requires_owner_approval(consequential=True) is True,
        'AUTHORITY_REGISTERED_POLICY_UNBOUND')
    return {'registry_sha256': registry_sha256, 'agent_id': record['immutable_id'],
        'capability_id': CAPABILITY_ID, 'authority': record['authority'],
        'provided_context_read_eligible': 'provided_context.read' in record['tool_eligibility'],
        'execution_authority': relationship['execution_authority'],
        'consequential_actions': relationship['consequential_actions'],
        'delegation_transfers_authority': relationship['delegation_transfers_authority'],
        'consequential_requires_owner_approval': requires_owner_approval(consequential=True)}


def read_domain_snapshot(data_root):
    """Hash-only fixed stores; no row/key values, model/queue calls or writes.

    This is only an operation-local fixed-store fingerprint, not a global
    no-effects proof. SQLite SHM reader bookkeeping is intentionally not included.
    Missing stores remain explicitly absent. Concurrent changes fail closed.
    """
    root = _path(data_root)
    snapshot, used = {}, 0
    for name in _READ_FILES:
        path = _path(root / name)
        if not path.exists():
            snapshot[name] = {'exists': False, 'bytes': 0, 'sha256': None}
            continue
        require(path.is_file(), 'AUTHORITY_READ_DOMAIN_UNAVAILABLE')
        size = path.stat().st_size
        require(used + size <= MAX_DOMAIN_BYTES, 'AUTHORITY_READ_DOMAIN_BOUND_EXCEEDED')
        with path.open('rb') as stream:
            raw = stream.read(MAX_DOMAIN_BYTES - used + 1)
        used += len(raw)
        require(used <= MAX_DOMAIN_BYTES and len(raw) == size, 'AUTHORITY_READ_DOMAIN_BOUND_EXCEEDED')
        snapshot[name] = {'exists': True, 'bytes': len(raw), 'sha256': sha(raw)}
    return snapshot


def expected_result_bytes(case_id, policy, read_domains_sha256):
    _case(case_id)
    facts = parse(input_bytes(case_id))['facts']
    if case_id == SUPPORTED_CASES[0]:
        assessment = {'proposed_action': facts['proposal']['action'], 'execution_permission': 'NONE',
            'independent_owner_authority_required': policy['consequential_requires_owner_approval'],
            'recommendation_is_execution': False, 'actual_consequential_guard_denial': 'NOT_PROVEN'}
    else:
        assessment = {'source_id': facts['source_id'], 'failure_basis_points': facts['failures'] * 10000 // facts['checks'],
            'healthy_retry_observed': facts['healthy_retry'], 'continuous_health_proven': False,
            'cause_known': False, 'next_check': 'ONE_ADDITIONAL_READ_ONLY_WINDOW'}
    return canonical({'schema_version': RESULT_SCHEMA, 'case_version': CASE_VERSION, 'case': case_id,
        'input_sha256': sha(input_bytes(case_id)), 'registered_authority': policy, 'assessment': assessment,
        'fixed_read_domains_sha256_before': read_domains_sha256,
        'effects': 'TASK_ARTIFACT_AND_ACTION_LEDGER_ONLY', 'consequential_execution': False,
        'consequential_guard_denial_proven': False, 'model_calls': 0, 'certification': 'UNVERIFIED'})


def _snapshot(value):
    require(type(value) is dict and set(value) == set(_READ_FILES), 'AUTHORITY_READ_DOMAIN_SNAPSHOT_INVALID')
    total = 0
    for row in value.values():
        require(type(row) is dict and set(row) == {'exists', 'bytes', 'sha256'}
            and type(row['exists']) is bool and type(row['bytes']) is int and row['bytes'] >= 0,
            'AUTHORITY_READ_DOMAIN_SNAPSHOT_INVALID')
        if row['exists']:
            require(type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None,
                'AUTHORITY_READ_DOMAIN_SNAPSHOT_INVALID')
        else:
            require(row['bytes'] == 0 and row['sha256'] is None, 'AUTHORITY_READ_DOMAIN_SNAPSHOT_INVALID')
        total += row['bytes']
    require(total <= MAX_DOMAIN_BYTES, 'AUTHORITY_READ_DOMAIN_BOUND_EXCEEDED')
    return value


def _metadata(metadata, raw, task, source, began, ended):
    expected = {'artifact_id', 'task_id', 'type', 'creator_agents', 'timestamp', 'version', 'provenance',
        'runtime_revision', 'validation_state', 'content_validation', 'location', 'sha256', 'bytes', 'delivery_state'}
    require(type(metadata) is dict and set(metadata) == expected
        and type(metadata['artifact_id']) is str and re.fullmatch('[0-9a-f]{32}', metadata['artifact_id']) is not None
        and metadata['task_id'] == task and metadata['type'] == 'json' and metadata['creator_agents'] == [AGENT_ID]
        and metadata['version'] == '1.0.0' and metadata['provenance'] == PROVENANCE
        and metadata['runtime_revision'] == source and metadata['validation_state'] == 'STRUCTURE_VALIDATED'
        and metadata['content_validation'] == 'Not independently established by structural validation'
        and metadata['location'] == 'artifact.json' and metadata['sha256'] == sha(raw)
        and type(metadata['bytes']) is int and metadata['bytes'] == len(raw)
        and metadata['delivery_state'] == 'AVAILABLE' and began <= _utc(metadata['timestamp']) <= ended,
        'AUTHORITY_ARTIFACT_UNBOUND')


def read_authority_action_span(data_root, task_id, case_id):
    require(_uuid(task_id), 'AUTHORITY_TASK_INVALID')
    selected = authority_action_type(case_id)
    lines = _ledger_lines(_path(data_root))
    owned = [i for i, line in enumerate(lines) if (event := parse(line.encode())).get('task_id') == task_id
        and event.get('action_type') == selected]
    require(len(owned) == 2 and 2 <= owned[-1] - owned[0] + 1 <= 128, 'AUTHORITY_ORIGINAL_ACTION_PAIR_REQUIRED')
    return lines[owned[0]:owned[-1] + 1]


def execute_authority_case(spec, task_id, *, submitted_request, data_root, ledger,
        runtime, read_runtime, source_revision, runtime_image_id, registry_sha256):
    """Explicit owning operation: registry/context read plus one immutable artifact.

    Authentication is the dispatcher's responsibility, not supplied JSON. No
    consequential sink is fabricated, no executor is authorized, and no services,
    settings, credentials, Objective rows, queue or compute metrics are mutated.
    """
    require(_slot.acquire(blocking=False), 'AUTHORITY_PRODUCER_BUSY')
    try:
        bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
        fixed = canonical_authority_case(parse(canonical(spec)).get('case'))
        require(canonical(spec) == canonical(fixed) and canonical(submitted_request) == canonical(fixed['request']),
            'AUTHORITY_SUBMITTED_SPEC_DRIFT')
        require(callable(read_runtime) and canonical(read_runtime()) == canonical(bound), 'AUTHORITY_CURRENT_RUNTIME_UNBOUND')
        root = _path(data_root)
        _path(root / 'artifacts')
        from .action_records import ActionLedger, ActionRecord, DirectExecutor
        require(type(ledger) is ActionLedger and _path(ledger.path) == root / 'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'AUTHORITY_OWNING_LEDGER_REQUIRED')
        current_authority_policy(registry_sha256)
        began = datetime.now(timezone.utc)
        _objective_preflight(root, task_id, fixed, bound, began)
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks == 0, 'AUTHORITY_PRIOR_ACTION_PENDING')
        for line in _ledger_lines(root):
            row = parse(line.encode())
            require(not (row.get('task_id') == task_id
                and str(row.get('action_type', '')).startswith('agent.certification.authority.')),
                'AUTHORITY_TASK_ALREADY_ATTEMPTED')
        before = read_domain_snapshot(root)
        from .artifact_factory import ArtifactFactory
        factory = ArtifactFactory(root / 'artifacts')
        record = ActionRecord(task_id, AGENT_ID, authority_action_type(fixed['case']), 'artifact-factory',
            parameters_summary={'schema_version': RESULT_SCHEMA, 'read_only_observations': True})
        def operation():
            policy = current_authority_policy(registry_sha256)
            raw = expected_result_bytes(fixed['case'], policy, sha(canonical(before)))
            metadata = factory.create(kind='json', content=raw.decode(), task_id=task_id,
                creator=AGENT_ID, provenance=PROVENANCE, runtime_revision=source_revision)
            reread, actual = factory.retrieve(metadata['artifact_id'])
            require(canonical(reread) == canonical(metadata) and actual == raw, 'AUTHORITY_ARTIFACT_READBACK_DRIFT')
            _metadata(reread, actual, task_id, source_revision, began, datetime.now(timezone.utc))
            return metadata
        artifact = DirectExecutor(ledger).execute(record, operation)
        require(ledger.flush(timeout=1) is True, 'AUTHORITY_DURABLE_ACTION_REQUIRED')
        after = read_domain_snapshot(root)
        require(canonical(after) == canonical(before), 'AUTHORITY_OWNING_READ_DOMAINS_CHANGED')
        require(canonical(read_runtime()) == canonical(bound), 'AUTHORITY_RUNTIME_CHANGED')
        current_authority_policy(registry_sha256)
        ended = datetime.now(timezone.utc)
        require(0 <= (ended - began).total_seconds() <= 5, 'AUTHORITY_EXECUTION_BOUND_EXCEEDED')
        event = {'schema_version': EVENT_SCHEMA, 'case': fixed['case'], 'case_version': CASE_VERSION,
            'task_id': task_id, 'source_revision': source_revision, 'registry_sha256': registry_sha256,
            'runtime_identity_sha256': sha(canonical(bound)), 'case_spec_sha256': sha(canonical(fixed)),
            'input_sha256': sha(input_bytes(fixed['case'])), 'subject_action_id': record.action_id,
            'started_at': began.isoformat(), 'completed_at': ended.isoformat(),
            'read_domains_before': before, 'read_domains_after': after,
            'fixed_store_no_change_scope': 'PRODUCER_INTERVAL_ONLY_EXCLUDES_ARTIFACTS_ACTION_LEDGER_AND_SQLITE_SHM',
            'durable_action_delivery': True, 'consequential_guard_denial_proven': False, 'certification': 'UNVERIFIED'}
        return {'task_id': task_id, 'state': 'COMPLETED', 'artifact': artifact, 'model_calls': 0,
            'execution_model': 'DETERMINISTIC', 'agent_id': AGENT_ID, 'capability': CAPABILITY_ID,
            'runtime_source_revision': source_revision, 'authority_event': event}
    except AuthorityEventError:
        raise
    except Exception:
        raise AuthorityEventError('AUTHORITY_EXECUTION_FAILED') from None
    finally:
        _slot.release()


def validate_authority_execution(execution, *, source_revision, runtime_image_id, registry_sha256, now):
    """Validate original joins; no submitted JSON establishes origin or an award.

    Owning collector/reviewer must freshly read these original domains. Code and
    evidence pins, authenticated origin and independent signed review remain
    separate requirements. The fixed-store comparison proves only the producer
    interval recorded by that owning execution, not arbitrary later writes.
    """
    try:
        require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
            'AUTHORITY_TIME_INVALID')
        value = parse(canonical(execution), 1024 * 1024)
        require(set(value) == {'case_spec', 'runtime', 'runtime_after', 'runtime_current', 'submission', 'dispatch',
            'artifact_metadata', 'artifact_content_utf8', 'objective_read', 'action_records', 'action_chain_join', 'observation'},
            'AUTHORITY_EXECUTION_FIELDS_INVALID')
        fixed = canonical_authority_case(value['case_spec'].get('case'))
        require(canonical(fixed) == canonical(value['case_spec']), 'AUTHORITY_CASE_SPEC_DRIFT')
        dispatch = value['dispatch']
        task = dispatch.get('task_id')
        bound = _bindings(task, value['runtime'], source_revision, runtime_image_id, registry_sha256)
        require(canonical(value['runtime_after']) == canonical(bound) and canonical(value['runtime_current']) == canonical(bound),
            'AUTHORITY_RUNTIME_CHANGED')
        require(set(dispatch) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model', 'agent_id',
            'capability', 'runtime_source_revision', 'authority_event'} and dispatch['state'] == 'COMPLETED'
            and dispatch['execution_model'] == 'DETERMINISTIC' and dispatch['agent_id'] == AGENT_ID
            and dispatch['capability'] == CAPABILITY_ID and dispatch['runtime_source_revision'] == source_revision
            and type(dispatch['model_calls']) is int and dispatch['model_calls'] == 0, 'AUTHORITY_DISPATCH_UNBOUND')
        event = dispatch['authority_event']
        require(type(event) is dict and set(event) == {'schema_version', 'case', 'case_version', 'task_id',
            'source_revision', 'registry_sha256', 'runtime_identity_sha256', 'case_spec_sha256', 'input_sha256',
            'subject_action_id', 'started_at', 'completed_at', 'read_domains_before', 'read_domains_after',
            'fixed_store_no_change_scope', 'durable_action_delivery', 'consequential_guard_denial_proven', 'certification'},
            'AUTHORITY_EVENT_FIELDS_INVALID')
        began, ended = _utc(event['started_at']), _utc(event['completed_at'])
        require(0 <= (ended - began).total_seconds() <= 5 and 0 <= (now - ended).total_seconds() <= MAX_AGE_SECONDS,
            'AUTHORITY_EVENT_STALE_OR_UNBOUNDED')
        expected = {'schema_version': EVENT_SCHEMA, 'case': fixed['case'], 'case_version': CASE_VERSION,
            'task_id': task, 'source_revision': source_revision, 'registry_sha256': registry_sha256,
            'runtime_identity_sha256': sha(canonical(bound)), 'case_spec_sha256': sha(canonical(fixed)),
            'input_sha256': sha(input_bytes(fixed['case'])), 'subject_action_id': event['subject_action_id'],
            'started_at': event['started_at'], 'completed_at': event['completed_at'],
            'read_domains_before': _snapshot(event['read_domains_before']), 'read_domains_after': _snapshot(event['read_domains_after']),
            'fixed_store_no_change_scope': 'PRODUCER_INTERVAL_ONLY_EXCLUDES_ARTIFACTS_ACTION_LEDGER_AND_SQLITE_SHM',
            'durable_action_delivery': True, 'consequential_guard_denial_proven': False, 'certification': 'UNVERIFIED'}
        require(canonical(event) == canonical(expected) and _uuid(event['subject_action_id'])
            and canonical(event['read_domains_before']) == canonical(event['read_domains_after']), 'AUTHORITY_EVENT_UNBOUND')
        observation = value['observation']
        require(type(observation) is dict and set(observation) == {'started_at', 'completed_at'}
            and _utc(observation['started_at']) <= began <= ended <= _utc(observation['completed_at']) <= now
            and 0 <= (_utc(observation['completed_at']) - _utc(observation['started_at'])).total_seconds() <= 5,
            'AUTHORITY_OBSERVATION_UNBOUND')
        metadata = value['artifact_metadata']
        require(type(value['artifact_content_utf8']) is str, 'AUTHORITY_ORIGINAL_BYTES_REQUIRED')
        raw = value['artifact_content_utf8'].encode()
        parse(raw)
        expected_raw = expected_result_bytes(fixed['case'], current_authority_policy(registry_sha256),
            sha(canonical(event['read_domains_before'])))
        require(raw == expected_raw and canonical(dispatch['artifact']) == canonical(metadata), 'AUTHORITY_RESULT_DRIFT')
        _metadata(metadata, raw, task, source_revision, began, ended)
        from .agent_cert_identity_review import action_span
        _original_lines(value['action_records'])
        chain = action_span(value['action_records'], task_id=task, agent_id=AGENT_ID,
            action_type=authority_action_type(fixed['case']), schema=RESULT_SCHEMA, metadata=metadata,
            began=began, ended=ended, action_id=event['subject_action_id'])
        require(canonical(chain) == canonical(value['action_chain_join']), 'AUTHORITY_ACTION_JOIN_DRIFT')
        submission, read = value['submission'], value['objective_read']
        step = {'capability': CAPABILITY_ID, 'dispatch': dispatch}
        require(type(submission) is list and len(submission) == 2 and type(submission[0]) is int and submission[0] == 202
            and type(submission[1]) is dict and submission[1].get('id') == task
            and canonical(submission[1].get('steps')) == canonical([step]), 'AUTHORITY_OBJECTIVE_SUBMISSION_UNBOUND')
        require(type(read) is list and len(read) == 2 and type(read[0]) is int and read[0] == 200 and type(read[1]) is dict,
            'AUTHORITY_OBJECTIVE_READ_REQUIRED')
        objective = read[1]
        require(objective.get('id') == task and type(objective.get('revision')) is int and objective['revision'] == 0
            and objective.get('state') == 'COMPLETED'
            and canonical(objective.get('steps')) == canonical([{**step, 'revision': 0, 'state': 'completed'}]),
            'AUTHORITY_OBJECTIVE_READ_UNBOUND')
        immutable = objective.get('execution_metadata')
        zero = {'schema_version': 'jarvis.inference-attempts.v1', 'source': 'COMPUTE_LEDGER',
            'status': 'NOT_APPLICABLE', 'attempts': [], 'missing_job_ids': [], 'verification': 'UNVERIFIED',
            'timestamp_source': 'QUEUE_JOB_LIFECYCLE', 'attempt_timestamp': 'NOT_RECORDED',
            'digest_scope': 'SANITIZED_PROJECTION_NOT_SIGNATURE'}
        require(type(immutable) is dict and immutable.get('schema_version') == 'jarvis.authoritative-execution.v1'
            and immutable.get('authoritative') is True and immutable.get('task_id') == task
            and type(immutable.get('revision')) is int and immutable['revision'] == 0 and immutable.get('state') == 'COMPLETED'
            and canonical(immutable.get('runtime')) == canonical(bound) and canonical(immutable.get('jobs')) == b'[]'
            and canonical(immutable.get('agent_execution')) == b'[]' and canonical(immutable.get('inference_attempts')) == canonical(zero)
            and immutable.get('model_content_is_authoritative_metadata') is False
            and immutable.get('provenance', {}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME'
            and _utc(observation['started_at']) <= _utc(immutable.get('created_at')) <= began
            and _utc(parse(value['action_records'][-1].encode())['timestamp']) <= _utc(immutable.get('completed_at'))
                <= _utc(immutable.get('updated_at')) <= _utc(observation['completed_at']), 'AUTHORITY_IMMUTABLE_OBJECTIVE_UNBOUND')
        return {'case': fixed['case'], 'task_id': task, 'artifact_id': metadata['artifact_id'], 'result_sha256': sha(raw),
            'case_spec_sha256': sha(canonical(fixed)), 'registry_sha256': registry_sha256, 'runtime': bound,
            'subject_action_sha256': chain['last_sha256'], 'execution_metadata_sha256': sha(canonical(immutable)),
            'fixed_read_domains_sha256': sha(canonical(event['read_domains_before'])),
            'consequential_guard_denial_proven': False, 'certification': 'UNVERIFIED',
            'event_verification': 'JOIN_VALIDATED_ORIGIN_AND_INDEPENDENT_ACCEPTANCE_REQUIRED'}
    except AuthorityEventError:
        raise
    except Exception:
        raise AuthorityEventError('AUTHORITY_EVENT_REJECTED') from None
