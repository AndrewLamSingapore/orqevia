"""Original temporary-domain path integration; never live, signed or L7 proof."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from app import agent_cert_artifact_events as events
from app import agent_cert_event_api as api
from app import agent_cert_role_review as contracts
from app import agent_dispatch_api as dispatch
from scripts.collect_agent_cert_event import collect_event_case
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE
from tests.test_collect_agent_cert_event import TemporaryOperator


class ArtifactOperator(TemporaryOperator):
    def submit(self, request):
        reply = super().submit(request)
        self.subject_reply = deepcopy(reply[1])
        return reply

    def subject_actions(self, task, action):
        self.calls.append('subject_actions')
        return api.actions(task, Response(), action_type=action,
            authorization='fixture-owner')['original_lines']

    def reviewer_actions(self, action):
        self.calls.append('review_actions')
        assert action == self.review['review_action_id']
        return api.actions(self.review['task_id'], Response(),
            action_type=contracts.ARTIFACT_REVIEW_ACTION,
            authorization='fixture-owner')['original_lines']

    def reviewer(self, request):
        self.review_request = deepcopy(request)
        return super().reviewer(request)


@pytest.fixture
def operator(configured, monkeypatch):
    value = ArtifactOperator(configured, monkeypatch)
    monkeypatch.setattr(api, 'authenticate_owner', dispatch.authenticate_owner)
    yield value
    assert value.ledger.close()


def collect(operator, case, *, io=None, actions=None, **changes):
    options = dict(io=io or operator.io(),
        read_subject_actions=actions or operator.subject_actions,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        expected_registry_sha256=operator.registry_sha,
        reviewer_code_revision='f' * 40, review_run_id='temporary-artifact-review',
        timeout_seconds=10, nonce_factory=lambda: NONCE)
    options.update(changes)
    return collect_event_case(events.canonical_artifact_case(case), **options)


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_original_event_through_existing_objective_dispatch_api_and_distinct_review(operator, case):
    result = collect(operator, case)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['certification'] == 'UNVERIFIED'
    assert result.summary['signature'] == 'NOT_PERFORMED'
    execution, review = json.loads(result.execution_bytes), json.loads(result.review_bytes)
    assert set(execution['observation']) == {'started_at', 'completed_at'}
    assert execution['runtime'] == execution['runtime_after'] == execution['runtime_current']
    assert execution['dispatch']['artifact_event']['case'] == case
    assert result.subject_artifact_bytes == events.expected_artifact_bytes(case)
    assert review['dimension'] == 'general' and review['test_case'] == case.split(':')[1]
    assert review['review_test_version'] == events.ORACLE_ID
    content = json.loads(result.reviewer_artifact_bytes)
    assert content['schema_version'] == contracts.ARTIFACT_REVIEW_SCHEMA
    assert content['subject_domain_join']['completed_at'] == execution['dispatch']['artifact_event']['completed_at']
    assert len(result.subject_actions) == len(result.reviewer_actions) == 2
    if case == 'general:artifact_produce':
        assert result.input_artifact_bytes is None and result.input_actions == ()
        assert execution['input_action_records'] == []
    else:
        assert len(result.input_actions) == 2 and result.input_artifact_bytes is not None
        assert result.input_artifact_bytes.decode() == execution['input_content_utf8']
        assert execution['input_action_chain_join']['last_sequence'] + 1 == execution['action_chain_join']['first_sequence']
    assert result.subject_artifact_bytes.decode() not in repr(result)
    assert result.reviewer_artifact_bytes.decode() not in repr(result)


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_source_owned_case_does_not_accept_generic_text_as_an_event(case):
    assert contracts.canonical_case_spec('a19', 'responsibility.a19', case) == events.canonical_artifact_case(case)
    assert contracts.review_case_output('a19', 'responsibility.a19', case,
        events.expected_artifact_bytes(case).decode()) == (False, ('artifact_event_evidence_required',))


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_direct_dispatch_without_original_owning_objective_has_no_artifact_or_action(operator, case):
    before = operator.ledger.status()['persisted']
    with pytest.raises(HTTPException) as error:
        dispatch.dispatch_request(dispatch.AgentRequest(**events.canonical_artifact_case(case)['request']), 'fixture-owner')
    assert error.value.status_code == 422
    assert not (operator.root / 'artifacts').exists()
    assert operator.ledger.status()['persisted'] == before


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_unauthorized_subject_dispatch_does_not_invoke_producer(operator, monkeypatch, case):
    monkeypatch.setattr(events, 'execute_artifact_case', lambda *a, **k: pytest.fail('Unauthorized producer'))
    with pytest.raises(HTTPException) as error:
        dispatch.dispatch_request(dispatch.AgentRequest(**events.canonical_artifact_case(case)['request']), 'wrong-owner')
    assert error.value.status_code == 401
    assert not (operator.root / 'artifacts').exists()


@pytest.mark.parametrize('case', ('general:artifact_consume', 'general:review'))
def test_late_original_input_bytes_are_retained_without_review_or_retry(operator, case):
    clock = type('Clock', (), {'value': 0.0})()
    def read(identifier):
        reply = operator.artifact(identifier)
        metadata = operator.subject_reply['steps'][0]['dispatch']['artifact_event']['input_artifact_metadata']
        if identifier == metadata['artifact_id']:
            clock.value = 11.0
        return reply
    result = collect(operator, case, io=replace(operator.io(), read_artifact=read),
        monotonic=lambda: clock.value)
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.input_artifact_bytes is not None
    assert result.summary['signature'] == 'NOT_PERFORMED'


@pytest.mark.parametrize('case', ('general:artifact_consume', 'general:review'))
def test_late_original_setup_actions_are_retained_without_review_or_retry(operator, case):
    clock = type('Clock', (), {'value': 0.0})()
    def read(task, action):
        lines = operator.subject_actions(task, action)
        if action == events.artifact_action_type(case, setup=True):
            clock.value = 11.0
        return lines
    result = collect(operator, case, actions=read, monotonic=lambda: clock.value)
    assert result.summary['state'] == 'REJECTED'
    assert len(result.input_actions) == 2
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_result_tamper_rejected_before_independent_review_and_never_retried(operator, case):
    def read(identifier):
        status, raw, digest = operator.artifact(identifier)
        return status, raw + b' ', digest
    result = collect(operator, case, io=replace(operator.io(), read_artifact=read))
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.subject_artifact_bytes is not None


@pytest.mark.parametrize('case', events.SUPPORTED_CASES)
def test_failed_action_persistence_does_not_collect_or_review(operator, monkeypatch, case):
    original_flush = operator.ledger.flush
    monkeypatch.setattr(operator.ledger, 'flush', lambda **k: False)
    try:
        result = collect(operator, case)
    finally:
        monkeypatch.setattr(operator.ledger, 'flush', original_flush)
    assert result.summary['state'] == 'REJECTED'
    assert operator.calls.count('submit') == 1 and operator.calls.count('review') == 0
    assert result.summary['signature'] == 'NOT_PERFORMED'


def rejected_review_has_no_new_effect(operator, request):
    artifact_ids = set((operator.root / 'artifacts').iterdir())
    persisted = operator.ledger.status()['persisted']
    with pytest.raises(HTTPException) as error:
        dispatch.dispatch_request(dispatch.AgentRequest(**request), 'fixture-owner')
    assert error.value.status_code == 422
    assert set((operator.root / 'artifacts').iterdir()) == artifact_ids
    assert operator.ledger.status()['persisted'] == persisted


@pytest.mark.parametrize('field,value', [('minimum_tier', 'MINI'),
    ('task_class', 'planning'), ('response_format', 'text')])
def test_reviewer_requires_fixed_zero_model_policy(operator, field, value):
    assert collect(operator, 'general:artifact_consume').summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    request = deepcopy(operator.review_request)
    request[field] = value
    rejected_review_has_no_new_effect(operator, request)


@pytest.mark.parametrize('domain', ('result', 'input', 'actions'))
def test_original_domains_are_rechecked_after_last_objective_read(operator, monkeypatch, domain):
    assert collect(operator, 'general:artifact_consume').summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    original = operator.objectives.get_read_only
    execution = json.loads(operator.review_request['context'])['execution']
    reads = 0
    def read(task, authorization):
        nonlocal reads
        reply = original(task, authorization)
        reads += 1
        if reads == 2:
            if domain == 'actions':
                path = operator.ledger.path
                raw = path.read_bytes()
                # Change only the fixture's actual persisted original record.
                changed = raw.replace(b'"phase": "completed"', b'"phase": "tampered"', 1)
                assert changed != raw
                path.write_bytes(changed)
            else:
                metadata = (execution['artifact_metadata'] if domain == 'result'
                    else execution['dispatch']['artifact_event']['input_artifact_metadata'])
                path = operator.root / 'artifacts' / metadata['artifact_id'] / 'artifact.json'
                path.write_bytes(path.read_bytes() + b' ')
        return reply
    monkeypatch.setattr(operator.objectives, 'get_read_only', read)
    rejected_review_has_no_new_effect(operator, operator.review_request)
    assert reads == 2


def test_original_artifact_metadata_reparse_point_is_rejected_before_review_write(operator, monkeypatch):
    assert collect(operator, 'general:artifact_produce').summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(operator.review_request['context'])['execution']
    path = operator.root / 'artifacts' / execution['artifact_metadata']['artifact_id'] / 'metadata.json'
    original = Path.lstat
    def lstat(value, *args, **kwargs):
        if value == path:
            return SimpleNamespace(st_file_attributes=0x400)
        return original(value, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    rejected_review_has_no_new_effect(operator, operator.review_request)
