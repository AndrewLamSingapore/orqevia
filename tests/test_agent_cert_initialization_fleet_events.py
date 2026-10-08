"""29 distinct temporary owned events/review/signature paths, never live/L7."""
import copy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_cert_initialization as init, agent_dispatch_api as dispatch, agent_registry
from app.action_records import ActionLedger
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_identity_review import canonical, sha, utc, action_span, read_action_span
from app.agent_cert_initialization_review import validate_initialization_execution
from app.agent_cert_role_review import canonical_case_spec
from app.agent_certification import AgentCertificationRegistry
from app.artifact_factory import ArtifactFactory
from scripts.agent_cert_reviewed_signing import CertificationReviewError, SERVICE, sign_reviewed_case
from tests.test_agent_cert_initialization_fleet import PAIRS
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE
from tests.test_agent_cert_reviewed_signing import fixture as ephemeral_key, REVIEWER_CODE, KEY


def capture(configured, monkeypatch, agent, cap):
    from app import compute_queue_api, objective_api, runtime_status
    monkeypatch.setattr(runtime_status, 'production_health', lambda: pytest.fail('No health probe'))
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model selection'))
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    execution = dict(case_spec=canonical_case_spec(agent, cap, init.CASE),
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
    execution['action_records'] = read_action_span(ledger.path, task, init.ACTION_TYPE)
    execution['action_chain_join'] = action_span(execution['action_records'], task_id=task,
        agent_id=agent, action_type=init.ACTION_TYPE, schema=init.SCHEMA,
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
    _, cap = init.initialization_reviewer(item.agent, item.cap)
    value = dict(capability=cap, objective=init.initialization_review_objective(item.agent, item.cap),
        context=canonical(item.payload).decode(), priority='low', response_format='strict_json',
        deterministic_operation='certification_initialization_review')
    return dispatch.AgentRequest(**{**value, **changes})


def review(item, **changes):
    return dispatch.dispatch_request(reviewer_request(item, **changes), 'fixture-owner')


def signing_input(item, tmp_path):
    result = review(item)
    metadata, raw = ArtifactFactory(item.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    assert metadata == result['artifact']
    content = json.loads(raw); joined = content['subject_domain_join']
    primary = canonical(item.execution)
    now = datetime.now(timezone.utc)
    verifier, _ = init.initialization_reviewer(item.agent, item.cap)
    oracle = init.initialization_oracle_id(item.agent, item.cap)
    row = dict(agent_id=item.agent, capability_id=item.cap, dimension='baseline', test_case='initialization',
        certification_test='baseline-initialization', test_version=oracle, test_result='PASS',
        verifier=verifier, executor_identity=item.agent, evidence='execution.json', evidence_sha256=sha(primary),
        certified_at=now.isoformat(), last_revalidated=now.isoformat(), expires_at=(now+timedelta(hours=1)).isoformat(),
        source_revision=SOURCE, authority_scope=agent_registry.agent_record(item.agent)['authority'],
        review_evidence='review.json', review_evidence_sha256='', review_run_id='temporary-distinct-owned-review',
        review_test_version=oracle, review_source_revision=SOURCE, reviewer_code_revision=REVIEWER_CODE)
    envelope = dict(schema_version='prime.agent-certification.review.v1', reviewer_identity=verifier,
        review_run_id=row['review_run_id'], source_revision=SOURCE, agent_id=item.agent, capability_id=item.cap,
        dimension='baseline', test_case='initialization', execution_evidence_sha256=sha(primary), test_result='PASS',
        review_test_version=oracle, observations=dict(execution_task_id=joined['task_id'], result_sha256=joined['result_sha256'],
            case_spec_sha256=joined['case_spec_sha256'], runtime_image_id=IMAGE, registry_sha256=item.registry_sha,
            reviewer_code_revision=REVIEWER_CODE, oracle_id=oracle, oracle_pass=True,
            reviewer_execution=dict(dispatch=result, artifact_content_utf8=raw.decode(),
                action_records=read_action_span(item.ledger.path, result['task_id'], 'agent.certification.initialization.review'),
                transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
                    artifact_http_status=200, runtime_source_revision=SOURCE, actual_runtime_image=IMAGE))))
    key = ephemeral_key(tmp_path / 'ephemeral-only')
    state = SimpleNamespace(row=row, execution=item.execution, review=envelope, root=tmp_path/'signature-evidence',
        pin=key['pin'], sign=key['sign'], calls=key['calls'], now=now)
    persist(state)
    return state


def persist(state):
    directory = state.root / state.row['agent_id']; directory.mkdir(parents=True, exist_ok=True)
    primary = canonical(state.execution)
    state.row['evidence_sha256'] = sha(primary)
    state.review['execution_evidence_sha256'] = sha(primary)
    raw = canonical(state.review); state.row['review_evidence_sha256'] = sha(raw)
    (directory/'execution.json').write_bytes(primary)
    (directory/'review.json').write_bytes(raw)


def sign(state):
    return sign_reviewed_case(state.row, evidence_root=state.root,
        execution_sha256=state.row['evidence_sha256'], review_sha256=state.row['review_evidence_sha256'],
        execution_source_revision=SOURCE, runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE,
        public_pin=state.pin, sign_digest=state.sign, now=state.now)


@pytest.mark.parametrize('fleet_event', PAIRS, indirect=True)
def test_each_owned_pair_has_original_subject_and_distinct_registered_review_and_signature(fleet_event, tmp_path):
    item = fleet_event
    joined = validate_initialization_execution(item.execution, source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=item.registry_sha, now=datetime.now(timezone.utc), agent_id=item.agent, capability_id=item.cap)
    state = signing_input(item, tmp_path)
    proof = state.review['observations']['reviewer_execution']
    reviewer, reviewer_cap = init.initialization_reviewer(item.agent, item.cap)
    assert reviewer != item.agent
    assert proof['dispatch']['agent_id'] == reviewer and proof['dispatch']['capability'] == reviewer_cap
    assert proof['dispatch']['task_id'] != joined['task_id']
    assert json.loads(proof['artifact_content_utf8'])['subject_domain_join'] == joined
    assert item.execution['dispatch']['agent_id'] == item.agent
    assert item.execution['submission'][1]['steps'][0]['capability'] == item.cap
    assert item.execution['objective_read'][1]['steps'][0]['capability'] == item.cap
    actions = [json.loads(line) for line in item.ledger.path.read_bytes().decode().splitlines()]
    assert [a['agent_id'] for a in actions] == [item.agent]*2+[reviewer]*2
    assert [a['action_type'] for a in actions] == [init.ACTION_TYPE]*2+['agent.certification.initialization.review']*2
    signed = sign(state)
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state.pin['jwk']}})
    assert len(state.calls) == 1 and verifier(signed) is True
    assert verifier({**signed, 'capability_id': 'responsibility.a19' if item.cap != 'responsibility.a19' else 'responsibility.a26'}) is False
    projection = AgentCertificationRegistry(state.root, source_revision=SOURCE, verify_record=verifier)._project_from_rows(
        item.agent, item.cap, state.now, [signed], agent_registry.agent_record(item.agent))
    assert projection['valid_cases'] == ['baseline:initialization']
    assert len(projection['missing_cases']) == 73 and projection['level'] == 'L0'
    assert projection['health'] == 'UNKNOWN'


@pytest.mark.parametrize('cap', ['responsibility.a26', 'responsibility.a25', 'responsibility.a18', 'responsibility.a19'])
def test_a26_subject_never_uses_self_or_wrong_capability_reviewer(fleet_event, cap):
    with pytest.raises(HTTPException) as error:
        review(fleet_event, capability=cap)
    assert error.value.status_code == 422


@pytest.mark.parametrize('change', [
    lambda e: e['case_spec'].update(capability_id='responsibility.a26'),
    lambda e: e['dispatch'].update(capability='responsibility.a26'),
    lambda e: e['submission'][1]['steps'][0].update(capability='responsibility.a26'),
    lambda e: e['objective_read'][1]['steps'][0].update(capability='responsibility.a26'),
    lambda e: e['artifact_metadata'].update(creator_agents=['a18']),
    lambda e: e['observation'].update(agent_id='a18'),
    lambda e: e['runtime'].update(source_revision='b'*40),
    lambda e: e['objective_read'][1]['execution_metadata'].update(jobs=[{'id':'invented'}]),
    lambda e: e.update(action_records=[]),
])
def test_rehashed_owned_pair_mismatch_not_reviewable(fleet_event, change):
    change(fleet_event.execution)
    fleet_event.payload['expected_execution_sha256'] = sha(canonical(fleet_event.execution))
    with pytest.raises(HTTPException) as error:
        review(fleet_event)
    assert error.value.status_code == 422


@pytest.mark.parametrize('field,value', [('verifier','a26'), ('executor_identity','a18'),
    ('capability_id','responsibility.a26'), ('authority_scope','owner'), ('review_test_version',init.ORACLE_ID)])
def test_ephemeral_signing_does_not_relabel_distinct_event(fleet_event, tmp_path, field, value):
    state = signing_input(fleet_event, tmp_path)
    state.row[field] = value
    with pytest.raises(CertificationReviewError):
        sign(state)
    assert state.calls == []


@pytest.mark.parametrize('change', [
    lambda p: p['dispatch'].update(agent_id='a26'),
    lambda p: p['dispatch'].update(capability='responsibility.a18'),
    lambda p: p['dispatch']['artifact'].update(creator_agents=['a26']),
    lambda p: p['dispatch'].update(review_action_durable=1),
    lambda p: p.update(action_records=[]),
])
def test_rehashed_peer_action_or_capability_laundering_never_reaches_signer(fleet_event, tmp_path, change):
    state = signing_input(fleet_event, tmp_path)
    change(state.review['observations']['reviewer_execution']); persist(state)
    with pytest.raises(CertificationReviewError):
        sign(state)
    assert state.calls == []


def test_no_owner_authorization_no_owned_event_read(fleet_event, monkeypatch):
    from app import objective_api
    monkeypatch.setattr(objective_api, 'get_read_only', lambda *a: pytest.fail('Read before auth'))
    with pytest.raises(HTTPException) as error:
        dispatch.dispatch_request(reviewer_request(fleet_event), 'wrong-owner')
    assert error.value.status_code == 401
