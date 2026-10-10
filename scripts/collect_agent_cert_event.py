"""Collect one original zero-model event through protected, bounded callbacks.

This operator-only adapter has no CLI, credential/client, ledger path, store,
signer or certification mutation. OperatorIO supplies existing Owner-authorized
operations. read_subject_actions(task_id, fixed_action_type) must additionally
read the original persisted subject span; it cannot fabricate or flush records.
Callbacks must enforce their own deadlines: synchronous Python cannot preempt
an uncooperative callback. This adapter checks one shared deadline before and
after reads and before either one-shot mutation, and never retries a mutation.

Original outputs are repr-hidden protected evidence, not automatic public logs.
Even a collected event remains UNSIGNED and pending protected admission/signing.
The owning validators, not this convenience collector, supply proof semantics.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import time
import uuid

from app.agent_cert_execution import observe_cert_case
from app.agent_cert_identity_review import action_span, parse, utc
from app.agent_cert_role_review import (canonical_case_spec, ARTIFACT_REVIEW_SCHEMA,
    ARTIFACT_REVIEW_ACTION, ARTIFACT_REVIEW_OPERATION, ARTIFACT_REVIEW_OBJECTIVE,
    artifact_event_review_join, AUTHORITY_REVIEW_SCHEMA, AUTHORITY_REVIEW_ACTION,
    AUTHORITY_REVIEW_OPERATION, AUTHORITY_REVIEW_OBJECTIVE, authority_event_review_join,
    TOOL_REVIEW_SCHEMA, TOOL_REVIEW_ACTION, TOOL_REVIEW_OPERATION, TOOL_REVIEW_OBJECTIVE, tool_event_review_join)
from scripts.collect_agent_cert_case import (
    OperatorIO, CollectionError, _call, _canonical, _copy, _equal, _now,
    _require, _response, _runtime, _sha, _tick, _uuid,
)


_REV = re.compile(r'[0-9a-f]{40}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_ARTIFACT = re.compile(r'[0-9a-f]{32}\Z')
_METADATA_FIELDS = {'artifact_id', 'task_id', 'type', 'creator_agents', 'timestamp',
    'version', 'provenance', 'runtime_revision', 'validation_state',
    'content_validation', 'location', 'sha256', 'bytes', 'delivery_state'}


@dataclass(frozen=True)
class CollectedEvent:
    summary: dict
    execution_bytes: bytes | None = field(default=None, repr=False)
    review_bytes: bytes | None = field(default=None, repr=False)
    subject_artifact_bytes: bytes | None = field(default=None, repr=False)
    reviewer_artifact_bytes: bytes | None = field(default=None, repr=False)
    subject_actions: tuple[str, ...] = field(default=(), repr=False)
    reviewer_actions: tuple[str, ...] = field(default=(), repr=False)
    # Canonical encoding of the original decoded callback reply, not a claim
    # of raw HTTP wire preservation. Retained even after a late one-shot reply.
    reviewer_dispatch_response_bytes: bytes | None = field(default=None, repr=False)
    input_artifact_bytes: bytes | None = field(default=None, repr=False)
    input_actions: tuple[str, ...] = field(default=(), repr=False)
    prior_artifact_bytes: bytes | None = field(default=None, repr=False)
    prior_actions: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class CollectedRecoveryCase:
    summary: dict
    execution_bytes: bytes | None = field(default=None,repr=False)
    peer_execution_bytes: bytes | None = field(default=None,repr=False)
    original_http_replies: tuple = field(default=(),repr=False)


def collect_recovery_case(*,operator_factory,expected_source_revision,expected_runtime_image,
        expected_registry_sha256,timeout_seconds=30,monotonic=time.monotonic,
        wall_clock=lambda:datetime.now(timezone.utc),nonce_factory=lambda:str(uuid.uuid4())):
    """Exactly two producer Objectives and a third persisted fixed A26 Objective.

    The injected factory must return the existing bounded fixed-loopback phase
    operator. It injects an already authorized credential; this collector never
    finds credentials, signs, renews, accesses local domains or retries a POST.
    """
    from app.agent_cert_recovery_events import (PRIOR_PHASE,CORRECTION_PHASE,CASE,canonical_phase_spec,
        action_type,REVIEW_ACTION,validate_phase_execution,validate_reviewed_recovery,canonical_review_request)
    from scripts.agent_cert_operator_io import RecoveryPhaseOperatorIO
    summary=dict(state='INCOMPLETE',case=CASE,agent_id='a19',certification='UNVERIFIED',
        production_recovery='NOT_ESTABLISHED',model_calls=0,submission_attempts=0,stage='PREPARE')
    operators=[];execution=peer=None
    try:
        _require(callable(operator_factory) and type(timeout_seconds) in (int,float)
            and 0<timeout_seconds<=30,'RECOVERY_BOUNDED_FACTORY_REQUIRED')
        deadline=_tick(monotonic)+timeout_seconds
        def remaining():
            left=deadline-_tick(monotonic)
            _require(left>0,'RECOVERY_OUTER_DEADLINE_EXCEEDED')
            return left
        def call(callback,*args):
            remaining();value=_call(callback,*args);remaining();return value
        def original_artifact(operator,metadata):
            response=call(operator.read_artifact,metadata['artifact_id'])
            _require(type(response) is tuple and len(response)==3 and response[0]==200
                and type(response[1]) is bytes and 0<len(response[1])<=65536
                and response[2]==metadata['sha256']==_sha(response[1]),'RECOVERY_ORIGINAL_HTTP_ARTIFACT_REQUIRED')
            return response[1]
        def make(which,**kwargs):
            operator=operator_factory(which=which,total_timeout_seconds=min(30,remaining()),**kwargs)
            _require(type(operator) is RecoveryPhaseOperatorIO,'RECOVERY_OWNED_TRANSPORT_REQUIRED')
            operators.append(operator)
            _require(call(operator.authorize) is None,'OWNER_AUTHENTICATION_FAILED')
            return operator
        pins=dict(source_revision=expected_source_revision,runtime_image_id=expected_runtime_image,
            registry_sha256=expected_registry_sha256)
        def produce(which,prior=None):
            nonlocal execution
            summary['stage']=which.upper()
            operator=make(which,prior_execution=prior)
            before=call(operator.runtime)
            _registry_pin(expected_registry_sha256)
            began=wall_clock()
            # Update before the one-shot POST; late replies remain private custody.
            summary['submission_attempts']+=1
            submission=_response(call(operator.submit_objective,operator._submitted_request),202,'RECOVERY_OBJECTIVE_SUBMIT_FAILED')
            _require(_uuid(submission.get('id')) and type(submission.get('steps')) is list
                and len(submission['steps'])==1,'RECOVERY_ORIGINAL_SUBMISSION_REQUIRED')
            dispatch=submission['steps'][0]['dispatch'];task=dispatch['task_id']
            metadata=dispatch['artifact'];event=dispatch['recovery_event']
            raw=original_artifact(operator,metadata)
            input_raw=original_artifact(operator,event['input_artifact_metadata'])
            objective=_response(call(operator.read_objective,task),200,'RECOVERY_OBJECTIVE_READ_FAILED')
            observed_end=wall_clock()
            lines=_lines(call(operator.read_subject_actions,task,action_type(which,'full')))
            after=call(operator.runtime)
            _require(_equal(before,after),'RECOVERY_RUNTIME_CHANGED')
            value=dict(case_spec=canonical_phase_spec(which),submitted_request=_copy(operator._submitted_request),
                runtime=before,runtime_after=after,runtime_current=call(operator.runtime),
                submission=[202,submission],dispatch=dispatch,artifact_metadata=metadata,
                artifact_content_utf8=raw.decode(),input_content_utf8=input_raw.decode(),
                objective_read=[200,objective],original_action_records=lines,
                observation=dict(started_at=began.isoformat(),completed_at=observed_end.isoformat()),prior_execution=prior)
            execution=value # Retain originals before pure acceptance; no synthetic repair.
            joined=validate_phase_execution(value,**pins,now=wall_clock())
            _require(_equal(objective,_response(call(operator.read_objective,task),200,'RECOVERY_OBJECTIVE_READ_FAILED')),
                'RECOVERY_OBJECTIVE_CHANGED')
            return value,joined
        prior,prior_join=produce(PRIOR_PHASE)
        summary['controlled_failure_task_id']=prior_join['task_id']
        corrected,joined=produce(CORRECTION_PHASE,prior)
        execution=corrected
        summary.update(stage='DISTINCT_PERSISTED_PEER',subject_task_id=joined['task_id'])
        nonce=call(nonce_factory)
        operator=make('review',execution=corrected,nonce=nonce)
        before=call(operator.runtime);began=wall_clock()
        _registry_pin(expected_registry_sha256);summary['submission_attempts']+=1
        submission=_response(call(operator.submit_objective,canonical_review_request(corrected,nonce=nonce)),202,
            'RECOVERY_PEER_OBJECTIVE_SUBMIT_FAILED')
        task=submission['id'];dispatch=submission['steps'][0]['dispatch'];metadata=dispatch['artifact']
        raw=original_artifact(operator,metadata)
        objective=_response(call(operator.read_objective,task),200,'RECOVERY_PEER_OBJECTIVE_READ_FAILED')
        lines=_lines(call(operator.read_subject_actions,task,REVIEW_ACTION))
        after=call(operator.runtime);_require(_equal(before,after),'RECOVERY_PEER_RUNTIME_CHANGED')
        peer=dict(submitted_request=canonical_review_request(corrected,nonce=nonce),runtime=before,
            runtime_after=after,submission=[202,submission],dispatch=dispatch,artifact_metadata=metadata,
            artifact_content_utf8=raw.decode(),objective_read=[200,objective],action_records=lines,
            observation=dict(started_at=began.isoformat(),completed_at=wall_clock().isoformat()))
        validate_reviewed_recovery(corrected,peer,**pins,now=wall_clock())
        _registry_pin(expected_registry_sha256);remaining()
        summary.update(state='UNSIGNED_EVENT_EVIDENCE',stage='COMPLETE',peer_task_id=task,
            source_revision=expected_source_revision,runtime_image_id=expected_runtime_image,
            execution_sha256=_sha(_canonical(corrected)),peer_execution_sha256=_sha(_canonical(peer)),
            original_producer_rows=12,original_peer_rows=2,controlled_failure_retained=True)
    except Exception as error:
        summary['reason']=str(error) if isinstance(error,(CollectionError,)) else 'RECOVERY_ORIGINAL_CHAIN_INCOMPLETE'
    replies=tuple(reply for operator in operators for reply in operator.original_replies())
    return CollectedRecoveryCase(summary,None if execution is None else _canonical(execution),
        None if peer is None else _canonical(peer),replies)


def _contract(agent, capability, case):
    from app.agent_cert_tool_events import (SUPPORTED_CASES as TOOL_CASES,
        RESULT_SCHEMA as TOOL_RESULT_SCHEMA, oracle_id, tool_action_type)
    if case in TOOL_CASES:
        _require((agent, capability) == ('a19', 'responsibility.a19'), 'SOURCE_OWNED_EVENT_UNAVAILABLE')
        from app.agent_cert_role_review import tool_review_objective
        return (tool_action_type(case), TOOL_RESULT_SCHEMA, TOOL_REVIEW_SCHEMA, oracle_id(case),
            tool_review_objective(case), ('a26', 'responsibility.a26'), tool_event_review_join)
    from app.agent_cert_authority_events import (SUPPORTED_CASES as AUTHORITY_CASES,
        RESULT_SCHEMA as AUTHORITY_RESULT_SCHEMA, ORACLE_ID as AUTHORITY_ORACLE, authority_action_type)
    if case in AUTHORITY_CASES:
        _require((agent, capability) == ('a19', 'responsibility.a19'), 'SOURCE_OWNED_EVENT_UNAVAILABLE')
        return (authority_action_type(case), AUTHORITY_RESULT_SCHEMA, AUTHORITY_REVIEW_SCHEMA,
            AUTHORITY_ORACLE, AUTHORITY_REVIEW_OBJECTIVE, ('a26', 'responsibility.a26'), authority_event_review_join)
    from app.agent_cert_artifact_events import SUPPORTED_CASES, RESULT_SCHEMA, oracle_id, artifact_action_type
    if case in SUPPORTED_CASES:
        _require((agent, capability) == ('a19', 'responsibility.a19'), 'SOURCE_OWNED_EVENT_UNAVAILABLE')
        return (artifact_action_type(case), RESULT_SCHEMA, ARTIFACT_REVIEW_SCHEMA,
            oracle_id(case), ARTIFACT_REVIEW_OBJECTIVE, ('a26', 'responsibility.a26'), artifact_event_review_join)
    if case == 'baseline:initialization':
        from app.agent_cert_initialization import (
            ACTION_TYPE, SCHEMA, initialization_reviewer, initialization_oracle_id,
            initialization_review_objective,
        )
        from app.agent_cert_initialization_review import (
            SCHEMA as review_schema, validate_initialization_execution,
        )
        def validate(value, **pins):
            return validate_initialization_execution(value, agent_id=agent,
                capability_id=capability, **pins)
        return (ACTION_TYPE, SCHEMA, review_schema,
            initialization_oracle_id(agent, capability),
            initialization_review_objective(agent, capability),
            initialization_reviewer(agent, capability), validate)
    if case == 'baseline:identity' and (agent, capability) != ('a19', 'responsibility.a19'):
        from app.agent_cert_owned_identity import (ACTION_TYPE, SCHEMA, REVIEW_SCHEMA,
            ORACLE_ID, identity_reviewer, identity_review_objective, validate_owned_identity_execution)
        def validate(value, **pins):
            return validate_owned_identity_execution(value, agent_id=agent, capability_id=capability, **pins)
        return (ACTION_TYPE, SCHEMA, REVIEW_SCHEMA, ORACLE_ID, identity_review_objective(agent, capability),
            identity_reviewer(agent, capability), validate)
    _require((agent, capability, case) == ('a19', 'responsibility.a19', 'baseline:identity'),
             'SOURCE_OWNED_EVENT_UNAVAILABLE')
    from app.agent_cert_identity_review import SCHEMA, ORACLE_ID, validate_identity_execution
    from app.agent_dispatch_api import IDENTITY_REVIEW_OBJECTIVE
    return ('runtime.status.artifact', 'jarvis.runtime-status.v1', SCHEMA,
        ORACLE_ID, IDENTITY_REVIEW_OBJECTIVE, ('a26', 'responsibility.a26'),
        validate_identity_execution)


def _registry_pin(expected):
    # Only the owning public source path is read. It is not a callback-provided
    # filesystem path or a runtime/private configuration reader. RAW bytes must
    # match the protected image's pin; CRLF is never rewritten into acceptance.
    from app.agent_registry import REGISTRY_PATH
    _require(REGISTRY_PATH.is_file() and not REGISTRY_PATH.is_symlink()
             and REGISTRY_PATH.stat().st_size <= 1024 * 1024,
             'LOCAL_REVIEW_SOURCE_MISMATCH')
    with REGISTRY_PATH.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    _require(len(raw) <= 1024 * 1024 and _sha(raw) == expected,
             'LOCAL_REVIEW_SOURCE_MISMATCH')


def _lines(value):
    _require(type(value) is list and 2 <= len(value) <= 128
             and all(type(line) is str and line.endswith('\n')
                     and 0 < len(line) <= 65536
                     and len(line.encode('utf-8')) <= 65536 for line in value),
             'ORIGINAL_DURABLE_ACTIONS_REQUIRED')
    return value


def _artifact(io, identifier, metadata, holder, *, subject=False, input_artifact=False, prior_artifact=False):
    _require(type(identifier) is str and _ARTIFACT.fullmatch(identifier) is not None,
             'ARTIFACT_ID_INVALID')
    value = _call(io.read_artifact, identifier)
    _require(type(value) is tuple and len(value) == 3 and type(value[0]) is int
             and value[0] == 200 and type(value[1]) is bytes
             and 0 < len(value[1]) <= 65536, 'ORIGINAL_ARTIFACT_READ_FAILED')
    holder['prior_raw' if prior_artifact else 'input_raw' if input_artifact else 'subject_raw' if subject else 'reviewer_raw'] = value[1]
    _require(type(value[2]) is str and value[2] == _sha(value[1])
             and type(metadata) is dict and set(metadata) == _METADATA_FIELDS
             and metadata.get('sha256') == value[2]
             and type(metadata.get('bytes')) is int and metadata['bytes'] == len(value[1]),
             'ORIGINAL_ARTIFACT_DIGEST_MISMATCH')
    return value[1]


def collect_event_case(spec, *, io: OperatorIO, read_subject_actions,
                       expected_source_revision, expected_runtime_image,
                       expected_registry_sha256, reviewer_code_revision,
                       review_run_id, timeout_seconds=10,
                       monotonic=time.monotonic,
                       wall_clock=lambda: datetime.now(timezone.utc),
                       nonce_factory=lambda: str(uuid.uuid4())) -> CollectedEvent:
    """One actual subject event and one distinct review, never portable approval."""
    summary = dict(schema='prime.agent-cert-event-collection.v1', state='REJECTED',
        stage='PRECHECK', certification='UNVERIFIED', signature='NOT_PERFORMED',
        protected_signing='PENDING_SEPARATE_ADMISSION', subject_submission_attempts=0,
        review_dispatch_attempts=0, submission_uncertain=False,
        review_dispatch_uncertain=False, source_revision=None, runtime_image_id=None)
    holder = dict(subject_raw=None, reviewer_raw=None, reviewer_dispatch=None, input_raw=None, prior_raw=None)
    primary = review_raw = None
    subject_lines = reviewer_lines = input_lines = prior_lines = ()
    execution = {}
    try:
        _require(type(io) is OperatorIO and callable(read_subject_actions)
            and all(callable(getattr(io, name)) for name in ('authorize', 'runtime',
                'submit_objective', 'read_objective', 'dispatch_reviewer',
                'read_artifact', 'read_review_actions')), 'AUTHENTICATED_EVENT_CALLBACKS_REQUIRED')
        _require(type(expected_source_revision) is str and _REV.fullmatch(expected_source_revision) is not None
            and type(expected_runtime_image) is str and _IMAGE.fullmatch(expected_runtime_image) is not None
            and type(expected_registry_sha256) is str and _SHA.fullmatch(expected_registry_sha256) is not None
            and type(reviewer_code_revision) is str and _REV.fullmatch(reviewer_code_revision) is not None
            and type(review_run_id) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', review_run_id) is not None,
            'PROTECTED_EVENT_BINDINGS_REQUIRED')
        _require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 30,
                 'BOUNDED_EVENT_DEADLINE_REQUIRED')
        deadline = _tick(monotonic) + timeout_seconds
        def bounded():
            _require(_tick(monotonic) < deadline, 'BOUNDED_EVENT_OBSERVATION_INCOMPLETE')
        def read(callback, *args):
            bounded()
            value = _call(callback, *args)
            bounded()
            return value
        _require(read(io.authorize) is None, 'OWNER_AUTHENTICATION_FAILED')
        _registry_pin(expected_registry_sha256)
        _require(type(spec) is dict, 'CANONICAL_EVENT_REQUIRED')
        canonical = canonical_case_spec(spec.get('agent_id'), spec.get('capability_id'), spec.get('case'))
        _require(_equal(canonical, spec), 'CANONICAL_EVENT_CHANGED')
        agent, capability, case = canonical['agent_id'], canonical['capability_id'], canonical['case']
        from app.agent_cert_artifact_events import SUPPORTED_CASES as ARTIFACT_CASES
        from app.agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES
        from app.agent_cert_tool_events import SUPPORTED_CASES as TOOL_CASES
        artifact_case = case in ARTIFACT_CASES
        authority_case = case in AUTHORITY_CASES
        tool_case = case in TOOL_CASES
        bounded_event = artifact_case or authority_case or tool_case
        dimension = case.split(':')[0]
        action_type, report_schema, review_schema, oracle, review_objective, reviewer_pair, validate = _contract(agent, capability, case)
        reviewer, reviewer_cap = reviewer_pair
        _require(reviewer != agent, 'INDEPENDENT_REVIEWER_REQUIRED')
        bounded()
        before = _runtime(io, expected_source_revision, expected_runtime_image)
        bounded()
        summary.update(agent_id=agent, capability_id=capability, case=case,
            source_revision=expected_source_revision, runtime_image_id=expected_runtime_image,
            registry_sha256=expected_registry_sha256, canonical_case_sha256=_sha(_canonical(canonical)))
        execution.update(case_spec=_copy(canonical), runtime=before)
        def submit(request):
            _require(_equal(request, canonical['request']), 'CANONICAL_EVENT_CHANGED')
            _registry_pin(expected_registry_sha256)
            _require(read(io.authorize) is None, 'OWNER_AUTHENTICATION_FAILED')
            bounded()
            summary.update(stage='SUBJECT_SUBMIT', subject_submission_attempts=1, submission_uncertain=True)
            value = _response(_call(io.submit_objective, _copy(request)), 202, 'OBJECTIVE_SUBMIT_FAILED')
            execution['submission'] = [202, value]
            if _uuid(value.get('id')):
                summary['subject_task_id'] = value['id']
            bounded()
            steps = value.get('steps')
            _require(_uuid(value.get('id')) and type(steps) is list and len(steps) == 1
                and type(steps[0]) is dict and steps[0].get('capability') == capability
                and type(steps[0].get('dispatch')) is dict
                and steps[0]['dispatch'].get('task_id') == value['id'], 'SUBJECT_OBJECTIVE_BINDING_INVALID')
            execution['dispatch'] = _copy(steps[0]['dispatch'])
            summary['subject_task_id'] = value['id']
            return execution['dispatch']
        def artifact(key):
            metadata = execution['dispatch'].get('artifact')
            bounded()
            raw = _artifact(io, key, metadata, holder, subject=True)
            execution.update(artifact_metadata=_copy(metadata), artifact_content_utf8=raw.decode('utf-8'))
            bounded()
            return _copy(metadata), raw
        def runtime():
            bounded()
            value = _runtime(io, expected_source_revision, expected_runtime_image)
            bounded()
            _require(_equal(before, value), 'RUNTIME_IDENTITY_CHANGED')
            return value
        def no_job(_):
            raise CollectionError('ZERO_MODEL_EVENT_HAS_NO_QUEUE') from None
        observed = _copy(observe_cert_case(canonical, dispatch=submit,
            get_artifact=artifact, get_job=no_job, get_runtime=runtime,
            expected_source_revision=expected_source_revision,
            expected_registry_sha256=expected_registry_sha256,
            timeout_seconds=min(5, max(0.001, deadline - _tick(monotonic))),
            monotonic=monotonic, wall_clock=wall_clock))
        execution['observation'] = ({key: observed[key] for key in ('started_at', 'completed_at')}
            if bounded_event and observed.get('state') == 'EXECUTED' else observed)
        primary = _canonical(execution)
        _require(observed.get('state') == 'EXECUTED', 'SUBJECT_EVENT_INCOMPLETE')
        if bounded_event:
            execution['runtime_after'] = runtime()
        task = execution['dispatch']['task_id']
        summary.update(stage='SUBJECT_JOIN', submission_uncertain=False)
        objective = _response(read(io.read_objective, task), 200, 'OWNED_OBJECTIVE_READ_FAILED')
        execution['objective_read'] = [200, objective]
        bounded()
        events = _lines(_call(read_subject_actions, task, action_type))
        subject_lines = tuple(events)
        execution['action_records'] = events
        # Retain bounded original counterevidence before rejecting a late read.
        # Custody is not acceptance, and cannot cause a retry or further POST.
        bounded()
        observation = execution['observation']
        event = (execution['dispatch'].get('tool_event') if tool_case else
            execution['dispatch'].get('authority_event') if authority_case else
            execution['dispatch'].get('artifact_event') if artifact_case else None)
        action_began = utc(event['started_at'] if bounded_event else observation['captured_at'])
        action_ended = utc(event['completed_at'] if bounded_event else observation['completed_at'])
        execution['action_chain_join'] = action_span(events, task_id=task, agent_id=agent,
            action_type=action_type, schema=report_schema, metadata=execution['artifact_metadata'],
            began=action_began, ended=action_ended,
            **({'action_id': event['subject_action_id']} if bounded_event else {}))
        if tool_case:
            from app.agent_cert_tool_events import INPUT_SCHEMA, tool_action_type, failed_read_span
            input_metadata = event['input_artifact_metadata']
            raw = _artifact(io, input_metadata.get('artifact_id') if type(input_metadata) is dict else None,
                input_metadata, holder, input_artifact=True)
            execution['input_content_utf8'] = raw.decode()
            lines = _lines(read(read_subject_actions, task, tool_action_type(case, phase='setup')))
            input_lines = tuple(lines)
            execution['input_action_records'] = lines
            execution['input_action_chain_join'] = action_span(lines, task_id=task, agent_id=agent,
                action_type=tool_action_type(case, phase='setup'), schema=INPUT_SCHEMA, metadata=input_metadata,
                began=action_began, ended=action_ended, action_id=event['setup_action_id'])
            if case in {'graceful_degradation:complete','health:complete','tools:complete','independent_verification:complete','injection_resistance:complete', 'continuous_revalidation:complete', 'cross_verification:complete', 'collaboration:complete'}:
                from app.agent_cert_tool_events import available_read_span
                available_lines = _lines(read(read_subject_actions, task, tool_action_type(case, phase='available')))
                execution['available_read_action_records'] = available_lines
                execution['available_read_action_chain_join'] = available_read_span(available_lines, task_id=task,
                    case=case, setup_metadata=input_metadata, input_raw=raw, began=action_began, ended=action_ended,
                    action_id=event['available_read_action_id'])
            if case not in {'tools:complete','independent_verification:complete','injection_resistance:complete', 'continuous_revalidation:complete', 'cross_verification:complete', 'collaboration:complete'}:
                lines = _lines(read(read_subject_actions, task, tool_action_type(case, phase='read')))
                execution['failed_read_action_records'] = lines
                execution['failed_read_action_chain_join'] = failed_read_span(lines, task_id=task, case=case,
                    setup_metadata=input_metadata, began=action_began, ended=action_ended,
                    action_id=event['failed_read_action_id'])
            execution['original_action_records'] = _lines(read(read_subject_actions, task,
                tool_action_type(case, phase='full')))
        if artifact_case:
            from app.agent_cert_artifact_events import INPUT_SCHEMA, artifact_action_type
            execution.update(input_content_utf8=None, input_action_records=[], input_action_chain_join=None)
            if case != 'general:artifact_produce':
                input_metadata = event['input_artifact_metadata']
                bounded()
                raw = _artifact(io, input_metadata.get('artifact_id') if type(input_metadata) is dict else None,
                    input_metadata, holder, input_artifact=True)
                execution['input_content_utf8'] = raw.decode('utf-8')
                bounded()
                lines = _lines(_call(read_subject_actions, task, artifact_action_type(case, setup=True)))
                input_lines = tuple(lines)
                execution['input_action_records'] = lines
                bounded()
                execution['input_action_chain_join'] = action_span(lines, task_id=task, agent_id=agent,
                    action_type=artifact_action_type(case, setup=True), schema=INPUT_SCHEMA,
                    metadata=input_metadata, began=action_began, ended=action_ended,
                    action_id=event['input_action_id'])
            if case in {'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'}:
                prior_metadata = event['prior_artifact_metadata']
                bounded()
                raw = _artifact(io, prior_metadata.get('artifact_id') if type(prior_metadata) is dict else None,
                    prior_metadata, holder, prior_artifact=True)
                execution['prior_artifact_content_utf8'] = raw.decode('utf-8')
                bounded()
                lines = _lines(_call(read_subject_actions, task, artifact_action_type(case, prior=True)))
                prior_lines = tuple(lines)
                execution['prior_action_records'] = lines
                bounded()
                execution['prior_action_chain_join'] = action_span(lines, task_id=task, agent_id=agent,
                    action_type=artifact_action_type(case, prior=True), schema=report_schema, metadata=prior_metadata,
                    began=action_began, ended=action_ended, action_id=event['prior_action_id'])
        if bounded_event:
            execution['runtime_current'] = runtime()
        primary = _canonical(execution)
        _require(len(primary) <= 1024 * 1024, 'EVENT_ENVELOPE_TOO_LARGE')
        now = _now(wall_clock)
        join = validate(execution, source_revision=expected_source_revision,
            runtime_image_id=expected_runtime_image, registry_sha256=expected_registry_sha256, now=now)
        runtime()
        _require(_equal(objective, _response(read(io.read_objective, task), 200,
            'OWNED_OBJECTIVE_READ_FAILED')), 'OWNED_OBJECTIVE_CHANGED')
        nonce = read(nonce_factory)
        _require(_uuid(nonce), 'REVIEW_NONCE_INVALID')
        context = _canonical(dict(execution=execution, expected_execution_sha256=_sha(primary),
            expected_source_revision=expected_source_revision, review_nonce=nonce)).decode('utf-8')
        _require(len(context.encode('utf-8')) <= 80000, 'REVIEW_CONTEXT_TOO_LARGE')
        request = dict(classification='R0', capability=reviewer_cap, objective=review_objective,
            context=context, data_classification='LOCAL_ONLY', minimum_tier='NANO', priority='low',
            task_class='classification', max_cost_usd=0, response_format='strict_json',
            deterministic_operation=TOOL_REVIEW_OPERATION if tool_case else AUTHORITY_REVIEW_OPERATION if authority_case else ARTIFACT_REVIEW_OPERATION if artifact_case else
                'certification_initialization_review' if case.endswith('initialization')
                else 'certification_owned_identity_review' if (agent, capability) != ('a19', 'responsibility.a19')
                else 'certification_identity_review')
        _registry_pin(expected_registry_sha256)
        _require(read(io.authorize) is None, 'OWNER_AUTHENTICATION_FAILED')
        runtime()
        bounded()
        summary.update(stage='REVIEW_DISPATCH', review_dispatch_attempts=1, review_dispatch_uncertain=True)
        result = _response(_call(io.dispatch_reviewer, request), 202, 'REVIEW_DISPATCH_FAILED')
        holder['reviewer_dispatch'] = _canonical([202, result])
        if _uuid(result.get('task_id')):
            summary['review_task_id'] = result['task_id']
        bounded()
        _require(set(result) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model',
            'agent_id', 'capability', 'runtime_source_revision', 'review_action_id',
            'review_action_durable', 'certification'} and _uuid(result.get('task_id'))
            and result['task_id'] != task and _uuid(result.get('review_action_id'))
            and result.get('agent_id') == reviewer and result.get('capability') == reviewer_cap
            and result.get('state') == 'COMPLETED' and type(result.get('model_calls')) is int
            and result['model_calls'] == 0 and result.get('execution_model') == 'DETERMINISTIC'
            and result.get('runtime_source_revision') == expected_source_revision
            and result.get('review_action_durable') is True and result.get('certification') == 'UNVERIFIED',
            'DURABLE_DISTINCT_REVIEW_REQUIRED')
        summary.update(review_task_id=result['task_id'], review_dispatch_uncertain=False, stage='REVIEW_JOIN')
        bounded()
        metadata = result['artifact']
        raw = _artifact(io, metadata.get('artifact_id') if type(metadata) is dict else None,
            metadata, holder)
        content = parse(raw)
        _require(_equal(metadata.get('creator_agents'), [reviewer]) and metadata.get('task_id') == result['task_id']
            and metadata.get('type') == 'json' and metadata.get('version') == '1.0.0'
            and metadata.get('runtime_revision') == expected_source_revision
            and metadata.get('provenance') == 'Deterministic computation; zero model calls'
            and metadata.get('validation_state') == 'STRUCTURE_VALIDATED'
            and metadata.get('content_validation') == 'Not independently established by structural validation'
            and metadata.get('location') == 'artifact.json' and metadata.get('delivery_state') == 'AVAILABLE',
            'REVIEW_ARTIFACT_BINDING_INVALID')
        expected = dict(schema_version=review_schema, task_id=result['task_id'], reviewer_id=reviewer,
            reviewer_capability_id=reviewer_cap, subject_agent_id=agent, subject_capability_id=capability,
            dimension=dimension, test_case=case.split(':')[1], source_revision=expected_source_revision,
            runtime_image_id=expected_runtime_image, execution_evidence_sha256=_sha(primary),
            case_spec_sha256=_sha(_canonical(canonical)), result_sha256=join['result_sha256'],
            oracle_id=oracle, test_result='PASS', review_errors=[], model_calls=0,
            execution_model='DETERMINISTIC', subject_execution_verification='ARTIFACT_OBJECTIVE_ACTION_JOINED',
            subject_domain_join=join, certification='UNVERIFIED')
        peer_objective = None
        if case in {'cross_verification:complete','collaboration:complete'}:
            from app.agent_cert_tool_events import cross_peer_request,validate_cross_peer_receipt,validate_cross_peer_objective,peer_review_fields
            peer_request = cross_peer_request(execution,nonce,expected_source_revision)
            receipt = content.get('peer_request_receipt')
            validate_cross_peer_receipt(receipt,peer_task=result['task_id'],subject_task=task,
                request=peer_request,runtime=before,now=_now(wall_clock))
            expected.update(peer_review_fields(case,receipt))
            peer_objective = _response(read(io.read_objective,result['task_id']),200,'CROSS_ORIGINAL_PEER_REQUEST_REQUIRED')
            validate_cross_peer_objective(peer_objective,dispatch=result,runtime=before,receipt=receipt,now=_now(wall_clock))
        _require(set(content) == set(expected) | {'review_nonce', 'reviewed_at'}
            and content.get('review_nonce') == nonce
            and all(_equal(content.get(key), value) for key, value in expected.items()),
            'REGISTERED_REVIEW_CONTENT_MISMATCH')
        now = _now(wall_clock)
        _require(utc(join['completed_at']) <= utc(content['reviewed_at'])
            <= utc(metadata['timestamp']) <= now, 'REVIEW_TIME_INVALID')
        bounded()
        lines = _lines(_call(io.read_review_actions, result['review_action_id']))
        reviewer_lines = tuple(lines)
        bounded()
        action_span(lines, task_id=result['task_id'], agent_id=reviewer,
            action_type=TOOL_REVIEW_ACTION if tool_case else AUTHORITY_REVIEW_ACTION if authority_case else ARTIFACT_REVIEW_ACTION if artifact_case else
                'agent.certification.' + case.split(':')[1] + '.review',
            schema=review_schema, metadata=metadata, began=utc(content['reviewed_at']),
            ended=now, action_id=result['review_action_id'], duration_limit_ms=120000)
        proof = dict(dispatch=result, artifact_content_utf8=raw.decode('utf-8'), action_records=lines,
            transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
                artifact_http_status=200, runtime_source_revision=expected_source_revision,
                actual_runtime_image=expected_runtime_image))
        if peer_objective is not None:
            final_peer = _response(read(io.read_objective,result['task_id']),200,'CROSS_ORIGINAL_PEER_REQUEST_REQUIRED')
            _require(_equal(final_peer,peer_objective),'CROSS_ORIGINAL_PEER_REQUEST_CHANGED')
            validate_cross_peer_objective(final_peer,dispatch=result,runtime=before,receipt=receipt,now=_now(wall_clock))
            proof.update(peer_objective_read=[200,peer_objective],peer_request_body=peer_request)
        review = dict(schema_version='prime.agent-certification.review.v1', reviewer_identity=reviewer,
            review_run_id=review_run_id, source_revision=expected_source_revision, agent_id=agent,
            capability_id=capability, dimension=dimension, test_case=case.split(':')[1],
            execution_evidence_sha256=_sha(primary), test_result='PASS', review_test_version=oracle,
            observations=dict(execution_task_id=task, result_sha256=join['result_sha256'],
                case_spec_sha256=join['case_spec_sha256'], runtime_image_id=expected_runtime_image,
                registry_sha256=expected_registry_sha256, reviewer_code_revision=reviewer_code_revision,
                oracle_id=oracle, oracle_pass=True, reviewer_execution=proof))
        review_raw = _canonical(review)
        _require(len(review_raw) <= 1024 * 1024, 'REVIEW_ENVELOPE_TOO_LARGE')
        _require(_equal(objective, _response(read(io.read_objective, task), 200,
            'OWNED_OBJECTIVE_READ_FAILED')), 'OWNED_OBJECTIVE_CHANGED')
        runtime()
        _registry_pin(expected_registry_sha256)
        _require(_equal(canonical, canonical_case_spec(agent, capability, case)), 'CANONICAL_EVENT_CHANGED')
        bounded()
        summary.update(state='UNSIGNED_EVENT_EVIDENCE', stage='COLLECTED', reason=None,
            validation='ORIGINAL_EVENT_AND_DISTINCT_REGISTERED_REVIEW_JOINED', model_calls=0,
            subject_artifact_id=execution['artifact_metadata']['artifact_id'],
            subject_artifact_sha256=_sha(holder['subject_raw']), execution_sha256=_sha(primary),
            reviewer_identity=reviewer, reviewer_capability_id=reviewer_cap,
            reviewer_artifact_id=metadata['artifact_id'], reviewer_artifact_sha256=_sha(raw),
            review_sha256=_sha(review_raw), collected_at=now.isoformat(),
            callback_deadlines='REQUIRED_FROM_PROTECTED_OPERATOR_NOT_PREEMPTIBLE_BY_COLLECTOR')
    except CollectionError as exc:
        summary.update(reason=str(exc), validation='NOT_ACCEPTED')
    except Exception:
        summary.update(reason='EVENT_COLLECTION_REJECTED', validation='NOT_ACCEPTED')
    # Preserve partially observed original evidence even when a later join fails.
    if execution and summary['state'] != 'UNSIGNED_EVENT_EVIDENCE':
        try:
            primary = _canonical(execution)
        except Exception:
            pass
    return CollectedEvent(summary, primary, review_raw, holder['subject_raw'],
        holder['reviewer_raw'], subject_lines, reviewer_lines, holder['reviewer_dispatch'],
        holder['input_raw'], input_lines, holder['prior_raw'], prior_lines)
