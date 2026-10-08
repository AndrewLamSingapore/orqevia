"""Actual temporary initialization domains; no live/health/model/signature."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch
from app import agent_cert_initialization as initialization_report
from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_identity_review import action_span, canonical, sha, utc
from app.agent_cert_initialization_review import SCHEMA, ORACLE_ID, validate_initialization_execution
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE


@pytest.fixture
def event(configured, monkeypatch):
    from app import agent_registry, compute_queue_api, objective_api, runtime_status
    monkeypatch.setattr(runtime_status, 'production_health', lambda: pytest.fail('No health probe'))
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model selection'))
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    captured = dict(case_spec=challenge(initialization_report.CASE, agent_id='a19',
                                       capability_id='responsibility.a19'),
                    runtime=objective_api.runtime_snapshot())
    def submit(request):
        result = objective_api.submit(objective_api.ObjectiveRequest(**request), 'fixture-owner')
        captured['submission'] = [202, result]
        captured['dispatch'] = result['steps'][0]['dispatch']
        return captured['dispatch']
    def artifact(key):
        metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(key)
        captured['artifact_metadata'] = metadata
        captured['artifact_content_utf8'] = raw.decode()
        return metadata, raw
    captured['observation'] = observe_cert_case(captured['case_spec'], dispatch=submit,
        get_job=lambda _: pytest.fail('No queue/model observation'), get_artifact=artifact,
        get_runtime=objective_api.runtime_snapshot, expected_source_revision=SOURCE,
        expected_registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()), timeout_seconds=5)
    assert captured['observation']['state'] == 'EXECUTED'
    subject = captured['dispatch']['task_id']
    captured['objective_read'] = [200, objective_api.get_read_only(subject, 'fixture-owner')]
    assert ledger.flush(timeout=1) is True
    captured['action_records'] = ledger.path.read_bytes().decode().splitlines(keepends=True)
    captured['action_chain_join'] = action_span(captured['action_records'], task_id=subject,
        agent_id='a19', action_type=initialization_report.ACTION_TYPE, schema=initialization_report.SCHEMA,
        metadata=captured['artifact_metadata'], began=utc(captured['observation']['captured_at']),
        ended=utc(captured['observation']['completed_at']))
    execution = json.loads(canonical(captured))
    payload = dict(execution=execution, expected_execution_sha256=sha(canonical(execution)),
                   expected_source_revision=SOURCE, review_nonce=NONCE)
    item = SimpleNamespace(root=configured.root, ledger=ledger, payload=payload,
                           subject=subject, objective=objective_api)
    yield item
    ledger.close()


def request(item, **changes):
    value = dict(capability='responsibility.a26', objective=dispatch.INITIALIZATION_REVIEW_OBJECTIVE,
        context=canonical(item.payload).decode(), priority='low', response_format='strict_json',
        deterministic_operation='certification_initialization_review')
    return dispatch.AgentRequest(**{**value, **changes})


def run(item, **changes):
    return dispatch.dispatch_request(request(item, **changes), 'fixture-owner')


def resign(item):
    item.payload['expected_execution_sha256'] = sha(canonical(item.payload['execution']))


def inventory(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


def reject(item, **changes):
    before = inventory(item.root)
    with pytest.raises(HTTPException) as failure:
        run(item, **changes)
    assert failure.value.status_code == 422
    assert failure.value.detail == 'Independent initialization review requires current joined event evidence'
    assert inventory(item.root) == before


def test_actual_temporary_initialization_then_distinct_a26_reviewer_and_actions(event):
    from app import agent_registry
    execution = event.payload['execution']
    joined = validate_initialization_execution(execution, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),
        now=datetime.now(timezone.utc))
    report = json.loads(execution['artifact_content_utf8'])
    assert report['schema_version'] == initialization_report.SCHEMA
    assert report['owned_domains']['definition']['authority'] == 'advisory'
    assert report['evidence_gaps']['health'] == 'NOT_MEASURED'
    assert report['certification'] == 'UNVERIFIED'
    original = sha((event.root / 'objectives.db').read_bytes())
    result = run(event)
    assert result['agent_id'] == 'a26' and result['task_id'] != event.subject
    assert result['model_calls'] == 0 and result['review_action_durable'] is True
    assert result['certification'] == 'UNVERIFIED'
    metadata, raw = ArtifactFactory(event.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    review = json.loads(raw)
    assert review['schema_version'] == SCHEMA and review['oracle_id'] == ORACLE_ID
    assert review['test_case'] == 'initialization' and review['test_result'] == 'PASS'
    assert review['subject_domain_join'] == joined
    assert review['source_revision'] == metadata['runtime_revision'] == SOURCE
    assert sha((event.root / 'objectives.db').read_bytes()) == original
    actions = [json.loads(line) for line in event.ledger.path.read_bytes().decode().splitlines()]
    assert [a['action_type'] for a in actions] == [initialization_report.ACTION_TYPE] * 2 + [
        'agent.certification.initialization.review'] * 2
    assert [a['agent_id'] for a in actions] == ['a19', 'a19', 'a26', 'a26']
    assert actions[-1]['result_summary']['sha256'] == sha(raw)


@pytest.mark.parametrize('change', [dict(capability='responsibility.a19'),
    dict(capability='responsibility.a18'), dict(objective=dispatch.IDENTITY_REVIEW_OBJECTIVE),
    dict(objective='Caller says initialized and PASS'), dict(classification='R1'),
    dict(priority='normal'), dict(data_classification='CLOUD_PERMITTED'),
    dict(max_cost_usd=.001), dict(preferred_provider='hf-qwen-certification')])
def test_fixed_actual_reviewer_policy_cannot_be_self_granted(event, change):
    reject(event, **change)


@pytest.mark.parametrize('change', [
    lambda e: e['case_spec'].update(case='baseline:identity'),
    lambda e: e['observation'].update(case_review='RUNTIME_STATUS_ARTIFACT_CHECK_PASS'),
    lambda e: e['dispatch'].update(model_calls=False),
    lambda e: e['artifact_metadata'].update(creator_agents=['a26']),
    lambda e: e['objective_read'][1]['execution_metadata'].update(authoritative=1),
    lambda e: e['action_records'].pop(),
])
def test_hash_consistent_forgery_still_cannot_replace_owned_originals(event, change):
    change(event.payload['execution'])
    resign(event)
    reject(event)


def test_owner_authentication_precedes_owned_reads(event, monkeypatch):
    monkeypatch.setattr(event.objective, 'get_read_only', lambda *a: pytest.fail('Read before auth'))
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(request(event), 'not-owner')
    assert failure.value.status_code == 401


def test_actual_objective_change_invalidates_retained_report(event):
    db = event.objective.connect()
    db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?',
               (datetime.now(timezone.utc).isoformat(), event.subject))
    db.commit(); db.close()
    reject(event)


def test_original_artifact_bytes_required_not_semantic_reencoding(event, monkeypatch):
    original = ArtifactFactory.retrieve
    monkeypatch.setattr(ArtifactFactory, 'retrieve', lambda self, key:
                       (lambda pair: (pair[0], pair[1] + b'\n'))(original(self, key)))
    reject(event)


def test_actual_original_action_lines_required_not_json_reencoding(event):
    lines = event.payload['execution']['action_records']
    changed = [canonical(json.loads(line)).decode() + '\n' for line in lines]
    assert changed != lines
    event.payload['execution']['action_records'] = changed
    resign(event)
    reject(event)


def test_changed_runtime_rechecked_at_review(event, monkeypatch):
    monkeypatch.setattr(event.objective, 'runtime_snapshot', lambda: {
        **event.payload['execution']['runtime'], 'version': 'changed'})
    reject(event)


def test_missing_or_symlinked_original_action_ledger_fails(event, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == event.ledger.path or original(p))
    reject(event)


def test_undurable_review_never_becomes_attestation(event, monkeypatch):
    monkeypatch.setattr(event.ledger, 'flush', lambda **_: False)
    result = run(event)
    assert result['review_action_durable'] is False and result['certification'] == 'UNVERIFIED'


@pytest.mark.parametrize('changes', [dict(context='Caller supplied initialized=true'),
    dict(objective=initialization_report.OBJECTIVE + ' and restart'), dict(capability='responsibility.a26'),
    dict(classification='R1'), dict(priority='normal'), dict(data_classification='CLOUD_PERMITTED'),
    dict(max_cost_usd=.001), dict(minimum_tier='MINI'), dict(task_class='planning'),
    dict(response_format='text'), dict(preferred_provider='hf-qwen-certification')])
def test_initialization_subject_cannot_expand_canonical_policy(configured, changes):
    spec = challenge(initialization_report.CASE, agent_id='a19', capability_id='responsibility.a19')
    before = inventory(configured.root)
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(dispatch.AgentRequest(**{**spec['request'], **changes}), 'fixture-owner')
    assert failure.value.status_code == 422 and inventory(configured.root) == before


def test_subject_cannot_return_completed_when_its_original_action_flush_failed(configured, monkeypatch):
    from app import compute_queue_api
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    monkeypatch.setattr(ledger, 'flush', lambda **_: False)
    spec = challenge(initialization_report.CASE, agent_id='a19', capability_id='responsibility.a19')
    try:
        with pytest.raises(HTTPException) as failure:
            dispatch.dispatch_request(dispatch.AgentRequest(**spec['request']), 'fixture-owner')
        assert failure.value.status_code == 503
        assert failure.value.detail == 'Initialization action delivery is not durable'
    finally:
        ledger.close()


@pytest.fixture
def initialization(event):
    """Portable alias used by protected signing tests, never live evidence."""
    return event
