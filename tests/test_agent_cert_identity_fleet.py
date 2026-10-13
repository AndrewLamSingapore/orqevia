"""28 original owned-identity events and independent reviews; never live/L7."""
import copy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_cert_identity_fleet as identity, agent_dispatch_api as dispatch, agent_registry
from app.action_records import ActionLedger
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_identity_review import canonical, sha, utc, action_span
from app.agent_cert_identity_fleet import validate_identity_execution, read_action_span
from app.agent_cert_role_review import canonical_case_spec
from app.artifact_factory import ArtifactFactory
PAIRS = tuple((row['id'], cap) for row in agent_registry.load_agent_registry()['agents']
              for cap in row['capability_requirements'] if row['id'] != 'a19')
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE


def capture(configured, monkeypatch, agent, cap):
    from app import compute_queue_api, objective_api, runtime_status
    monkeypatch.setattr(runtime_status, 'production_health', lambda: pytest.fail('No health probe'))
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model selection'))
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    execution = dict(case_spec=canonical_case_spec(agent, cap, identity.CASE),
                     runtime=objective_api.runtime_snapshot())
    def submit(request):
        reply = objective_api.submit(objective_api.ObjectiveRequest(**request), 'fixture-owner')
        execution['submission'] = [202, reply]
        execution['dispatch'] = reply['steps'][0]['dispatch']
        return execution['dispatch']
    def artifact(key):
        metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(key)
        execution.update(artifact_metadata=metadata, artifact_content_utf8=raw.decode())
        return metadata, raw
    registry_sha = sha(agent_registry.REGISTRY_PATH.read_bytes())
    execution['observation'] = observe_cert_case(execution['case_spec'], dispatch=submit,
        get_job=lambda _: pytest.fail('No job/model request'), get_artifact=artifact,
        get_runtime=objective_api.runtime_snapshot, expected_source_revision=SOURCE,
        expected_registry_sha256=registry_sha, timeout_seconds=5)
    assert execution['observation']['state'] == 'EXECUTED'
    task = execution['dispatch']['task_id']
    execution['objective_read'] = [200, objective_api.get_read_only(task, 'fixture-owner')]
    assert ledger.flush(timeout=1) is True
    execution['action_records'] = read_action_span(ledger.path, task, identity.ACTION_TYPE)
    execution['action_chain_join'] = action_span(execution['action_records'], task_id=task,
        agent_id=agent, action_type=identity.ACTION_TYPE, schema=identity.SCHEMA,
        metadata=execution['artifact_metadata'], began=utc(execution['observation']['captured_at']),
        ended=utc(execution['observation']['completed_at']))
    execution = json.loads(canonical(execution))
    return SimpleNamespace(root=configured.root, ledger=ledger, agent=agent, cap=cap,
        registry_sha=registry_sha, execution=execution, payload=dict(execution=execution,
            expected_execution_sha256=sha(canonical(execution)), expected_source_revision=SOURCE,
            review_nonce=NONCE))


@pytest.fixture
def fleet_event(request, configured, monkeypatch):
    agent, cap = getattr(request, 'param', ('a26', 'responsibility.a25'))
    item = capture(configured, monkeypatch, agent, cap)
    yield item
    item.ledger.close()


def reviewer_request(item, **changes):
    _, cap = identity.identity_reviewer(item.agent, item.cap)
    value = dict(capability=cap, objective=identity.identity_review_objective(item.agent, item.cap),
        context=canonical(item.payload).decode(), priority='low', task_class='classification', response_format='strict_json',
        deterministic_operation='certification_identity_review')
    return dispatch.AgentRequest(**{**value, **changes})


def review(item, **changes):
    return dispatch.dispatch_request(reviewer_request(item, **changes), 'fixture-owner')


@pytest.mark.parametrize('fleet_event', PAIRS, indirect=True)
def test_each_owned_identity_has_original_objective_artifact_actions_and_distinct_review(fleet_event):
    item = fleet_event
    joined = validate_identity_execution(item.execution, source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=item.registry_sha, now=datetime.now(timezone.utc), agent_id=item.agent, capability_id=item.cap)
    result = review(item)
    reviewer, reviewer_cap = identity.identity_reviewer(item.agent, item.cap)
    assert result['agent_id'] == reviewer != item.agent and result['capability'] == reviewer_cap
    assert result['task_id'] != joined['task_id'] and result['review_action_durable'] is True
    assert result['model_calls'] == 0 and result['certification'] == 'UNVERIFIED'
    metadata, raw = ArtifactFactory(item.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    content = json.loads(raw)
    assert content['schema_version'] == identity.REVIEW_SCHEMA
    assert content['subject_domain_join'] == joined and content['oracle_id'] == identity.VERSION
    assert content['subject_agent_id'] == item.agent and content['subject_capability_id'] == item.cap
    assert content['certification'] == 'UNVERIFIED'
    report = json.loads(item.execution['artifact_content_utf8'])
    assert report['identity']['responsibility_owner'] == item.agent
    assert report['scope'] == dict(worker_activation='NOT_ESTABLISHED', health='NOT_MEASURED',
                                   authority_added=False, certification='UNVERIFIED')
    lines = read_action_span(item.ledger.path, result['task_id'], identity.REVIEW_ACTION)
    action_span(lines, task_id=result['task_id'], agent_id=reviewer, action_type=identity.REVIEW_ACTION,
        schema=identity.REVIEW_SCHEMA, metadata=metadata, began=utc(content['reviewed_at']),
        ended=datetime.now(timezone.utc), action_id=result['review_action_id'])
    assert item.execution['objective_read'][1]['execution_metadata']['jobs'] == []
    assert item.execution['objective_read'][1]['steps'][0]['capability'] == item.cap


@pytest.mark.parametrize('change', [
    {'capability': 'responsibility.a26'}, {'capability': 'responsibility.a25'},
    {'objective': dispatch.IDENTITY_REVIEW_OBJECTIVE}, {'task_class': 'coding'},
    {'minimum_tier': 'MINI'}, {'response_format': 'text'}, {'max_cost_usd': 1},
    {'data_classification': 'CLOUD_PERMITTED'}, {'classification': 'R1'},
])
def test_reviewer_cannot_self_review_or_widen_policy(fleet_event, change):
    with pytest.raises(HTTPException) as error:
        review(fleet_event, **change)
    assert error.value.status_code == 422


@pytest.mark.parametrize('path,value', [
    (('runtime', 'source_revision'), 'f'*40),
    (('dispatch', 'agent_id'), 'a19'),
    (('artifact_metadata', 'creator_agents'), ['a19']),
    (('submission',), [200, {}]),
    (('action_records',), []),
    (('objective_read',), [200, {}]),
])
def test_changed_original_evidence_is_rejected(fleet_event, path, value):
    item = fleet_event
    packet = copy.deepcopy(item.execution); cursor = packet
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    item.payload.update(execution=packet, expected_execution_sha256=sha(canonical(packet)))
    with pytest.raises(HTTPException) as error:
        review(item)
    assert error.value.status_code == 422


@pytest.mark.parametrize('change', [
    {'context': '{}'}, {'objective': identity.PREFIX+'a26 / responsibility.a25 fake'},
    {'priority': 'normal'}, {'data_classification': 'CLOUD_PERMITTED'},
    {'minimum_tier': 'MINI'}, {'max_cost_usd': 1}, {'classification': 'R1'},
    {'task_class': 'coding'}, {'response_format': 'text'},
])
def test_subject_prefix_requires_complete_fixed_source_policy(configured, monkeypatch, change):
    from app import compute_queue_api
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model fallback'))
    request = canonical_case_spec('a26', 'responsibility.a25', identity.CASE)['request']
    with pytest.raises(HTTPException) as error:
        dispatch.dispatch_request(dispatch.AgentRequest(**{**request, **change}), 'fixture-owner')
    assert error.value.status_code == 422


def test_legacy_a19_identity_and_agent_request_schema_are_unchanged():
    from app.agent_cert_cases import challenge
    from app.runtime_status import OBJECTIVE
    spec = canonical_case_spec('a19', 'responsibility.a19', identity.CASE)
    assert spec == challenge(identity.CASE) and spec['request']['objective'] == OBJECTIVE
    assert identity.PREFIX not in OBJECTIVE
    with pytest.raises(ValueError):
        identity.canonical_identity_case(agent_id='a19', capability_id='responsibility.a19')
    operations = dispatch.AgentRequest.model_json_schema()['properties']['deterministic_operation']['anyOf'][0]['enum']
    assert 'certification_owned_identity' not in operations


@pytest.mark.parametrize('agent,cap', [('a26', 'responsibility.a19'), ('A26', 'responsibility.a26'),
                                     ('a19', 'responsibility.a26'), ('prime', 'responsibility.a25')])
def test_unowned_or_aliased_identity_is_not_accepted(agent, cap):
    with pytest.raises(ValueError):
        canonical_case_spec(agent, cap, identity.CASE)


def test_model_answer_cannot_replace_identity_event():
    from app.agent_cert_role_review import review_case_output
    assert review_case_output('a26', 'responsibility.a25', identity.CASE, '{"test_result":"PASS"}') == (
        False, ('identity_event_evidence_required',))


def test_latest_objective_read_cannot_conceal_changed_original_artifact(fleet_event, monkeypatch):
    from app import objective_api
    item = fleet_event
    original = objective_api.get_read_only
    calls = []
    def read(task, authorization):
        result = original(task, authorization); calls.append(task)
        if len(calls) == 2:
            artifact = item.root / 'artifacts' / item.execution['artifact_metadata']['artifact_id'] / 'artifact.json'
            artifact.write_bytes(b'{}')
        return result
    monkeypatch.setattr(objective_api, 'get_read_only', read)
    with pytest.raises(HTTPException) as error:
        review(item)
    assert error.value.status_code == 422 and len(calls) == 2


def test_event_collector_selects_fixed_new_contract_and_legacy_remains_distinct():
    from scripts.collect_agent_cert_event import _contract
    new = _contract('a26', 'responsibility.a25', identity.CASE)
    assert new[:6] == (identity.ACTION_TYPE, identity.SCHEMA, identity.REVIEW_SCHEMA,
                      identity.VERSION, identity.identity_review_objective('a26', 'responsibility.a25'),
                      identity.identity_reviewer('a26', 'responsibility.a25'))
    assert _contract('a19', 'responsibility.a19', identity.CASE)[0] == 'runtime.status.artifact'
