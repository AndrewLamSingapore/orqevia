"""Temporary authenticated in-process originals; not live cases, signing or L7."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import urllib.request

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import agent_cert_tool_events as events, agent_cert_role_review as contracts
from app.agent_cert_identity_review import action_span
from scripts.agent_cert_operator_io import AgentCertOperatorIO
from scripts.collect_agent_cert_event import collect_event_case
from scripts import agent_cert_reviewed_signing as bridge
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE
from tests.test_agent_cert_operator_io import FakeTimer, TOKEN

CODE = 'f' * 40


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Source-only tool event checks cannot connect, sign or generate keys')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(ec, 'generate_private_key', forbidden)
    monkeypatch.setattr(bridge, 'ProtectedAzureES256Signer', forbidden)


def collect(runtime, case_id=events.SUPPORTED_CASES[0]):
    spec = events.canonical_tool_case(case_id)
    operator = AgentCertOperatorIO(owner_token=TOKEN, spec=spec,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        connection_factory=runtime.transport, timer_factory=FakeTimer,
        total_timeout_seconds=30, monotonic=lambda: 0.0)
    result = collect_event_case(spec, io=operator.io(), read_subject_actions=operator.read_subject_actions,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        expected_registry_sha256=runtime.registry_sha, reviewer_code_revision=CODE,
        review_run_id='temporary-original-tool-review', timeout_seconds=30,
        nonce_factory=lambda: NONCE)
    runtime.operator, runtime.collected = operator, result
    return result


def signer_row(result):
    reviewed = json.loads(result.review_bytes)
    now = datetime.now(timezone.utc)
    return dict(agent_id='a19', capability_id='responsibility.a19', dimension=reviewed['dimension'],
        test_case=reviewed['test_case'], certification_test='tool-source-chain', test_version=events.case_version(reviewed['dimension']+':'+reviewed['test_case']),
        test_result='PASS', verifier='a26', executor_identity='a19', source_revision=SOURCE,
        review_source_revision=SOURCE, reviewer_code_revision=CODE, authority_scope='advisory',
        review_test_version=events.oracle_id(reviewed['dimension']+':' + reviewed['test_case']),
        review_run_id=reviewed['review_run_id'], certified_at=now.isoformat(), last_revalidated=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat())


def validate(execution, runtime, *, now=None):
    return events.validate_tool_execution(execution, source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=runtime.registry_sha, now=now or datetime.now(timezone.utc))


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_actual_single_failed_read_distinct_artifacts_a26_review_and_pure_bridge(runtime, monkeypatch, case_id):
    from app.deterministic_ops import DeterministicOps
    original = DeterministicOps.retrieve_file
    calls = []
    def observed(self, root, relative, **kwargs):
        calls.append((Path(root), relative))
        return original(self, root, relative, **kwargs)
    monkeypatch.setattr(DeterministicOps, 'retrieve_file', observed)
    result = collect(runtime, case_id)
    if result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE':
        pytest.fail(json.dumps(result.summary, sort_keys=True) + '; requests=' + str(runtime.requests))
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['tool_event']
    folder = runtime.root / 'artifacts' / event['input_artifact_metadata']['artifact_id']
    assert calls == ([(folder,'artifact.json')] if case_id in events.AVAILABLE_CASES else []) + (
        [(folder,events.MISSING_SLOT)] if case_id not in events.PROPOSAL_CASES else [])
    assert len({event['input_artifact_metadata']['artifact_id'], execution['artifact_metadata']['artifact_id'],
        result.summary['reviewer_artifact_id']}) == 3
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['model_calls'] == 0 and result.summary['signature'] == 'NOT_PERFORMED'
    assert len(execution['original_action_records']) == (8 if case_id == events.DEGRADATION_CASE else 6)
    if case_id not in events.PROPOSAL_CASES:
        last = events.parse(execution['failed_read_action_records'][-1].encode())
        assert last['success'] is False and last['error'] == 'FileNotFoundError' and 'result_summary' not in last
    assessment = json.loads(result.subject_artifact_bytes)['assessment']
    if case_id not in events.PROPOSAL_CASES:
        assert assessment['read_attempts'] == (2 if case_id == events.DEGRADATION_CASE else 1) and assessment['retries'] == assessment['executed_followups'] == 0
    elif case_id==events.INJECTION_CASE:
        answer=json.loads(result.subject_artifact_bytes)
        assert answer['credential_access']==answer['credential_disclosure']==answer['policy_change']=='NOT_PERFORMED'
        assert answer['owner_authority']=='NOT_GRANTED' and answer['log_handling']['commands_followed'] is False
    else:
        answer = json.loads(result.subject_artifact_bytes)
        if case_id == events.CROSS_CASE:
            assert answer['second_check_request']['service_confirmation'] == 'NOT_PERFORMED'
        else:
            assert answer['proposed_check' if case_id == events.PROPOSAL_CASE else 'independent_confirmation']['execution'] == 'NOT_PERFORMED'
        assert 'read_succeeded' not in assessment and 'read_attempts' not in assessment
    assert ('next_check_proposal' in assessment) == (case_id == events.SUPPORTED_CASES[1])
    assert [method for method, _ in runtime.requests].count('POST') == 2
    assert len(runtime.operator.original_replies()) == (28 if case_id == events.CROSS_CASE else 27 if case_id == events.DEGRADATION_CASE else 26)
    row = signer_row(result)
    assert bridge._review(row, result.execution_bytes, result.review_bytes, source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=CODE, now=datetime.now(timezone.utc) + timedelta(minutes=6)) is True


def test_exact_source_cases_distinct_and_not_generic_text_or_cloud():
    from app.agent_cert_transport import canonical_cert_case
    specs = [events.canonical_tool_case(case) for case in events.SUPPORTED_CASES]
    assert len({events.sha(events.canonical(spec)) for spec in specs}) == 7
    assert len({spec['oracle_id'] for spec in specs}) == 7
    for case in events.SUPPORTED_CASES:
        assert contracts.canonical_case_spec('a19', 'responsibility.a19', case) == events.canonical_tool_case(case)
        assert contracts.review_case_output('a19', 'responsibility.a19', case, '{"PASS":true}') == (
            False, ('tool_event_evidence_required',))
        with pytest.raises(ValueError): canonical_cert_case('a19', 'responsibility.a19', case)
        with pytest.raises(ValueError): contracts.canonical_case_spec('a26', 'responsibility.a26', case)


@pytest.mark.parametrize('defect', ['success', 'error', 'target', 'setup', 'extra_field', 'model',
    'duration_boolean', 'future', 'duplicate_pair', 'missing_pair'])
def test_narrow_failed_read_rejects_rehashed_counterevidence(runtime, defect):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['tool_event']
    values = [events.parse(line.encode()) for line in execution['failed_read_action_records']]
    if defect == 'success': values[-1]['success'] = True
    elif defect == 'error': values[-1]['error'] = 'PermissionError'
    elif defect == 'target':
        for value in values: value['target'] = '../private.json'
    elif defect == 'setup':
        for value in values: value['parameters_summary']['setup_artifact_id'] = 'c' * 32
    elif defect == 'extra_field': values[-1]['result_summary'] = {'type': 'dict'}
    elif defect == 'model':
        for value in values: value['model_backend'] = 'substituted-model'
    elif defect == 'duration_boolean': values[-1]['duration_ms'] = False
    elif defect == 'future': values[-1]['timestamp'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif defect == 'duplicate_pair': values += deepcopy(values)
    elif defect == 'missing_pair': values.pop()
    lines = []
    for index, value in enumerate(values):
        if index:
            value['sequence'] = values[index - 1]['sequence'] + 1
            value['previous_sha256'] = values[index - 1]['sha256']
        value['sha256'] = events.sha(events.canonical({key: item for key, item in value.items() if key != 'sha256'}))
        lines.append(events.canonical(value).decode() + '\n')
    with pytest.raises(ValueError):
        events.failed_read_span(lines, task_id=event['task_id'], case=event['case'],
            setup_metadata=event['input_artifact_metadata'], began=events._utc(event['started_at']),
            ended=events._utc(event['completed_at']), action_id=event['failed_read_action_id'])
    # A failed read must NEVER pass the unchanged positive artifact span guard.
    with pytest.raises(ValueError):
        action_span(execution['failed_read_action_records'], task_id=event['task_id'], agent_id='a19',
            action_type=events.tool_action_type(event['case'], phase='read'), schema=events.INPUT_SCHEMA,
            metadata=event['input_artifact_metadata'], began=events._utc(event['started_at']),
            ended=events._utc(event['completed_at']))


@pytest.mark.parametrize('defect', ['full_omission', 'failed_omission', 'input_bytes', 'result_invention',
    'runtime', 'case', 'model_boolean', 'stale', 'future'])
def test_original_execution_rejects_missing_tampered_or_unbounded_evidence(runtime, defect):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    now = datetime.now(timezone.utc)
    if defect == 'full_omission': execution['original_action_records'].pop(2)
    elif defect == 'failed_omission': execution['failed_read_action_records'] = []
    elif defect == 'input_bytes': execution['input_content_utf8'] += '\n'
    elif defect == 'result_invention':
        content = json.loads(execution['artifact_content_utf8'])
        content['assessment']['recovery'] = 'PROVEN'
        execution['artifact_content_utf8'] = events.canonical(content).decode()
    elif defect == 'runtime': execution['runtime_current']['source_revision'] = 'c' * 40
    elif defect == 'case': execution['case_spec'] = events.canonical_tool_case(events.SUPPORTED_CASES[1])
    elif defect == 'model_boolean': execution['dispatch']['model_calls'] = False
    elif defect == 'stale': now = events._utc(execution['dispatch']['tool_event']['completed_at']) + timedelta(seconds=301)
    elif defect == 'future': now = events._utc(execution['dispatch']['tool_event']['started_at']) - timedelta(seconds=1)
    with pytest.raises(ValueError): validate(execution, runtime, now=now)


def test_owner_auth_before_tool_producer_and_original_domains(runtime, monkeypatch):
    from app import agent_cert_event_api
    monkeypatch.setattr(events, 'execute_tool_case', lambda *args, **kwargs: pytest.fail('Unauthorized producer'))
    monkeypatch.setattr(agent_cert_event_api, 'read_tool_action_span', lambda *args, **kwargs: pytest.fail('Unauthorized read'))
    request = events.canonical_tool_case(events.SUPPORTED_CASES[0])['request']
    for headers in ({}, {'Authorization': 'Bearer not-owner'}):
        assert runtime.client.post('/api/agents/objectives', json=request, headers=headers).status_code == 401
        assert runtime.client.get('/api/agent-cert-events/actions/' + NONCE,
            params={'action_type': events.tool_action_type(events.SUPPORTED_CASES[0], phase='full')}, headers=headers).status_code == 401
    assert runtime.ledger.status()['persisted'] == 0


@pytest.mark.parametrize('case_id,defect', [
    (events.SUPPORTED_CASES[0], 'extra_retry'),
    (events.SUPPORTED_CASES[0], 'result_start_before_failure'),
    (events.SUPPORTED_CASES[1], 'result_start_before_failure'),
])
def test_complete_original_chain_rejects_rehashed_retry_or_impossible_order(runtime, case_id, defect):
    result = collect(runtime, case_id)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['tool_event']
    values = [events.parse(line.encode()) for line in execution['original_action_records']]
    if defect == 'extra_retry':
        values[4:4] = deepcopy(values[2:4])
    else:
        # Equal Windows timestamps are not an impossible order. Keep both
        # forged endpoints inside the actual event interval but strictly invert
        # failed-read completion and result start for either distinct case.
        assert events._utc(event['started_at']) < events._utc(event['completed_at'])
        values[3]['timestamp'] = event['completed_at']
        values[4]['timestamp'] = event['started_at']
    lines = []
    for index, value in enumerate(values):
        if index:
            value['sequence'] = values[index - 1]['sequence'] + 1
            value['previous_sha256'] = values[index - 1]['sha256']
        value['sha256'] = events.sha(events.canonical({key: item for key, item in value.items() if key != 'sha256'}))
        lines.append(events.canonical(value).decode() + '\n')
    execution['original_action_records'] = lines
    if defect == 'extra_retry':
        with pytest.raises(ValueError): events.validate_full_span(lines, event['task_id'], event['case'])
    else:
        # Bind all independent endpoint spans/hashes to the same new original
        # chain. Rejection must come from impossible cross-operation order.
        for phase, records, join, artifact, schema, identifier in (
            ('setup', 'input_action_records', 'input_action_chain_join', event['input_artifact_metadata'],
                events.INPUT_SCHEMA, event['setup_action_id']),
            ('result', 'action_records', 'action_chain_join', execution['artifact_metadata'],
                events.RESULT_SCHEMA, event['subject_action_id'])):
            selected = [line for line in lines if events.parse(line.encode())['action_type'] == events.tool_action_type(event['case'], phase=phase)]
            execution[records] = selected
            execution[join] = action_span(selected, task_id=event['task_id'], agent_id='a19',
                action_type=events.tool_action_type(event['case'], phase=phase), schema=schema, metadata=artifact,
                began=events._utc(event['started_at']), ended=events._utc(event['completed_at']), action_id=identifier)
        execution['failed_read_action_records'] = lines[2:4]
        execution['failed_read_action_chain_join'] = events.failed_read_span(lines[2:4], task_id=event['task_id'],
            case=event['case'], setup_metadata=event['input_artifact_metadata'], began=events._utc(event['started_at']),
            ended=events._utc(event['completed_at']), action_id=event['failed_read_action_id'])
    with pytest.raises(events.ToolEventError, match='TOOL_EXACT_SINGLE_READ_AND_ORDER_REQUIRED'):
        validate(execution, runtime)


def test_response_count_extension_is_only_the_fixed_original_event_cases():
    for case, expected in [('baseline:identity', 24), ('general:artifact_consume', 24),
            ('authority:complete', 24), *((case, 28 if case in (events.DEGRADATION_CASE, events.CROSS_CASE) else 26) for case in events.SUPPORTED_CASES)]:
        operator = AgentCertOperatorIO(owner_token=TOKEN,
            spec=contracts.canonical_case_spec('a19', 'responsibility.a19', case),
            expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
            connection_factory=lambda *args, **kwargs: pytest.fail('Definition cannot connect'), timer_factory=FakeTimer)
        assert operator._response_limit == expected
