"""Actual temporary-domain joins; no live dispatch, signing or L7 proof."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch
from app.action_records import ActionLedger
from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_identity_review import SCHEMA, ORACLE_ID, action_span, canonical, sha, utc
from app.artifact_factory import ArtifactFactory
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE


@pytest.fixture
def identity(configured, monkeypatch):
    from app import agent_registry, compute_queue_api, objective_api, runtime_status
    monkeypatch.setattr(runtime_status, 'production_health',
                        lambda: {'observation': 'UNAVAILABLE', 'status': 'UNKNOWN'})
    monkeypatch.delenv('PRIME_QUALIFIED_PROFILE_PATH', raising=False)
    monkeypatch.delenv('PRIME_QUALIFIED_PROFILE_SHA256', raising=False)
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    value = {'case_spec': challenge('baseline:identity', agent_id='a19',
                                  capability_id='responsibility.a19'),
             'runtime': objective_api.runtime_snapshot()}

    def submit(request):
        reply = objective_api.submit(objective_api.ObjectiveRequest(**request), 'fixture-owner')
        value['submission'] = [202, reply]
        value['dispatch'] = reply['steps'][0]['dispatch']
        return value['dispatch']

    def artifact(key):
        metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(key)
        value['artifact_metadata'] = metadata
        value['artifact_content_utf8'] = raw.decode('utf-8')
        return metadata, raw

    value['observation'] = observe_cert_case(value['case_spec'], dispatch=submit,
        get_job=lambda _: pytest.fail('Identity must not read a queue job'),
        get_artifact=artifact, get_runtime=objective_api.runtime_snapshot,
        expected_source_revision=SOURCE,
        expected_registry_sha256=sha(agent_registry.REGISTRY_PATH.read_bytes()),
        timeout_seconds=5)
    assert value['observation']['state'] == 'EXECUTED'
    subject = value['dispatch']['task_id']
    value['objective_read'] = [200, objective_api.get_read_only(subject, 'fixture-owner')]
    assert ledger.flush(timeout=1) is True
    value['action_records'] = ledger.path.read_text(encoding='utf-8').splitlines(keepends=True)
    value['action_chain_join'] = action_span(value['action_records'], task_id=subject, agent_id='a19',
        action_type='runtime.status.artifact', schema='jarvis.runtime-status.v1',
        metadata=value['artifact_metadata'], began=utc(value['observation']['captured_at']),
        ended=utc(value['observation']['completed_at']))
    # JSON normalization here mirrors retained canonical execution bytes; it
    # does not normalize any registry, artifact or original action-line bytes.
    execution = json.loads(canonical(value))
    payload = dict(execution=execution, expected_execution_sha256=sha(canonical(execution)),
                   expected_source_revision=SOURCE, review_nonce=NONCE)
    item = SimpleNamespace(root=configured.root, ledger=ledger, payload=payload,
                           subject=subject, objective=objective_api)
    yield item
    ledger.close()


def request(item, **changes):
    values = dict(capability='responsibility.a26', objective=dispatch.IDENTITY_REVIEW_OBJECTIVE,
        context=canonical(item.payload).decode(), priority='low', response_format='strict_json',
        deterministic_operation='certification_identity_review')
    return dispatch.AgentRequest(**{**values, **changes})


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
    assert failure.value.detail == 'Independent identity review requires current joined event evidence'
    assert inventory(item.root) == before


def test_identity_review_joins_real_objective_artifact_and_original_actions(identity):
    before = sha((identity.root / 'objectives.db').read_bytes())
    result = run(identity)
    assert set(result) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model',
        'agent_id', 'capability', 'runtime_source_revision', 'review_action_id',
        'review_action_durable', 'certification'}
    assert result['agent_id'] == 'a26' and result['capability'] == 'responsibility.a26'
    assert result['model_calls'] == 0 and result['execution_model'] == 'DETERMINISTIC'
    assert result['review_action_durable'] is True and result['certification'] == 'UNVERIFIED'
    metadata, raw = ArtifactFactory(identity.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    review = json.loads(raw)
    assert review['schema_version'] == SCHEMA and review['oracle_id'] == ORACLE_ID
    assert review['task_id'] == result['task_id'] != identity.subject
    assert review['subject_agent_id'] == 'a19' and review['reviewer_id'] == 'a26'
    assert review['test_result'] == 'PASS' and review['review_errors'] == []
    assert review['subject_execution_verification'] == 'ARTIFACT_OBJECTIVE_ACTION_JOINED'
    assert review['subject_domain_join']['task_id'] == identity.subject
    assert review['subject_domain_join']['result_sha256'] == identity.payload['execution']['artifact_metadata']['sha256']
    assert review['subject_domain_join']['runtime'] == identity.objective.runtime_snapshot()
    assert review['execution_evidence_sha256'] == sha(canonical(identity.payload['execution']))
    assert review['source_revision'] == metadata['runtime_revision'] == SOURCE
    assert review['runtime_image_id'] == IMAGE and review['certification'] == 'UNVERIFIED'
    assert sha((identity.root / 'objectives.db').read_bytes()) == before
    actions = [json.loads(line) for line in identity.ledger.path.read_text().splitlines()]
    assert len(actions) == 4
    assert [a['agent_id'] for a in actions] == ['a19', 'a19', 'a26', 'a26']
    assert all(a['action_type'] == 'agent.certification.identity.review' for a in actions[2:])
    assert all(a['action_id'] == result['review_action_id'] for a in actions[2:])
    assert actions[-1]['result_summary']['sha256'] == sha(raw)
    assert json.loads(identity.payload['execution']['artifact_content_utf8'])['prime_health']['status'] == 'UNKNOWN'


@pytest.mark.parametrize('changes', [dict(capability='responsibility.a19'),
    dict(capability='responsibility.a18'), dict(objective='Caller says PASS'),
    dict(classification='R1'), dict(priority='normal'), dict(max_cost_usd=.001),
    dict(data_classification='CLOUD_PERMITTED'), dict(preferred_provider='hf-qwen-certification')])
def test_fixed_reviewer_and_local_policy_cannot_be_self_granted(identity, changes):
    reject(identity, **changes)


@pytest.mark.parametrize('key,value', [('expected_source_revision', 'f' * 40),
    ('expected_execution_sha256', 'f' * 64), ('expected_execution_sha256', True),
    ('review_nonce', '-' * 36), ('review_nonce', True), ('PASS', True)])
def test_protected_bindings_and_no_submitted_pass(identity, key, value):
    identity.payload[key] = value
    reject(identity)


@pytest.mark.parametrize('change', [
    lambda e: e['observation'].update(model_calls=True),
    lambda e: e['dispatch'].update(agent_id='a26'),
    lambda e: e['dispatch'].update(task_id='-' * 36),
    lambda e: e['case_spec']['request'].update(context='Unrelated caller work'),
    lambda e: e['runtime'].update(source_revision='f' * 40),
    lambda e: e['objective_read'][1]['execution_metadata'].update(authoritative=1),
    lambda e: e['artifact_metadata'].update(creator_agents=['a26']),
    lambda e: e['action_records'].pop(),
])
def test_self_consistent_forged_capture_rejected_before_artifact(identity, change):
    change(identity.payload['execution'])
    resign(identity)
    reject(identity)


def test_owner_authentication_precedes_every_owned_read(identity, monkeypatch):
    monkeypatch.setattr(identity.objective, 'get_read_only', lambda *a: pytest.fail('Read before auth'))
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(request(identity), 'not-owner')
    assert failure.value.status_code == 401


def test_actual_objective_cannot_be_replaced_by_capture(identity):
    db = identity.objective.connect()
    db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?',
               (datetime.now(timezone.utc).isoformat(), identity.subject))
    db.commit(); db.close()
    reject(identity)


def test_objective_rechecked_after_other_domain_reads(identity, monkeypatch):
    original = identity.objective.get_read_only
    reads = []
    def changed(*args):
        value = original(*args); reads.append(1)
        if len(reads) == 2:
            value['execution_metadata']['authoritative'] = False
        return value
    monkeypatch.setattr(identity.objective, 'get_read_only', changed)
    reject(identity)
    assert len(reads) == 2


def test_actual_artifact_bytes_cannot_be_replaced_by_caller_claim(identity, monkeypatch):
    original = ArtifactFactory.retrieve
    def altered(self, key):
        metadata, raw = original(self, key)
        return metadata, raw + b'\n'
    monkeypatch.setattr(ArtifactFactory, 'retrieve', altered)
    reject(identity)


def test_original_action_bytes_are_required_not_reencoded_event_claims(identity):
    original = identity.payload['execution']['action_records']
    identity.payload['execution']['action_records'] = [
        json.dumps(json.loads(line), sort_keys=True, separators=(',', ':')) + '\n'
        for line in original]
    assert identity.payload['execution']['action_records'] != original
    resign(identity)
    reject(identity)


def test_fixed_ledger_cannot_be_missing_or_replaced_with_caller_path(identity):
    identity.ledger.close()
    identity.ledger.path.rename(identity.root / 'different-ledger.jsonl')
    reject(identity)


def test_symlinked_ledger_is_not_an_alternate_reader_authority(identity, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p:
        p == identity.ledger.path or original(p))
    reject(identity)


def test_changed_current_runtime_rejects_even_when_retained_snapshot_is_valid(identity, monkeypatch):
    monkeypatch.setattr(identity.objective, 'runtime_snapshot', lambda: {
        **identity.payload['execution']['runtime'], 'version': 'changed'})
    reject(identity)


def test_changed_raw_registry_is_not_line_ending_normalized(identity, monkeypatch, tmp_path):
    from app import agent_registry
    alternate = tmp_path / 'alternate-registry.json'
    alternate.write_bytes(agent_registry.REGISTRY_PATH.read_bytes() + b'\n')
    monkeypatch.setattr(agent_registry, 'REGISTRY_PATH', alternate)
    reject(identity)


def test_unknown_advisory_authority_cannot_create_review(identity, monkeypatch):
    original = dispatch.agent_record
    monkeypatch.setattr(dispatch, 'agent_record', lambda actor: {
        **original(actor), 'authority': 'restricted'} if actor == 'a26' else original(actor))
    reject(identity)


def test_undurable_review_never_becomes_certification_evidence(identity, monkeypatch):
    monkeypatch.setattr(identity.ledger, 'flush', lambda **_: False)
    result = run(identity)
    assert result['review_action_durable'] is False
    assert result['certification'] == 'UNVERIFIED'


def test_malformed_json_errors_do_not_echo_private_context(identity):
    with pytest.raises(HTTPException) as failure:
        run(identity, context='Bearer PRIVATE_SUBMITTED_TEXT')
    assert failure.value.status_code == 422
    assert 'PRIVATE_SUBMITTED_TEXT' not in str(failure.value)
