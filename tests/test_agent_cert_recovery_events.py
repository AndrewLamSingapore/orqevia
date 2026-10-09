"""Actual temporary artifact custody and fake HTTP; not live/signature/L7 proof."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import uuid

import pytest

from app import agent_cert_artifact_events as events
from app import agent_cert_role_review as contracts
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span
from scripts import agent_cert_operator_io as binding
from tests.test_agent_cert_artifact_paths import operator, collect, rejected_review_has_no_new_effect
from tests.test_agent_cert_artifact_events import domain, execute_and_collect
from tests.test_agent_cert_review_dispatch import configured, SOURCE
from tests.test_agent_cert_operator_io import FakeResponse, FakeTransport, client, raw


CASE = 'general:recovery'


def test_exact_existing_recovery_scope_has_owned_zero_model_adapter():
    spec = contracts.canonical_case_spec('a19', 'responsibility.a19', CASE)
    assert spec == events.canonical_artifact_case(CASE)
    assert spec['request']['max_cost_usd'] == 0.0
    assert spec['request']['preferred_provider'] is None
    assert spec['request']['deterministic_operation'] == events.OPERATION
    assert spec['certification'] == 'UNVERIFIED'


def fake_transport(operator):
    subject_task = [None]
    def handler(method, path, body):
        if path == binding.RUNTIME_PATH:
            return FakeResponse(body=raw(operator.runtime()))
        if path == '/api/agents/objectives':
            status, reply = operator.submit(json.loads(body))
            subject_task[0] = reply['id']
            return FakeResponse(status, raw(reply))
        if path == '/api/agents/dispatch':
            status, reply = operator.reviewer(json.loads(body))
            return FakeResponse(status, raw(reply))
        if path.startswith('/api/agents/objectives/'):
            status, reply = operator.objective(path.rsplit('/', 1)[1])
            return FakeResponse(status, raw(reply))
        if path.startswith('/api/artifacts/'):
            status, original, digest = operator.artifact(path.rsplit('/', 1)[1])
            return FakeResponse(status, original, {'X-Artifact-SHA256': digest})
        task = path.split('/actions/')[1].split('?')[0]
        action = path.split('?action_type=')[1]
        lines = operator.subject_actions(task, action) if task == subject_task[0] else operator.reviewer_actions(operator.review['review_action_id'])
        return FakeResponse(body=raw(dict(schema='prime.original-action-span.v1', task_id=task,
            action_type=action, source_revision=SOURCE, original_lines=lines)))
    return FakeTransport(handler)


def test_actual_three_artifact_recovery_and_distinct_a26_through_bounded_http(operator, monkeypatch):
    original_review, original_retrieve = operator.reviewer, ArtifactFactory.retrieve
    reviewing, retrieved = [], []
    def retrieve(factory, identifier):
        if reviewing:
            retrieved.append(identifier)
        return original_retrieve(factory, identifier)
    def reviewer(request):
        reviewing.append(True)
        try:
            return original_review(request)
        finally:
            reviewing.clear()
    monkeypatch.setattr(ArtifactFactory, 'retrieve', retrieve)
    monkeypatch.setattr(operator, 'reviewer', reviewer)
    transport = fake_transport(operator)
    item = client(transport, spec=events.canonical_artifact_case(CASE))
    result = collect(operator, CASE, io=item.io(), actions=item.read_subject_actions)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['artifact_event']
    prior = json.loads(result.prior_artifact_bytes)
    correction = json.loads(result.input_artifact_bytes)
    revised = json.loads(result.subject_artifact_bytes)
    assert prior['assessment']['failures'] == 3 and prior['assessment']['checks'] == 20
    assert prior['assessment']['failure_basis_points'] == 1500
    assert revised['assessment']['failures'] == 1 and revised['assessment']['checks'] == 20
    assert revised['assessment']['failure_basis_points'] == 500
    assert prior['assessment_revision'] == 0 and revised['assessment_revision'] == 1
    assert execution['objective_read'][1]['revision'] == 0
    assert execution['objective_read'][1]['execution_metadata']['revision'] == 0
    expected_ref = {'task_id': event['task_id'],
        'artifact_id': event['prior_artifact_metadata']['artifact_id'],
        'sha256': event['prior_artifact_metadata']['sha256']}
    assert correction['correction_of'] == revised['original_assessment_ref'] == expected_ref
    assert revised['correction_ref']['sha256'] == events.sha(result.input_artifact_bytes)
    assert len(result.prior_actions) == len(result.input_actions) == len(result.subject_actions) == 2
    for metadata in (event['prior_artifact_metadata'], event['input_artifact_metadata'], execution['artifact_metadata']):
        assert retrieved.count(metadata['artifact_id']) >= 2
    for assessment in (prior['assessment'], revised['assessment']):
        assert assessment['continuous_health_proven'] is False
        assert assessment['cause_known'] is False and assessment['restart_authorized'] is False
    assert revised['assessment']['recovery_proven'] is False
    review = json.loads(result.reviewer_artifact_bytes)
    assert review['reviewer_id'] == 'a26' and review['task_id'] != event['task_id']
    assert result.summary['signature'] == 'NOT_PERFORMED'
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert len(item.original_replies()) == len(transport.calls) == item._response_limit == 26
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 2
    assert all(connection.closed and connection.response.closed for connection in transport.connections)


def test_existing_24_reply_bound_is_insufficient_only_for_the_two_new_original_gets(operator):
    transport = fake_transport(operator)
    item = client(transport, spec=events.canonical_artifact_case(CASE))
    item._response_limit = 24  # Negative discriminator, not a production override.
    result = collect(operator, CASE, io=item.io(), actions=item.read_subject_actions)
    assert result.summary['state'] == 'REJECTED'
    assert len(item.original_replies()) == len(transport.calls) == 24
    assert result.prior_artifact_bytes is not None and result.prior_actions
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 2


@pytest.mark.parametrize('defect', ['result_arithmetic', 'prior_arithmetic', 'corrected_denominator',
    'restart', 'continuous_health', 'recovery_claim', 'wrong_correction_origin', 'bool_assessment_revision'])
def test_independent_oracle_rejects_shared_generator_defect_before_a26_dispatch(operator, monkeypatch, defect):
    helper = ('prior_assessment_bytes' if defect == 'prior_arithmetic' else
        'correction_bytes' if defect in {'corrected_denominator', 'wrong_correction_origin'} else '_recovery_result_bytes')
    original = getattr(events, helper)
    def broken(*args, **kwargs):
        value = json.loads(original(*args, **kwargs))
        if defect == 'corrected_denominator':
            value['corrected_observation']['checks'] = 10
        elif defect == 'wrong_correction_origin':
            value['correction_of']['artifact_id'] = 'f' * 32
        elif defect == 'bool_assessment_revision':
            value['assessment_revision'] = True
        elif defect in {'result_arithmetic', 'prior_arithmetic'}:
            value['assessment']['failure_basis_points'] += 100
        else:
            value['assessment'][{'restart': 'restart_authorized', 'continuous_health': 'continuous_health_proven',
                'recovery_claim': 'recovery_proven'}[defect]] = True
        return events.canonical(value)
    monkeypatch.setattr(events, helper, broken)
    result = collect(operator, CASE)
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.prior_artifact_bytes and result.input_artifact_bytes and result.subject_artifact_bytes
    execution = json.loads(result.execution_bytes)
    with pytest.raises(events.ArtifactEventError, match='RECOVERY_'):
        events.validate_artifact_execution(execution, source_revision=SOURCE,
            runtime_image_id=execution['runtime']['image_digest'], registry_sha256=operator.registry_sha,
            now=events._utc(execution['observation']['completed_at']))


@pytest.mark.parametrize('defect', ['missing_prior', 'wrong_prior_task', 'wrong_prior_hash', 'missing_prior_actions',
    'missing_prior_chain', 'wrong_prior_action', 'gapped_sequence', 'reordered_pairs',
    'original_revision', 'bool_objective_revision', 'wrong_source', 'stale'])
def test_original_revision_zero_three_artifact_custody_and_order_fail_closed(domain, defect):
    execution, pins = execute_and_collect(domain, CASE)
    event = execution['dispatch']['artifact_event']
    if defect == 'missing_prior':
        execution['prior_artifact_content_utf8'] = None
    elif defect == 'wrong_prior_task':
        event['prior_artifact_metadata']['task_id'] = str(uuid.uuid4())
    elif defect == 'wrong_prior_hash':
        event['prior_artifact_metadata']['sha256'] = 'f' * 64
    elif defect == 'missing_prior_actions':
        execution['prior_action_records'] = []
    elif defect == 'missing_prior_chain':
        execution['prior_action_chain_join'] = None
    elif defect == 'wrong_prior_action':
        event['prior_action_id'] = event['input_action_id']
    elif defect == 'gapped_sequence':
        execution['prior_action_chain_join']['last_sequence'] += 1
    elif defect == 'reordered_pairs':
        execution['prior_action_records'], execution['input_action_records'] = (
            execution['input_action_records'], execution['prior_action_records'])
    elif defect in {'original_revision', 'bool_objective_revision'}:
        execution['objective_read'][1]['revision'] = 1 if defect == 'original_revision' else False
    elif defect == 'wrong_source':
        execution['runtime_current']['source_revision'] = 'f' * 40
    elif defect == 'stale':
        pins['now'] += timedelta(minutes=6)
    with pytest.raises(events.ArtifactEventError):
        events.validate_artifact_execution(execution, **pins)


def test_strict_timestamp_inversion_not_equal_clock_is_rejected(domain):
    execution, pins = execute_and_collect(domain, CASE)
    first_correction = events._utc(json.loads(execution['input_action_records'][0])['timestamp'])
    execution['dispatch']['artifact_event']['prior_artifact_metadata']['timestamp'] = (
        first_correction + timedelta(microseconds=1)).isoformat()
    with pytest.raises(events.ArtifactEventError):
        events.validate_artifact_execution(execution, **pins)


def test_coherently_rehashed_substitute_prior_is_not_owning_provenance(operator):
    assert collect(operator, CASE).summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    request = deepcopy(operator.review_request)
    envelope = json.loads(request['context'])
    execution = envelope['execution']
    event = execution['dispatch']['artifact_event']
    event['prior_artifact_metadata']['artifact_id'] = uuid.uuid4().hex
    correction_raw = events.correction_bytes(event['task_id'], event['prior_artifact_metadata'])
    execution['input_content_utf8'] = correction_raw.decode()
    event['input_artifact_metadata'].update(sha256=events.sha(correction_raw), bytes=len(correction_raw))
    result_raw = events.expected_artifact_bytes(CASE, task_id=event['task_id'],
        prior_artifact=event['prior_artifact_metadata'], input_artifact=event['input_artifact_metadata'])
    execution['artifact_content_utf8'] = result_raw.decode()
    execution['artifact_metadata'].update(sha256=events.sha(result_raw), bytes=len(result_raw))
    execution['dispatch']['artifact'] = deepcopy(execution['artifact_metadata'])
    previous = json.loads(execution['prior_action_records'][0])['previous_sha256']
    for records, chain, metadata, action_type, schema, action_id in (
        ('prior_action_records', 'prior_action_chain_join', event['prior_artifact_metadata'],
            events.artifact_action_type(CASE, prior=True), events.RESULT_SCHEMA, event['prior_action_id']),
        ('input_action_records', 'input_action_chain_join', event['input_artifact_metadata'],
            events.artifact_action_type(CASE, setup=True), events.INPUT_SCHEMA, event['input_action_id']),
        ('action_records', 'action_chain_join', execution['artifact_metadata'],
            events.artifact_action_type(CASE), events.RESULT_SCHEMA, event['subject_action_id'])):
        rewritten = []
        for line in execution[records]:
            record = json.loads(line)
            if record['phase'] == 'completed':
                record['result_summary'].update(artifact_id=metadata['artifact_id'], sha256=metadata['sha256'])
            record['previous_sha256'] = previous
            record['sha256'] = events.sha(events.canonical({k: v for k, v in record.items() if k != 'sha256'}))
            previous = record['sha256']
            rewritten.append(json.dumps(record, sort_keys=True) + '\n')
        execution[records] = rewritten
        execution[chain] = action_span(rewritten, task_id=event['task_id'], agent_id='a19', action_type=action_type,
            schema=schema, metadata=metadata, began=events._utc(event['started_at']),
            ended=events._utc(event['completed_at']), action_id=action_id)
    execution['submission'][1]['steps'][0]['dispatch'] = deepcopy(execution['dispatch'])
    execution['objective_read'][1]['steps'][0]['dispatch'] = deepcopy(execution['dispatch'])
    assert events.validate_artifact_execution(execution, source_revision=SOURCE,
        runtime_image_id=execution['runtime']['image_digest'], registry_sha256=operator.registry_sha,
        now=events._utc(execution['observation']['completed_at']))['certification'] == 'UNVERIFIED'
    envelope['expected_execution_sha256'] = events.sha(events.canonical(execution))
    request['context'] = events.canonical(envelope).decode()
    rejected_review_has_no_new_effect(operator, request)


@pytest.mark.parametrize('target', ['prior', 'correction', 'result', 'prior_actions'])
def test_actual_owning_domains_rechecked_after_final_objective_read(operator, monkeypatch, target):
    assert collect(operator, CASE).summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(operator.review_request['context'])['execution']
    original = operator.objectives.get_read_only
    reads = []
    def read(task, authorization):
        reply = original(task, authorization)
        reads.append(task)
        if len(reads) == 2:
            if target == 'prior_actions':
                path = operator.ledger.path
                content = path.read_bytes()
                changed = content.replace(b'"phase": "completed"', b'"phase": "tampered"', 1)
                assert changed != content
                path.write_bytes(changed)
            else:
                event = execution['dispatch']['artifact_event']
                metadata = (event['prior_artifact_metadata'] if target == 'prior' else
                    event['input_artifact_metadata'] if target == 'correction' else execution['artifact_metadata'])
                path = operator.root / 'artifacts' / metadata['artifact_id'] / 'artifact.json'
                path.write_bytes(path.read_bytes() + b' ')
        return reply
    monkeypatch.setattr(operator.objectives, 'get_read_only', read)
    rejected_review_has_no_new_effect(operator, operator.review_request)
    assert len(reads) == 2


def test_original_assessment_is_not_overwritten_or_a_prose_recovery_claim(operator):
    result = collect(operator, CASE)
    execution = json.loads(result.execution_bytes)
    prior_metadata = execution['dispatch']['artifact_event']['prior_artifact_metadata']
    actual_metadata, actual_raw = ArtifactFactory(operator.root / 'artifacts').retrieve(prior_metadata['artifact_id'])
    assert actual_metadata == prior_metadata and actual_raw == result.prior_artifact_bytes
    assert contracts.review_case_output('a19', 'responsibility.a19', CASE,
        result.subject_artifact_bytes.decode()) == (False, ('artifact_event_evidence_required',))
    assert result.prior_artifact_bytes.decode() not in repr(result)


@pytest.mark.parametrize('case', ['recovery:complete', 'handoff_recovery:agent_failure', 'tool_recovery:tool_failure'])
def test_new_general_recovery_does_not_claim_other_recovery_contracts(case):
    with pytest.raises(events.ArtifactEventError):
        events.canonical_artifact_case(case)
    with pytest.raises(events.ArtifactEventError):
        events.artifact_action_type('general:handoff', prior=True)


def test_missing_distinct_actual_a26_receipt_cannot_be_recovery_evidence(operator):
    result = collect(operator, CASE, io=replace(operator.io(),
        dispatch_reviewer=lambda request: (202, {'state': 'COMPLETED', 'recovery_proven': True})))
    assert result.summary['state'] == 'REJECTED'
    assert result.prior_artifact_bytes and result.input_artifact_bytes and result.subject_artifact_bytes
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
