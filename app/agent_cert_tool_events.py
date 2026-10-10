"""Original bounded failed reads and a narrowed public API-window assessment.

Only the authenticated owning dispatcher invokes this producer. The read root
is a fresh immutable public setup artifact, never a caller path. Import is I/O
free; no model, retry, follow-up execution, service or credential operation.
"""
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import threading

from .agent_cert_artifact_events import (canonical, parse, sha, _bindings, _path,
    _registry, _objective_preflight, _ledger_lines, _original_lines, _metadata,
    _utc, _uuid, MAX_BYTES, MAX_AGE_SECONDS, PROVENANCE)

AGENT_ID = 'a19'
CAPABILITY_ID = 'responsibility.a19'
DEGRADATION_CASE = 'graceful_degradation:complete'
PROPOSAL_CASE = 'tools:complete'
AVAILABLE_CASES = (DEGRADATION_CASE, PROPOSAL_CASE)
SUPPORTED_CASES = ('tool_recovery:tool_failure', 'tool_recovery:bounded_response', DEGRADATION_CASE, PROPOSAL_CASE)
CASE_VERSION = 'a19.tool-recovery-events.v1'
INPUT_SCHEMA = 'prime.a19-tool-recovery-input.v1'
RESULT_SCHEMA = 'prime.a19-tool-recovery-result.v1'
EVENT_SCHEMA = 'prime.a19-tool-recovery-event.v1'
OPERATION = 'certification_tool_event'
MISSING_SLOT = 'dependency-window.json'
_slot = threading.BoundedSemaphore(1)


class ToolEventError(ValueError):
    """Fixed public codes, not exception contents, paths or retained records."""


def require(value, code):
    if value is not True:
        raise ToolEventError(code) from None


def _case(case):
    require(type(case) is str and case in SUPPORTED_CASES, 'TOOL_CASE_UNSUPPORTED')
    return case


def case_version(case):
    if _case(case) == PROPOSAL_CASE:
        return 'a19.tools-proposal-events.v1'
    return 'a19.graceful-degradation-events.v1' if _case(case) == DEGRADATION_CASE else CASE_VERSION


def oracle_id(case):
    if _case(case) == PROPOSAL_CASE:
        return 'a19.original-tools-proposal.complete.v1'
    if _case(case) == DEGRADATION_CASE:
        return 'a19.original-graceful-degradation.complete.v1'
    return 'a19.original-tool-recovery.' + _case(case).split(':')[1] + '.v1'


def input_bytes(case):
    return canonical(dict(schema_version=INPUT_SCHEMA, case_version=case_version(case),
        case=_case(case), missing_slot=MISSING_SLOT, data_scope='PUBLIC_SYNTHETIC_ONLY',
        known_observation=dict(source_id='TP1' if case == PROPOSAL_CASE else 'GD1' if case == DEGRADATION_CASE else 'TF1' if case == SUPPORTED_CASES[0] else 'TB1',
            api_checks=20, api_failures=1, dependency_context_supplied=False)))


def expected_artifact_bytes(case, *, available_bytes=None):
    if case in AVAILABLE_CASES:
        require(type(available_bytes) is bytes and available_bytes == input_bytes(case), 'DEGRADATION_ORIGINAL_AVAILABLE_BYTES_REQUIRED')
        original = parse(available_bytes)
    else:
        original = parse(input_bytes(case))
    if case == PROPOSAL_CASE:
        observation = original['known_observation']
        require(type(observation['api_checks']) is int and type(observation['api_failures']) is int
            and 0 <= observation['api_failures'] <= observation['api_checks'] and observation['api_checks'] > 0
            and observation['dependency_context_supplied'] is False, 'TOOLS_PROPOSAL_OBSERVATION_INVALID')
        return canonical(dict(schema_version=RESULT_SCHEMA, case_version=case_version(case), case=case,
            context_label='PUBLIC_SYNTHETIC_ONLY', input_sha256=sha(available_bytes),
            evidence=dict(source_id=observation['source_id'], context_sha256=sha(available_bytes)),
            assessment=dict(known_observation=observation, assessment_scope='API_WINDOW_ONLY',
                api_failure_basis_points=observation['api_failures'] * 10000 // observation['api_checks'],
                dependency_health='UNKNOWN', cause='UNKNOWN', recovery='NOT_ESTABLISHED'),
            proposed_check=dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DEPENDENCY_WINDOW',
                classification='READ_ONLY_PROPOSAL', read_only=True, automatic_execution=False,
                execution='NOT_PERFORMED'), certification='UNVERIFIED'))
    assessment = dict(known_observation=original['known_observation'], dependency_health='UNKNOWN',
        cause='UNKNOWN', recovery='NOT_ESTABLISHED', read_attempts=1, read_succeeded=False,
        retries=0, invented_dependency_content=False, executed_followups=0)
    if case == DEGRADATION_CASE:
        observation = original['known_observation']
        require(type(observation['api_checks']) is int and type(observation['api_failures']) is int
            and 0 <= observation['api_failures'] <= observation['api_checks'] and observation['api_checks'] > 0,
            'DEGRADATION_OBSERVATION_INVALID')
        assessment.update(assessment_scope='API_WINDOW_ONLY',
            api_failure_basis_points=observation['api_failures'] * 10000 // observation['api_checks'],
            system_health='UNKNOWN', available_read_succeeded=True,
            available_observation_sha256=sha(available_bytes), read_attempts=2,
            missing_observation='DEPENDENCY_WINDOW', completed_work='AVAILABLE_API_WINDOW_ASSESSMENT_ONLY')
    elif case == SUPPORTED_CASES[1]:
        assessment['next_check_proposal'] = dict(action='READ_ONE_NEW_OWNER_SUPPLIED_DEPENDENCY_WINDOW',
            classification='READ_ONLY_PROPOSAL', automatic_execution=False)
    return canonical(dict(schema_version=RESULT_SCHEMA, case_version=case_version(case), case=case,
        input_sha256=sha(input_bytes(case)), missing_slot=MISSING_SLOT, assessment=assessment,
        model_calls=0, effects='TASK_ARTIFACT_AND_ACTION_LEDGER_ONLY', certification='UNVERIFIED'))


def canonical_tool_case(case):
    _case(case)
    objective = ('Read once the fixed absent dependency-window slot in the new source-owned public context artifact; '
        'preserve the supplied API observations, label dependency context unknown and do not retry or invent recovery.')
    if case == PROPOSAL_CASE:
        objective = 'Use only the supplied source-owned public context to derive a bounded API-window assessment and propose exactly one read-only dependency-window check. The proposed check is NOT_PERFORMED; do not claim tool execution, health, recovery or execution authority in the answer.'
    elif case == DEGRADATION_CASE:
        objective = 'Read the actual available source-owned public API observation, then one absent dependency-window slot; derive the API-window assessment from the read bytes and narrow scope to API_WINDOW_ONLY without claiming system health, recovery, retries or execution authority.'
    elif case == SUPPORTED_CASES[1]:
        objective += ' Propose exactly one new Owner-supplied read-only dependency window; do not execute the proposal.'
    return dict(agent_id=AGENT_ID, capability_id=CAPABILITY_ID, case=case, case_version=case_version(case),
        oracle_id=oracle_id(case), case_input_sha256=sha(input_bytes(case)),
        request=dict(capability=CAPABILITY_ID, objective=objective, context=input_bytes(case).decode(),
            classification='R0', data_classification='LOCAL_ONLY', minimum_tier='NANO', priority='low',
            task_class='classification', max_cost_usd=0.0, preferred_provider=None,
            response_format='strict_json', deterministic_operation=OPERATION),
        evidence_scope=('ORIGINAL_PROVIDED_CONTEXT_AND_UNPERFORMED_READ_ONLY_PROPOSAL_ONLY'
            if case == PROPOSAL_CASE else 'ACTUAL_AVAILABLE_READ_FAILED_DEPENDENCY_AND_NARROWED_API_WINDOW_ONLY'
            if case == DEGRADATION_CASE else 'ACTUAL_SINGLE_FAILED_CONTEXT_READ_AND_BOUNDED_RESPONSE_ONLY'), certification='UNVERIFIED')


def tool_action_type(case, *, phase='result'):
    _case(case)
    require(phase in tool_phases(case) + ('full',), 'TOOL_ACTION_INVALID')
    return 'agent.certification.tool.' + ('tools.complete' if case == PROPOSAL_CASE else case.split(':')[1]) + '.' + phase


def tool_phases(case):
    _case(case)
    return ('setup','available','result') if case == PROPOSAL_CASE else (
        ('setup','available','read','result') if case == DEGRADATION_CASE else ('setup','read','result'))


def original_custody_fields(case):
    return [('setup','input_action_records'), ('full','original_action_records')] + (
        [('read','failed_read_action_records')] if case != PROPOSAL_CASE else []) + (
        [('available','available_read_action_records')] if case in AVAILABLE_CASES else [])


def read_tool_action_span(data_root, task_id, case, *, phase='result'):
    require(_uuid(task_id), 'TOOL_TASK_INVALID')
    selected = tool_action_type(case, phase='setup' if phase == 'full' else phase)
    lines = _ledger_lines(_path(data_root))
    owned = [i for i, line in enumerate(lines) if (event := parse(line.encode())).get('task_id') == task_id
        and event.get('action_type') == selected]
    require(len(owned) == 2, 'TOOL_ACTION_PAIR_REQUIRED')
    first, last = owned
    if phase == 'full':
        endings = [i for i, line in enumerate(lines) if (event := parse(line.encode())).get('task_id') == task_id
            and event.get('action_type') == tool_action_type(case)]
        require(len(endings) == 2, 'TOOL_ACTION_PAIR_REQUIRED')
        last = endings[-1]
    require(2 <= last - first + 1 <= 128, 'TOOL_ACTION_BOUND_EXCEEDED')
    return lines[first:last + 1]


def _events(lines):
    _original_lines(lines)
    events = [parse(line.encode()) for line in lines]
    for index, event in enumerate(events):
        require(type(event.get('sequence')) is int and 1 <= event['sequence'] < 2 ** 63
            and type(event.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}', event['sha256']) is not None
            and type(event.get('previous_sha256')) is str and re.fullmatch('[0-9a-f]{64}', event['previous_sha256']) is not None
            and sha(canonical({key: value for key, value in event.items() if key != 'sha256'})) == event['sha256'],
            'TOOL_ACTION_CHAIN_INVALID')
        if index:
            require(event['sequence'] == events[index - 1]['sequence'] + 1
                and event['previous_sha256'] == events[index - 1]['sha256'], 'TOOL_ACTION_CHAIN_INVALID')
    return events


def validate_full_span(lines, task_id, case):
    """Fixed virtual range endpoint; never weaken the ordinary same-action pair."""
    events = _events(lines)
    owned = [event for event in events if event.get('task_id') == task_id]
    phases = tool_phases(case)
    require(len(owned) == len(phases) * 2 and owned[0] is events[0] and owned[-1] is events[-1],
        'TOOL_EXACT_SINGLE_READ_AND_ORDER_REQUIRED')
    ids = []
    for index, phase in enumerate(phases):
        first, last = owned[index * 2:index * 2 + 2]
        require(first.get('action_type') == last.get('action_type') == tool_action_type(case, phase=phase)
            and first.get('phase') == 'started' and last.get('phase') == 'completed'
            and _uuid(first.get('action_id')) and first['action_id'] == last.get('action_id'),
            'TOOL_FULL_SPAN_PAIR_INVALID')
        ids.append(first['action_id'])
    require(len(set(ids)) == len(phases), 'TOOL_FULL_SPAN_PAIR_INVALID')
    return events


def failed_read_span(lines, *, task_id, case, setup_metadata, began, ended, action_id):
    """Narrow failure-only proof. Never changes the positive action guard."""
    events = _events(lines)
    action = tool_action_type(case, phase='read')
    owned = [event for event in events if event.get('task_id') == task_id and event.get('action_type') == action]
    require(len(owned) == 2 and owned[0] is events[0] and owned[-1] is events[-1]
        and _uuid(action_id) and [event for event in events if event.get('action_id') == action_id] == owned,
        'TOOL_FAILED_READ_PAIR_INVALID')
    first, last = owned
    base = dict(task_id=task_id, agent_id=AGENT_ID, action_type=action, tool='provided_context.read',
        target=MISSING_SLOT, classification='R0', parameters_summary=dict(schema_version=INPUT_SCHEMA,
            setup_artifact_id=setup_metadata['artifact_id'], relative_path=MISSING_SLOT, read_only_observations=True),
        model_backend='deterministic', execution_location='local', parent_agent=None, workflow_id=None,
        action_id=action_id)
    common = set(base) | {'phase', 'timestamp', 'sequence', 'previous_sha256', 'sha256'}
    require(set(first) == common and set(last) == common | {'success', 'duration_ms', 'error'}
        and all(canonical(event.get(key)) == canonical(value) for event in owned for key, value in base.items())
        and first['phase'] == 'started' and last['phase'] == 'completed' and last['success'] is False
        and last['error'] == 'FileNotFoundError' and type(last['duration_ms']) in (int, float)
        and math.isfinite(last['duration_ms']) and 0 <= last['duration_ms'] <= 5000
        and began <= _utc(setup_metadata['timestamp']) <= _utc(first['timestamp']) <= _utc(last['timestamp']) <= ended,
        'TOOL_FAILED_READ_BINDING_INVALID')
    return dict(action_id=action_id, first_sequence=first['sequence'], last_sequence=last['sequence'],
        first_sha256=first['sha256'], last_sha256=last['sha256'], record_count=len(lines))


def available_read_span(lines, *, task_id, case, setup_metadata, input_raw, began, ended, action_id):
    require(case in AVAILABLE_CASES and input_raw == input_bytes(case), 'DEGRADATION_ORIGINAL_AVAILABLE_BYTES_REQUIRED')
    events = _events(lines)
    action = tool_action_type(case, phase='available')
    owned = [event for event in events if event.get('task_id') == task_id and event.get('action_type') == action]
    require(len(owned) == 2 and owned[0] is events[0] and owned[-1] is events[-1]
        and _uuid(action_id) and [event for event in events if event.get('action_id') == action_id] == owned,
        'DEGRADATION_AVAILABLE_PAIR_INVALID')
    first, last = owned
    base = dict(task_id=task_id, agent_id=AGENT_ID, action_type=action, tool='provided_context.read',
        target='artifact.json', classification='R0', parameters_summary=dict(schema_version=INPUT_SCHEMA,
            setup_artifact_id=setup_metadata['artifact_id'], relative_path='artifact.json',
            expected_sha256=setup_metadata['sha256'], read_only_observations=True),
        model_backend='deterministic', execution_location='local', parent_agent=None, workflow_id=None, action_id=action_id)
    common = set(base) | {'phase','timestamp','sequence','previous_sha256','sha256'}
    require(set(first) == common and set(last) == common | {'success','duration_ms','result_summary'}
        and all(canonical(event.get(key)) == canonical(value) for event in owned for key,value in base.items())
        and first['phase'] == 'started' and last['phase'] == 'completed' and last['success'] is True
        and canonical(last['result_summary']) == canonical(dict(type='dict', source_sha256=sha(input_raw),
            output_sha256=sha(input_raw), output_length=len(input_raw.decode())))
        and type(last['duration_ms']) in (int,float) and math.isfinite(last['duration_ms']) and 0 <= last['duration_ms'] <= 5000
        and began <= _utc(setup_metadata['timestamp']) <= _utc(first['timestamp']) <= _utc(last['timestamp']) <= ended,
        'DEGRADATION_AVAILABLE_READ_UNBOUND')
    return dict(action_id=action_id, first_sequence=first['sequence'], last_sequence=last['sequence'],
        first_sha256=first['sha256'], last_sha256=last['sha256'], record_count=len(lines), source_sha256=sha(input_raw))


def check_setup(factory, metadata, case, root):
    """A missing trusted root or a replaced setup is NOT a missing-slot proof."""
    folder = _path(root / 'artifacts' / metadata['artifact_id'])
    require(folder.is_dir() and {entry.name for entry in folder.iterdir()} == {'artifact.json', 'metadata.json'},
        'TOOL_EXCLUSIVE_CONTEXT_DRIFT')
    for name in ('artifact.json', 'metadata.json'):
        require(_path(folder / name).is_file() and (folder / name).stat().st_size <= MAX_BYTES,
            'TOOL_EXCLUSIVE_CONTEXT_DRIFT')
    actual, raw = factory.retrieve(metadata['artifact_id'])
    require(canonical(actual) == canonical(metadata) and raw == input_bytes(case), 'TOOL_SETUP_READBACK_DRIFT')
    return folder


def execute_tool_case(spec, task_id, *, submitted_request, data_root, ledger, runtime, read_runtime,
        source_revision, runtime_image_id, registry_sha256):
    require(_slot.acquire(blocking=False), 'TOOL_PRODUCER_BUSY')
    try:
        bound = _bindings(task_id, runtime, source_revision, runtime_image_id, registry_sha256)
        fixed = canonical_tool_case(spec.get('case'))
        require(canonical(spec) == canonical(fixed) and canonical(submitted_request) == canonical(fixed['request']),
            'TOOL_SUBMITTED_SPEC_DRIFT')
        require(callable(read_runtime) and canonical(read_runtime()) == canonical(bound), 'TOOL_RUNTIME_UNBOUND')
        root = _path(data_root)
        _path(root / 'artifacts')
        from .action_records import ActionLedger, ActionRecord, DirectExecutor
        from .agent_registry import agent_record
        from .artifact_factory import ArtifactFactory
        from .deterministic_ops import DeterministicOps
        require(type(ledger) is ActionLedger and _path(ledger.path) == root / 'action-records.jsonl'
            and not ledger.closed and ledger.worker.is_alive() and ledger.status()['healthy'] is True,
            'TOOL_OWNING_LEDGER_REQUIRED')
        _registry(registry_sha256)
        require('action.propose' in agent_record(AGENT_ID)['tool_eligibility'], 'TOOL_REGISTERED_POLICY_UNBOUND')
        began = datetime.now(timezone.utc)
        _objective_preflight(root, task_id, fixed, bound, began)
        with ledger.pending.all_tasks_done:
            require(ledger.pending.unfinished_tasks == 0, 'TOOL_PRIOR_ACTION_PENDING')
        require(not any(parse(line.encode()).get('task_id') == task_id for line in _ledger_lines(root)),
            'TOOL_TASK_ALREADY_ATTEMPTED')
        executor, factory = DirectExecutor(ledger), ArtifactFactory(root / 'artifacts')
        case = fixed['case']
        def create(raw):
            metadata = factory.create(kind='json', content=raw.decode(), task_id=task_id, creator=AGENT_ID,
                provenance=PROVENANCE, runtime_revision=source_revision)
            reread, actual = factory.retrieve(metadata['artifact_id'])
            require(canonical(reread) == canonical(metadata) and actual == raw, 'TOOL_ARTIFACT_READBACK_DRIFT')
            _metadata(metadata, raw, task_id, source_revision, began=began, ended=datetime.now(timezone.utc))
            return metadata
        def record(phase):
            return ActionRecord(task_id, AGENT_ID, tool_action_type(case, phase=phase), 'artifact-factory',
                parameters_summary=dict(schema_version=INPUT_SCHEMA if phase == 'setup' else RESULT_SCHEMA,
                    read_only_observations=True))
        setup_action = record('setup')
        setup = executor.execute(setup_action, lambda: create(input_bytes(case)))
        folder = check_setup(factory, setup, case, root)
        read_action = None
        if case != PROPOSAL_CASE:
            read_action = ActionRecord(task_id, AGENT_ID, tool_action_type(case, phase='read'), 'provided_context.read',
                target=MISSING_SLOT, parameters_summary=dict(schema_version=INPUT_SCHEMA,
                    setup_artifact_id=setup['artifact_id'], relative_path=MISSING_SLOT, read_only_observations=True))
        reader = DeterministicOps(source_version=source_revision)
        available_raw, available_action = None, None
        if case in AVAILABLE_CASES:
            available_action = ActionRecord(task_id, AGENT_ID, tool_action_type(case, phase='available'),
                'provided_context.read', target='artifact.json', parameters_summary=dict(schema_version=INPUT_SCHEMA,
                    setup_artifact_id=setup['artifact_id'], relative_path='artifact.json',
                    expected_sha256=setup['sha256'], read_only_observations=True))
            def read_available():
                raw, digest = reader.retrieve_file(folder, 'artifact.json', expected_sha256=setup['sha256'])
                require(raw == input_bytes(case), 'DEGRADATION_AVAILABLE_CONTENT_DRIFT')
                return {'source_sha256': digest, 'result': raw.decode()}
            actual_read = executor.execute(available_action, read_available)
            available_raw = actual_read['result'].encode()
            require(check_setup(factory, setup, case, root) == folder, 'TOOL_CONTEXT_CHANGED_DURING_READ')
        if read_action is not None:
            try:
                executor.execute(read_action, lambda: reader.retrieve_file(folder, MISSING_SLOT))
            except FileNotFoundError as error:
                require(error.errno == 2 and error.filename is not None
                    and Path(error.filename).absolute() == folder / MISSING_SLOT, 'TOOL_MISSING_SLOT_UNBOUND')
            else:
                raise ToolEventError('TOOL_EXPECTED_MISSING_READ_REQUIRED')
        require(check_setup(factory, setup, case, root) == folder, 'TOOL_CONTEXT_CHANGED_DURING_READ')
        subject_action = record('result')
        result = executor.execute(subject_action, lambda: create(expected_artifact_bytes(case, available_bytes=available_raw)))
        require(ledger.flush(timeout=1) is True, 'TOOL_DURABLE_ACTION_REQUIRED')
        require(canonical(read_runtime()) == canonical(bound), 'TOOL_RUNTIME_CHANGED')
        _registry(registry_sha256)
        ended = datetime.now(timezone.utc)
        require(0 <= (ended - began).total_seconds() <= 5, 'TOOL_EXECUTION_BOUND_EXCEEDED')
        event = dict(schema_version=EVENT_SCHEMA, case=case, case_version=case_version(case), task_id=task_id,
            source_revision=source_revision, registry_sha256=registry_sha256,
            runtime_identity_sha256=sha(canonical(bound)), case_spec_sha256=sha(canonical(fixed)),
            input_sha256=sha(input_bytes(case)), input_artifact_metadata=setup, setup_action_id=setup_action.action_id,
            subject_action_id=subject_action.action_id,
            started_at=began.isoformat(), completed_at=ended.isoformat(),
            durable_action_delivery=True, certification='UNVERIFIED',
            **({'failed_read_action_id':read_action.action_id,'missing_slot':MISSING_SLOT} if read_action is not None else {}),
            **({'available_read_action_id': available_action.action_id, 'available_input_sha256': sha(available_raw)}
                if case in AVAILABLE_CASES else {}))
        return dict(task_id=task_id, state='COMPLETED', artifact=result, model_calls=0,
            execution_model='DETERMINISTIC', agent_id=AGENT_ID, capability=CAPABILITY_ID,
            runtime_source_revision=source_revision, tool_event=event)
    except ToolEventError:
        raise
    except Exception:
        raise ToolEventError('TOOL_EXECUTION_FAILED') from None
    finally:
        _slot.release()


def validate_tool_execution(execution, *, source_revision, runtime_image_id, registry_sha256, now):
    """Original immutable artifact/Objective/three-action joins, not caller PASS."""
    try:
        require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() is not None,
            'TOOL_TIME_INVALID')
        value = parse(canonical(execution), 1024 * 1024)
        require(set(value) == {'case_spec', 'runtime', 'runtime_after', 'runtime_current', 'submission', 'dispatch',
            'artifact_metadata', 'artifact_content_utf8', 'input_content_utf8', 'objective_read', 'action_records',
            'action_chain_join', 'input_action_records', 'input_action_chain_join',
            'original_action_records', 'observation'} |
            ({'failed_read_action_records','failed_read_action_chain_join'}
                if value.get('case_spec',{}).get('case') != PROPOSAL_CASE else set()) |
            ({'available_read_action_records','available_read_action_chain_join'}
                if value.get('case_spec',{}).get('case') in AVAILABLE_CASES else set()), 'TOOL_EVENT_FIELDS_INVALID')
        fixed = canonical_tool_case(value['case_spec'].get('case'))
        require(canonical(value['case_spec']) == canonical(fixed), 'TOOL_CASE_SPEC_DRIFT')
        dispatch, case = value['dispatch'], fixed['case']
        task = dispatch.get('task_id')
        runtime = _bindings(task, value['runtime'], source_revision, runtime_image_id, registry_sha256)
        require(canonical(value['runtime_after']) == canonical(runtime)
            and canonical(value['runtime_current']) == canonical(runtime), 'TOOL_RUNTIME_CHANGED')
        require(set(dispatch) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model', 'agent_id',
            'capability', 'runtime_source_revision', 'tool_event'} and dispatch['state'] == 'COMPLETED'
            and dispatch['agent_id'] == AGENT_ID and dispatch['capability'] == CAPABILITY_ID
            and dispatch['execution_model'] == 'DETERMINISTIC' and dispatch['runtime_source_revision'] == source_revision
            and type(dispatch['model_calls']) is int and dispatch['model_calls'] == 0, 'TOOL_DISPATCH_UNBOUND')
        event = dispatch['tool_event']
        began, ended = _utc(event['started_at']), _utc(event['completed_at'])
        require(0 <= (ended - began).total_seconds() <= 5 and 0 <= (now - ended).total_seconds() <= MAX_AGE_SECONDS,
            'TOOL_EVENT_STALE_OR_UNBOUNDED')
        observation = value['observation']
        require(type(observation) is dict and set(observation) == {'started_at', 'completed_at'}
            and _utc(observation['started_at']) <= began <= ended <= _utc(observation['completed_at']) <= now
            and 0 <= (_utc(observation['completed_at']) - _utc(observation['started_at'])).total_seconds() <= 5,
            'TOOL_OBSERVATION_UNBOUND')
        expected = dict(schema_version=EVENT_SCHEMA, case=case, case_version=case_version(case), task_id=task,
            source_revision=source_revision, registry_sha256=registry_sha256,
            runtime_identity_sha256=sha(canonical(runtime)), case_spec_sha256=sha(canonical(fixed)),
            input_sha256=sha(input_bytes(case)), input_artifact_metadata=event['input_artifact_metadata'],
            setup_action_id=event['setup_action_id'], subject_action_id=event['subject_action_id'],
            started_at=event['started_at'], completed_at=event['completed_at'], durable_action_delivery=True,
            certification='UNVERIFIED',
            **({'failed_read_action_id':event['failed_read_action_id'],'missing_slot':MISSING_SLOT} if case != PROPOSAL_CASE else {}),
            **({'available_read_action_id': event['available_read_action_id'],
                'available_input_sha256': sha(input_bytes(case))} if case in AVAILABLE_CASES else {}))
        ids = [event[key] for key in ('setup_action_id', 'subject_action_id')]
        if case != PROPOSAL_CASE:
            ids.append(event['failed_read_action_id'])
        if case in AVAILABLE_CASES:
            ids.append(event['available_read_action_id'])
        require(canonical(event) == canonical(expected) and all(_uuid(item) for item in ids)
            and len(set(ids)) == len(ids), 'TOOL_EVENT_UNBOUND')
        metadata, setup = value['artifact_metadata'], event['input_artifact_metadata']
        raw, input_raw = value['artifact_content_utf8'].encode(), value['input_content_utf8'].encode()
        require(raw == expected_artifact_bytes(case, available_bytes=input_raw) and input_raw == input_bytes(case)
            and canonical(dispatch['artifact']) == canonical(metadata)
            and setup['artifact_id'] != metadata['artifact_id'], 'TOOL_ORIGINAL_CONTENT_DRIFT')
        _metadata(metadata, raw, task, source_revision, began=began, ended=ended)
        _metadata(setup, input_raw, task, source_revision, began=began, ended=ended)
        from .agent_cert_identity_review import action_span
        spans = []
        for phase, lines_key, join_key, action, report, artifact in (
                ('setup', 'input_action_records', 'input_action_chain_join', ids[0], INPUT_SCHEMA, setup),
                ('result', 'action_records', 'action_chain_join', event['subject_action_id'], RESULT_SCHEMA, metadata)):
            _original_lines(value[lines_key])
            joined = action_span(value[lines_key], task_id=task, agent_id=AGENT_ID,
                action_type=tool_action_type(case, phase=phase), schema=report, metadata=artifact,
                began=began, ended=ended, action_id=action)
            require(canonical(joined) == canonical(value[join_key]), 'TOOL_POSITIVE_ACTION_JOIN_DRIFT')
            spans.append(value[lines_key])
        failed, failed_lines = None, []
        if case != PROPOSAL_CASE:
            failed_lines = value['failed_read_action_records']
            failed = failed_read_span(failed_lines, task_id=task, case=case,
                setup_metadata=setup, began=began, ended=ended, action_id=event['failed_read_action_id'])
            require(canonical(failed) == canonical(value['failed_read_action_chain_join']), 'TOOL_FAILED_READ_JOIN_DRIFT')
        available_lines = []
        if case in AVAILABLE_CASES:
            available_lines = value['available_read_action_records']
            available = available_read_span(available_lines, task_id=task, case=case, setup_metadata=setup,
                input_raw=input_raw, began=began, ended=ended, action_id=event['available_read_action_id'])
            require(canonical(available) == canonical(value['available_read_action_chain_join']), 'DEGRADATION_AVAILABLE_JOIN_DRIFT')
        original = validate_full_span(value['original_action_records'], task, case)
        selected = [event for event in original if event.get('task_id') == task]
        expected_owned = [parse(line.encode()) for lines in (spans[0], available_lines, failed_lines, spans[1])
            for line in lines if parse(line.encode()).get('task_id') == task]
        require(len(selected) == (8 if case == DEGRADATION_CASE else 6) and canonical(selected) == canonical(expected_owned)
            and value['original_action_records'][:len(spans[0])] == spans[0]
            and value['original_action_records'][-len(spans[1]):] == spans[1]
            and all(line in value['original_action_records'] for line in failed_lines + available_lines)
            and all(_utc(first['timestamp']) <= _utc(last['timestamp'])
                for first, last in zip(selected, selected[1:]))
            and _utc(selected[-3]['timestamp']) <= _utc(metadata['timestamp']),
            'TOOL_EXACT_SINGLE_READ_AND_ORDER_REQUIRED')
        submission, read = value['submission'], value['objective_read']
        require(type(submission) is list and len(submission) == 2 and type(submission[0]) is int
            and submission[0] == 202 and submission[1].get('id') == task
            and canonical(submission[1].get('steps')) == canonical([{'capability': CAPABILITY_ID, 'dispatch': dispatch}]),
            'TOOL_OBJECTIVE_SUBMISSION_UNBOUND')
        require(type(read) is list and len(read) == 2 and type(read[0]) is int and read[0] == 200
            and type(read[1]) is dict, 'TOOL_OBJECTIVE_READ_REQUIRED')
        objective, immutable = read[1], read[1].get('execution_metadata')
        require(objective.get('id') == task and type(objective.get('revision')) is int and objective['revision'] == 0
            and objective.get('state') == 'COMPLETED' and canonical(objective.get('steps')) == canonical([
                {'capability': CAPABILITY_ID, 'dispatch': dispatch, 'revision': 0, 'state': 'completed'}]),
            'TOOL_OBJECTIVE_READ_UNBOUND')
        from .objective_api import inference_attempt_projection
        require(type(immutable) is dict and immutable.get('schema_version') == 'jarvis.authoritative-execution.v1'
            and immutable.get('authoritative') is True and immutable.get('task_id') == task
            and type(immutable.get('revision')) is int and immutable['revision'] == 0
            and immutable.get('state') == 'COMPLETED' and canonical(immutable.get('runtime')) == canonical(runtime)
            and canonical(immutable.get('jobs')) == b'[]' and canonical(immutable.get('agent_execution')) == b'[]'
            and canonical(immutable.get('inference_attempts')) == canonical(inference_attempt_projection([]))
            and immutable.get('model_content_is_authoritative_metadata') is False
            and immutable.get('provenance', {}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME'
            and _utc(observation['started_at']) <= _utc(immutable.get('created_at')) <= began
            and _utc(selected[-1]['timestamp']) <= _utc(immutable.get('completed_at')) <=
                _utc(immutable.get('updated_at')) <= _utc(observation['completed_at']), 'TOOL_IMMUTABLE_OBJECTIVE_UNBOUND')
        return dict(task_id=task, case=case, artifact_id=metadata['artifact_id'], result_sha256=sha(raw),
            case_spec_sha256=sha(canonical(fixed)), runtime=runtime, registry_sha256=registry_sha256,
            subject_action_sha256=parse(spans[1][-1].encode())['sha256'],
            input_action_sha256=parse(spans[0][-1].encode())['sha256'],
            **({'failed_read_action_sha256':failed['last_sha256']} if failed is not None else {}),
            **({'available_read_action_sha256': available['last_sha256'], 'available_source_sha256': available['source_sha256']}
                if case in AVAILABLE_CASES else {}),
            original_action_span_sha256=sha(''.join(value['original_action_records']).encode()),
            execution_metadata_sha256=sha(canonical(immutable)), certification='UNVERIFIED',
            event_verification='JOIN_VALIDATED_ORIGIN_AND_INDEPENDENT_ACCEPTANCE_REQUIRED')
    except ToolEventError:
        raise
    except Exception:
        raise ToolEventError('TOOL_EVENT_REJECTED') from None
