"""Distinct registered owned-identity events; never activation, authority or L7.

The original A19 runtime-status identity contract is unchanged. These explicit
events identify each other actual owned pair from current raw/loaded Registry
source, with original Objective/artifact/action custody and a separate peer.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import threading

from .agent_cert_initialization import (_bindings, _instant, _owned_domains,
    _owned_pair, _parse, canonical, sha, initialization_reviewer, MAX_BYTES,
    MAX_AGE_SECONDS)

CASE = 'baseline:identity'
SCHEMA = 'jarvis.owned-agent-identity.v1'
ORACLE_ID = 'registered.owned-identity.v1'
ACTION_TYPE = 'agent.certification.owned_identity.artifact'
OPERATION = 'certification_owned_identity'
REVIEW_SCHEMA = 'prime.agent-cert-owned-identity-review.v1'
REVIEW_ACTION = 'agent.certification.owned_identity.review'
REVIEW_OPERATION = 'certification_owned_identity_review'
_slot = threading.BoundedSemaphore(1)


class OwnedIdentityError(ValueError):
    """Fixed public errors; no submitted content, private paths or exception text."""


def require(value, code):
    if value is not True:
        raise OwnedIdentityError(code) from None


def owned_pair(agent_id, capability_id):
    record, selected = _owned_pair(agent_id, capability_id)
    require((agent_id, capability_id) != ('a19', 'responsibility.a19'),
        'OWNED_IDENTITY_LEGACY_A19_REQUIRED')
    return record, selected


def identity_objective(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return (f'Identify current canonical registered {agent_id.upper()} and its owned capability {capability_id} '
        'from the actual Registry; produce a distinct zero-model identity artifact without claiming '
        'runtime activation, health, execution authority or certification.')


def identity_reviewer(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return initialization_reviewer(agent_id, capability_id)


def identity_review_objective(agent_id, capability_id):
    owned_pair(agent_id, capability_id)
    return (f'Independently review one recorded {agent_id.upper()} identity event for {capability_id} '
        'against the current owned Registry, original Objective, artifact and action records; do not certify or sign.')


def canonical_owned_identity_case(agent_id, capability_id):
    return dict(agent_id=agent_id, capability_id=capability_id, case=CASE,
        request=dict(capability=capability_id, objective=identity_objective(agent_id, capability_id), context='',
            classification='R0', data_classification='LOCAL_ONLY', minimum_tier='NANO', priority='low',
            task_class='classification', max_cost_usd=0.0, preferred_provider=None,
            response_format='strict_json', deterministic_operation=OPERATION),
        independent_review=('authenticated_owner', 'registered_owned_capability_route',
            'original_owned_identity_artifact', 'owned_objective_action_join', 'independent_verifier'),
        expected_discriminants=('Actual canonical agent and selected owned capability are distinct identities',
            'Raw Registry and its loaded domain agree', 'Identity definition does not establish activation or authority'),
        certification='UNVERIFIED')


def _facts(agent_id, capability_id, registry_sha256):
    owned_pair(agent_id, capability_id)
    owned = _owned_domains(registry_sha256, agent_id, capability_id)
    definition, selected = owned['definition'], owned['selected_capability']
    return owned, dict(canonical_agent_id=definition['immutable_id'], role=definition['role'],
        owned_capability_id=selected['id'], responsibility_owner=agent_id,
        selected_responsibility=selected, selected_responsibility_sha256=sha(canonical(selected)))


def _gaps():
    return dict(runtime_activation='NOT_ESTABLISHED_BY_DEFINITION', health='NOT_MEASURED',
        role_completion='NOT_ESTABLISHED', execution_authority='NOT_GRANTED',
        independent_review='NOT_PERFORMED', signed_attestation='NOT_PRESENT', l7='UNVERIFIED')


def build_identity_report(task_id, *, agent_id, capability_id, runtime, source_revision,
        runtime_image_id, registry_sha256, now=None):
    bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
    captured = _instant(datetime.now(timezone.utc) if now is None else now)
    owned, identity = _facts(agent_id, capability_id, registry_sha256)
    return dict(schema_version=SCHEMA, case=CASE, oracle_id=ORACLE_ID, task_id=task_id,
        agent_id=agent_id, capability_id=capability_id, captured_at=captured.isoformat(), runtime=bound,
        owned_domains=owned, identity=identity, observation='CANONICAL_AGENT_AND_OWNED_CAPABILITY_READ',
        evidence_gaps=_gaps(), execution=dict(method='DETERMINISTIC_READ_ONLY', model_calls=0,
            input_tokens=0, output_tokens=0, fresh_inference_performed=False), certification='UNVERIFIED')


def validate_identity_report(raw, *, task_id, agent_id, capability_id, runtime, source_revision,
        runtime_image_id, registry_sha256, now):
    report = _parse(raw, MAX_BYTES)
    try:
        captured = _instant(datetime.fromisoformat(report['captured_at']))
    except Exception:
        raise OwnedIdentityError('OWNED_IDENTITY_TIME_INVALID') from None
    current = _instant(now)
    require(0 <= (current - captured).total_seconds() <= MAX_AGE_SECONDS, 'OWNED_IDENTITY_TIME_UNBOUND')
    bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
    owned, identity = _facts(agent_id, capability_id, registry_sha256)
    # Independently stated literal event claims; never call the report producer
    # to decide whether its output falsely claimed activation or certification.
    expected = dict(schema_version=SCHEMA, case=CASE, oracle_id=ORACLE_ID, task_id=task_id,
        agent_id=agent_id, capability_id=capability_id, captured_at=captured.isoformat(), runtime=bound,
        owned_domains=owned, identity=identity, observation='CANONICAL_AGENT_AND_OWNED_CAPABILITY_READ',
        evidence_gaps=dict(runtime_activation='NOT_ESTABLISHED_BY_DEFINITION', health='NOT_MEASURED',
            role_completion='NOT_ESTABLISHED', execution_authority='NOT_GRANTED', independent_review='NOT_PERFORMED',
            signed_attestation='NOT_PRESENT', l7='UNVERIFIED'),
        execution=dict(method='DETERMINISTIC_READ_ONLY', model_calls=0, input_tokens=0,
            output_tokens=0, fresh_inference_performed=False), certification='UNVERIFIED')
    require(canonical(report) == canonical(expected), 'OWNED_IDENTITY_REPORT_MISMATCH')
    return report


def validate_owned_identity_execution(execution, **pins):
    from .agent_cert_identity_review import _validate_event_execution, _OWNED_IDENTITY_ADAPTER
    return _validate_event_execution(execution, _adapter=_OWNED_IDENTITY_ADAPTER, **pins)


def execute_owned_identity_case(spec, task_id, *, submitted_request, data_root, ledger,
        runtime, read_runtime, source_revision, runtime_image_id, registry_sha256):
    """Authenticated owning dispatcher only; one actual new task/artifact/pair."""
    require(_slot.acquire(blocking=False), 'OWNED_IDENTITY_PRODUCER_BUSY')
    try:
        from .action_records import ActionLedger, ActionRecord, DirectExecutor
        from .artifact_factory import ArtifactFactory
        from .agent_cert_artifact_events import _path, _ledger_lines, parse, _utc
        fixed = canonical_owned_identity_case(spec.get('agent_id'), spec.get('capability_id'))
        require(canonical(spec) == canonical(fixed) and canonical(submitted_request) == canonical(fixed['request']),
            'OWNED_IDENTITY_FIXED_POLICY_REQUIRED')
        bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
        require(callable(read_runtime) and canonical(read_runtime()) == canonical(bound), 'OWNED_IDENTITY_RUNTIME_UNBOUND')
        root = _path(data_root)
        require(type(ledger) is ActionLedger and _path(ledger.path) == root / 'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'OWNED_IDENTITY_LEDGER_REQUIRED')
        began = datetime.now(timezone.utc)
        # Original owning task only, revision zero; no manufactured Objective.
        path = _path(root / 'objectives.db')
        require(path.is_file(), 'OWNED_IDENTITY_OBJECTIVE_REQUIRED')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            row = db.execute('SELECT objective_hash,state,steps_json FROM objectives WHERE id=?', (task_id,)).fetchone()
            turns = db.execute('SELECT revision FROM objective_turns WHERE task=? LIMIT 1', (task_id,)).fetchone()
            times = db.execute('SELECT revision,created_at,updated_at FROM objective_metadata WHERE task=? LIMIT 2', (task_id,)).fetchall()
            pins = db.execute('SELECT revision,host_id,source_revision,version,image_digest FROM objective_runtime WHERE task=? LIMIT 2', (task_id,)).fetchall()
        require(row is not None and row[0] == sha(fixed['request']['objective'].encode()) and row[1] == 'dispatching'
            and row[2] == json.dumps([fixed['capability_id']]) and turns is None and len(times) == 1
            and type(times[0][0]) is int and times[0][0] == 0 and times[0][1] == times[0][2]
            and 0 <= (began - _utc(times[0][1])).total_seconds() <= MAX_AGE_SECONDS
            and pins == [(0, bound['host_id'], bound['source_revision'], bound['version'], bound['image_digest'])],
            'OWNED_IDENTITY_OBJECTIVE_DRIFT')
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks == 0, 'OWNED_IDENTITY_PRIOR_ACTION_PENDING')
        require(all(not (parse(line.encode()).get('task_id') == task_id and
            parse(line.encode()).get('action_type') == ACTION_TYPE) for line in _ledger_lines(root)),
            'OWNED_IDENTITY_ALREADY_ATTEMPTED')
        factory = ArtifactFactory(_path(root / 'artifacts'))
        record = ActionRecord(task_id, fixed['agent_id'], ACTION_TYPE, 'artifact-factory',
            parameters_summary={'schema_version': SCHEMA, 'read_only_observations': True})
        def operation():
            report = build_identity_report(task_id, agent_id=fixed['agent_id'], capability_id=fixed['capability_id'],
                runtime=bound, source_revision=source_revision, runtime_image_id=runtime_image_id,
                registry_sha256=registry_sha256)
            raw = canonical(report)
            metadata = factory.create(kind='json', content=raw.decode(), task_id=task_id,
                creator=fixed['agent_id'], provenance='Deterministic computation; zero model calls',
                runtime_revision=source_revision)
            original, content = factory.retrieve(metadata['artifact_id'])
            require(canonical(original) == canonical(metadata) and content == raw, 'OWNED_IDENTITY_READBACK_DRIFT')
            validate_identity_report(content, task_id=task_id, agent_id=fixed['agent_id'], capability_id=fixed['capability_id'],
                runtime=bound, source_revision=source_revision, runtime_image_id=runtime_image_id,
                registry_sha256=registry_sha256, now=datetime.now(timezone.utc))
            return metadata
        artifact = DirectExecutor(ledger).execute(record, operation)
        require(ledger.flush(timeout=1) is True, 'OWNED_IDENTITY_DURABLE_ACTION_REQUIRED')
        _facts(fixed['agent_id'], fixed['capability_id'], registry_sha256)
        require(canonical(read_runtime()) == canonical(bound) and
            0 <= (datetime.now(timezone.utc) - began).total_seconds() <= 5, 'OWNED_IDENTITY_RUNTIME_OR_TIME_DRIFT')
        return dict(task_id=task_id, state='COMPLETED', artifact=artifact, model_calls=0,
            execution_model='DETERMINISTIC', agent_id=fixed['agent_id'], capability=fixed['capability_id'],
            runtime_source_revision=source_revision)
    except OwnedIdentityError:
        raise
    except Exception:
        raise OwnedIdentityError('OWNED_IDENTITY_EXECUTION_REJECTED') from None
    finally:
        _slot.release()
