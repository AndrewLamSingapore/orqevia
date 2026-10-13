"""Original temporary-domain handoff custody; not live/signature/L7 proof."""
from copy import deepcopy
from dataclasses import replace
import json
import uuid

import pytest

from app import agent_cert_artifact_events as events
from app import agent_cert_role_review as contracts
from app.handoff import validate_handoff
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import action_span
from tests.test_agent_cert_artifact_paths import operator, collect, rejected_review_has_no_new_effect
from tests.test_agent_cert_review_dispatch import configured


CASE = 'general:handoff'


def test_handoff_has_exact_owned_zero_model_adapter_and_registered_recipient():
    spec = contracts.canonical_case_spec('a19', 'responsibility.a19', CASE)
    assert spec == events.canonical_artifact_case(CASE)
    assert spec['request']['deterministic_operation'] == events.OPERATION
    assert spec['request']['max_cost_usd'] == 0.0
    assert spec['request']['preferred_provider'] is None
    assert spec['certification'] == 'UNVERIFIED'


def test_actual_handoff_packet_and_separate_registered_a26_review(operator, monkeypatch):
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
    result = collect(operator, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = json.loads(result.execution_bytes)
    event = execution['dispatch']['artifact_event']
    packet = json.loads(result.subject_artifact_bytes)['assessment']
    assert validate_handoff(packet) == packet
    assert packet['schema_version'] == '1.1'
    assert packet['task_id'] == result.summary['subject_task_id']
    assert packet['artifact_refs'] == [event['input_artifact_metadata']['artifact_id']]
    assert packet['evidence_refs'] == [event['input_artifact_metadata']['sha256']]
    assert 'REGISTERED_RECIPIENT:a26/responsibility.a26' in packet['constraints']
    assert 'ADVISORY_ONLY_NO_DELEGATION_OR_AUTHORITY_TRANSFER' in packet['constraints']
    assert packet['changed_state'] == ['ONLY_ORIGINAL_INPUT_AND_HANDOFF_ARTIFACTS_PERSISTED',
        'NO_PROVIDER_SERVICE_OR_PRODUCTION_CONFIGURATION_CHANGED']
    assert packet['open_questions'] and packet['acceptance_criteria']
    assert len(result.input_actions) == len(result.subject_actions) == len(result.reviewer_actions) == 2
    assert retrieved.count(event['input_artifact_metadata']['artifact_id']) >= 2
    assert retrieved.count(execution['artifact_metadata']['artifact_id']) >= 2
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    review = json.loads(result.reviewer_artifact_bytes)
    assert review['reviewer_id'] == 'a26' and review['reviewer_capability_id'] == 'responsibility.a26'
    assert review['task_id'] != packet['task_id']
    assert review['subject_domain_join']['artifact_id'] == execution['artifact_metadata']['artifact_id']
    assert result.summary['signature'] == 'NOT_PERFORMED'


def test_fully_rehashed_substitute_origin_passes_shape_but_not_actual_owning_review(operator):
    assert collect(operator, CASE).summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    request = deepcopy(operator.review_request)
    envelope = json.loads(request['context'])
    execution = envelope['execution']
    event = execution['dispatch']['artifact_event']
    input_metadata = event['input_artifact_metadata']
    input_metadata['artifact_id'] = uuid.uuid4().hex  # Not in the actual owning store.
    raw = events.expected_artifact_bytes(CASE, task_id=event['task_id'], input_artifact=input_metadata)
    execution['artifact_content_utf8'] = raw.decode()
    execution['artifact_metadata'].update(sha256=events.sha(raw), bytes=len(raw))
    execution['dispatch']['artifact'] = deepcopy(execution['artifact_metadata'])
    previous = json.loads(execution['input_action_records'][0])['previous_sha256']
    for key, metadata in [('input_action_records', input_metadata),
            ('action_records', execution['artifact_metadata'])]:
        rewritten = []
        for line in execution[key]:
            record = json.loads(line)
            if record['phase'] == 'completed':
                record['result_summary'].update(artifact_id=metadata['artifact_id'], sha256=metadata['sha256'])
            record['previous_sha256'] = previous
            record['sha256'] = events.sha(events.canonical({k: v for k, v in record.items() if k != 'sha256'}))
            previous = record['sha256']
            rewritten.append(json.dumps(record, sort_keys=True) + '\n')
        execution[key] = rewritten
    for setup, key, metadata in [(True, 'input', input_metadata), (False, '', execution['artifact_metadata'])]:
        records = 'input_action_records' if setup else 'action_records'
        chain = 'input_action_chain_join' if setup else 'action_chain_join'
        execution[chain] = action_span(execution[records], task_id=event['task_id'], agent_id='a19',
            action_type=events.artifact_action_type(CASE, setup=setup),
            schema=events.INPUT_SCHEMA if setup else events.RESULT_SCHEMA, metadata=metadata,
            began=events._utc(event['started_at']), ended=events._utc(event['completed_at']),
            action_id=event['input_action_id'] if setup else event['subject_action_id'])
    execution['submission'][1]['steps'][0]['dispatch'] = deepcopy(execution['dispatch'])
    execution['objective_read'][1]['steps'][0]['dispatch'] = deepcopy(execution['dispatch'])
    pins = dict(source_revision=execution['runtime']['source_revision'],
        runtime_image_id=execution['runtime']['image_digest'], registry_sha256=operator.registry_sha,
        now=events._utc(execution['observation']['completed_at']))
    # This deliberately demonstrates why a valid submitted hash chain is not
    # provenance: only the separate current owning-domain reads are decisive.
    assert events.validate_artifact_execution(execution, **pins)['certification'] == 'UNVERIFIED'
    envelope['expected_execution_sha256'] = events.sha(events.canonical(execution))
    request['context'] = events.canonical(envelope).decode()
    rejected_review_has_no_new_effect(operator, request)


@pytest.mark.parametrize('binding', ['task', 'input'])
def test_handoff_expected_bytes_cannot_fabricate_dynamic_origin(binding):
    options = dict(task_id=str(uuid.uuid4()), input_artifact={})
    options['task_id' if binding == 'task' else 'input_artifact'] = None
    with pytest.raises(events.ArtifactEventError):
        events.expected_artifact_bytes(CASE, **options)


@pytest.mark.parametrize('field,value', [('agent_id', 'a26'), ('capability_id', 'responsibility.a26')])
def test_handoff_does_not_grant_peer_or_secondary_capability(field, value):
    with pytest.raises(events.ArtifactEventError):
        events.canonical_artifact_case(CASE, **{field: value})


def test_handoff_never_accepts_prose_as_delivery_or_review():
    assert contracts.review_case_output('a19', 'responsibility.a19', CASE,
        '{"delivered":true,"recipient":"a26","status":"PASS"}') == (
            False, ('artifact_event_evidence_required',))


@pytest.mark.parametrize('field,value', [('schema_version', '1.0'),
    ('task_id', 'syntactically-valid-but-not-owned'), ('artifact_refs', ['0' * 32]),
    ('evidence_refs', ['0' * 64]), ('constraints', ['AUTHORITY_TRANSFERRED_TO_A26']),
    ('facts', ['raw history not present in the input']), ('results', ['RECOVERY_PROVEN']),
    ('open_questions', []), ('acceptance_criteria', []), ('recipient', 'a27')])
def test_substituted_packet_even_with_rehashed_metadata_is_rejected_before_new_review(operator, field, value):
    assert collect(operator, CASE).summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    request = deepcopy(operator.review_request)
    envelope = json.loads(request['context'])
    execution = envelope['execution']
    content = json.loads(execution['artifact_content_utf8'])
    content['assessment'][field] = value
    raw = events.canonical(content)
    execution['artifact_content_utf8'] = raw.decode()
    for metadata in (execution['artifact_metadata'], execution['dispatch']['artifact']):
        metadata['sha256'], metadata['bytes'] = events.sha(raw), len(raw)
    envelope['expected_execution_sha256'] = events.sha(events.canonical(execution))
    request['context'] = events.canonical(envelope).decode()
    rejected_review_has_no_new_effect(operator, request)


def test_handoff_claim_without_actual_distinct_registered_review_is_not_collected(operator):
    result = collect(operator, CASE, io=replace(operator.io(),
        dispatch_reviewer=lambda request: (202, {'delivered': True, 'reviewer_id': 'a26'})))
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.subject_artifact_bytes is not None and result.reviewer_artifact_bytes is None
    assert result.summary['signature'] == 'NOT_PERFORMED'
