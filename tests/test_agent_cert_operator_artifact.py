"""Bounded HTTP fakes only; not live agent execution or certification."""
import traceback
import ast
from pathlib import Path

import pytest

from app.agent_cert_artifact_events import SUPPORTED_CASES, artifact_action_type
from app.agent_cert_role_review import canonical_case_spec
from scripts.agent_cert_operator_io import OperatorBindingError
from tests.test_agent_cert_operator_io import (
    ARTIFACT, REVIEW, TASK, TOKEN,
    FakeResponse, FakeTransport, client, raw,
)


INPUT_ARTIFACT = 'b' * 32


def test_canonical_ci_selects_every_new_artifact_integration_suite():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'scripts/run_canonical_ci.py').read_text(encoding='utf-8'))
    selected = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'names'
                and node.func.attr in {'append', 'extend'} and len(node.args) == 1):
            value = ast.literal_eval(node.args[0])
            selected.update([value] if node.func.attr == 'append' else value)
    required = {'agent_cert_artifact_paths', 'agent_cert_artifact_signing',
                'agent_cert_artifact_admission', 'agent_cert_operator_artifact', 'agent_cert_handoff_events',
                'agent_cert_recovery_events', 'agent_cert_evidence_integrity_events', 'agent_cert_context_integrity_events'}
    assert required <= selected
    assert all((root / 'tests' / ('test_' + name + '.py')).is_file() for name in required)


def artifact_client(case, transport=None):
    return client(transport, spec=canonical_case_spec('a19', 'responsibility.a19', case))


def subject_reply():
    return FakeResponse(202, raw({'id': TASK, 'steps': [{'dispatch': {
        'artifact': {'artifact_id': ARTIFACT},
        'artifact_event': {'input_artifact_metadata': {'artifact_id': INPUT_ARTIFACT}},
    }}]}))


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_artifact_operator_preparation_is_bounded_and_has_distinct_reviewer(case):
    transport = FakeTransport()
    item = artifact_client(case, transport)
    assert transport.connections == []
    assert (item._reviewer, item._review_cap) == ('a26', 'responsibility.a26')
    assert item._review_operation == 'certification_artifact_review'
    assert item._review_action_type == 'agent.certification.artifact.review'
    assert item._action_type == artifact_action_type(case)
    assert item._response_limit == (26 if case in {'general:recovery', 'evidence_integrity:complete', 'context_integrity:complete'} else 24)
    assert TOKEN not in repr(item)
    with pytest.raises(OperatorBindingError, match='ZERO_MODEL_EVENT_HAS_NO_QUEUE'):
        item.io().read_job(TASK)


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_only_original_subject_response_admits_result_and_applicable_input(case):
    transport = FakeTransport(lambda method, path, body: subject_reply()
        if method == 'POST' else FakeResponse())
    item = artifact_client(case, transport)
    assert not item._allowed_get('/api/artifacts/' + INPUT_ARTIFACT, True)
    item.authorize()
    assert item.submit_objective(item._spec['request'])[0] == 202
    assert item._allowed_get('/api/artifacts/' + ARTIFACT, True)
    needs_input = case != 'general:artifact_produce'
    assert item._allowed_get('/api/artifacts/' + INPUT_ARTIFACT, True) is needs_input
    assert not item._allowed_get('/api/artifacts/' + 'c' * 32, True)
    assert len(item.original_replies()) == 3


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_subject_action_allowlist_never_borrows_other_case_or_task(case):
    item = artifact_client(case)
    item._subject_task = TASK
    path = '/api/agent-cert-events/actions/' + TASK + '?action_type='
    assert item._allowed_get(path + artifact_action_type(case), False)
    if case != 'general:artifact_produce':
        assert item._allowed_get(path + artifact_action_type(case, setup=True), False)
    else:
        assert not item._allowed_get(path + 'agent.certification.artifact.fixture.artifact_consume', False)
    for other in SUPPORTED_CASES:
        if other != case:
            assert not item._allowed_get(path + artifact_action_type(other), False)
    with pytest.raises(OperatorBindingError, match='OWNED_ACTION_BINDING_REQUIRED'):
        item.read_subject_actions(REVIEW, artifact_action_type(case))
    with pytest.raises(OperatorBindingError, match='OWNED_ACTION_BINDING_REQUIRED'):
        item.read_subject_actions(TASK, 'runtime.status.artifact')


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_artifact_review_uses_fixed_independent_action_route(case):
    item = artifact_client(case)
    item._review_task = REVIEW
    fixed = '/api/agent-cert-events/actions/' + REVIEW + '?action_type=agent.certification.artifact.review'
    assert item._allowed_get(fixed, False)
    borrowed = '/api/agent-cert-events/actions/' + REVIEW + '?action_type=agent.certification.'
    assert not item._allowed_get(borrowed + case.split(':')[1] + '.review', False)
    assert not item._allowed_get(fixed.replace(REVIEW, TASK), False)


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_interrupted_artifact_submit_preserves_single_attempt_and_redacts(case):
    def response(method, path, body):
        if method == 'POST':
            raise RuntimeError('private provider detail ' + TOKEN)
        return FakeResponse()
    transport = FakeTransport(response)
    item = artifact_client(case, transport)
    item.authorize()
    for _ in range(2):
        with pytest.raises(OperatorBindingError) as error:
            item.submit_objective(item._spec['request'])
        rendered = ''.join(traceback.format_exception(error.value))
        assert TOKEN not in rendered and 'private provider detail' not in rendered
    assert sum(method == 'POST' for method, _, _ in transport.calls) == 1


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_subject_cannot_request_cloud_or_extra_authority(case):
    transport = FakeTransport()
    item = artifact_client(case, transport)
    for change in ({'capability': 'responsibility.a26'},
                   {'data_classification': 'CLOUD_PERMITTED'},
                   {'max_cost_usd': 0.001}, {'context': 'replacement'},
                   {'deterministic_operation': None}):
        with pytest.raises(OperatorBindingError, match='CANONICAL_ZERO_MODEL_EVENT_REQUIRED'):
            item.submit_objective({**item._spec['request'], **change})
    assert transport.connections == []
