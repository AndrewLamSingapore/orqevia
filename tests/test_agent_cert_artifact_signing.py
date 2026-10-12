"""Temporary original-domain and ephemeral-key checks, never live/L7 evidence."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.action_records import ActionLedger, ActionRecord, DirectExecutor
from app.artifact_factory import ArtifactFactory
from app import agent_cert_artifact_events as events
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_certification import AgentCertificationRegistry
from app.agent_registry import agent_record
from app.agent_cert_role_review import artifact_event_review_join, ARTIFACT_REVIEW_SCHEMA, ARTIFACT_REVIEW_ACTION
from scripts.agent_cert_reviewed_signing import CertificationReviewError, SERVICE, sign_reviewed_case
from tests.test_agent_cert_artifact_events import domain, execute_and_collect, observation_failure_metrics, SOURCE, IMAGE
from tests.test_agent_cert_identity_signing import mutate_reviewer_artifact


CODE = 'e' * 40
KEY = 'https://fixturevault.vault.azure.net/keys/artifact-test/' + 'f' * 32


def persist(state):
    state.primary = events.canonical(state.execution)
    state.row['evidence_sha256'] = events.sha(state.primary)
    state.review['execution_evidence_sha256'] = events.sha(state.primary)
    state.review_bytes = events.canonical(state.review)
    state.row['review_evidence_sha256'] = events.sha(state.review_bytes)
    (state.root / 'a19' / 'execution.json').write_bytes(state.primary)
    (state.root / 'a19' / 'review.json').write_bytes(state.review_bytes)


def prepared(domain, case_id, tmp_path):
    execution, pins = execute_and_collect(domain, case_id)
    try:
        join = artifact_event_review_join(execution, **pins)
    except events.ArtifactEventError as error:
        # Preserve the original rejection; disclose only discriminating timing
        # measurements if a baseline fixture fails before the negative case.
        try:
            note = json.dumps(observation_failure_metrics(execution, pins['now']), sort_keys=True)
        except Exception:
            note = 'TIMING_DIAGNOSTIC_UNAVAILABLE'
        error.add_note(note)
        raise
    review_task = str(uuid.uuid4())
    reviewed_at = datetime.now(timezone.utc).isoformat()
    primary = events.canonical(execution)
    content = dict(schema_version=ARTIFACT_REVIEW_SCHEMA, task_id=review_task,
        reviewer_id='a26', reviewer_capability_id='responsibility.a26',
        subject_agent_id='a19', subject_capability_id='responsibility.a19',
        dimension='general', test_case=case_id.split(':')[1], source_revision=SOURCE,
        runtime_image_id=IMAGE, execution_evidence_sha256=events.sha(primary),
        case_spec_sha256=join['case_spec_sha256'], result_sha256=join['result_sha256'],
        oracle_id=events.ORACLE_ID, test_result='PASS', review_errors=[], model_calls=0,
        execution_model='DETERMINISTIC', subject_execution_verification='ARTIFACT_OBJECTIVE_ACTION_JOINED',
        subject_domain_join=join, certification='UNVERIFIED', review_nonce=str(uuid.uuid4()),
        reviewed_at=reviewed_at)
    ledger = ActionLedger(tmp_path / 'registered-review' / 'action-records.jsonl')
    factory = ArtifactFactory(tmp_path / 'registered-review' / 'artifacts')
    action = ActionRecord(review_task, 'a26', ARTIFACT_REVIEW_ACTION, 'artifact-factory',
        parameters_summary={'schema_version': ARTIFACT_REVIEW_SCHEMA, 'read_only_observations': True})
    try:
        metadata = DirectExecutor(ledger).execute(action, lambda: factory.create(kind='json',
            content=json.dumps(content, ensure_ascii=False), task_id=review_task, creator='a26',
            provenance='Deterministic computation; zero model calls', runtime_revision=SOURCE))
        assert ledger.flush(timeout=1) is True
        assert factory.retrieve(metadata['artifact_id'])[0] == metadata
        raw = factory.retrieve(metadata['artifact_id'])[1]
        original_lines = ledger.path.read_text(encoding='utf-8').splitlines(keepends=True)
    finally:
        assert ledger.close() is True
    certified_at = datetime.now(timezone.utc)
    row = dict(agent_id='a19', capability_id='responsibility.a19', dimension='general',
        test_case=case_id.split(':')[1], certification_test=case_id.replace(':', '-'),
        test_version=events.CASE_VERSION, test_result='PASS', verifier='a26', executor_identity='a19',
        evidence='execution.json', evidence_sha256=events.sha(primary),
        certified_at=certified_at.isoformat(), last_revalidated=certified_at.isoformat(),
        expires_at=(certified_at + timedelta(hours=1)).isoformat(), source_revision=SOURCE,
        authority_scope=agent_record('a19')['authority'], review_evidence='review.json', review_evidence_sha256='',
        review_run_id='temporary-artifact-independent-review', review_test_version=events.ORACLE_ID,
        review_source_revision=SOURCE, reviewer_code_revision=CODE)
    dispatch = dict(task_id=review_task, state='COMPLETED', artifact=metadata, model_calls=0,
        execution_model='DETERMINISTIC', agent_id='a26', capability='responsibility.a26',
        runtime_source_revision=SOURCE, review_action_id=action.action_id,
        review_action_durable=True, certification='UNVERIFIED')
    proof = dict(dispatch=dispatch, artifact_content_utf8=raw.decode(), action_records=original_lines,
        transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202, artifact_http_status=200,
            runtime_source_revision=SOURCE, actual_runtime_image=IMAGE))
    review = dict(schema_version='prime.agent-certification.review.v1', reviewer_identity='a26',
        review_run_id=row['review_run_id'], source_revision=SOURCE, agent_id='a19',
        capability_id='responsibility.a19', dimension='general', test_case=row['test_case'],
        execution_evidence_sha256=events.sha(primary), test_result='PASS', review_test_version=events.ORACLE_ID,
        observations=dict(execution_task_id=join['task_id'], result_sha256=join['result_sha256'],
            case_spec_sha256=join['case_spec_sha256'], runtime_image_id=IMAGE, registry_sha256=join['registry_sha256'],
            reviewer_code_revision=CODE, oracle_id=events.ORACLE_ID, oracle_pass=True, reviewer_execution=proof))
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    encode = lambda value: base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()
    state = SimpleNamespace(root=tmp_path / 'evidence', row=row, execution=execution, review=review, calls=[],
        pin=dict(key_id=KEY, jwk=dict(kty='EC', crv='P-256', x=encode(point.x), y=encode(point.y))))
    (state.root / 'a19').mkdir(parents=True)
    def signing(digest):
        state.calls.append(digest)
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return KEY, r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    state.signing = signing
    persist(state)
    return state


def sign(state, **changes):
    args = dict(evidence_root=state.root, execution_sha256=state.row['evidence_sha256'],
        review_sha256=state.row['review_evidence_sha256'], execution_source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=CODE, public_pin=state.pin,
        sign_digest=state.signing, now=datetime.now(timezone.utc))
    args.update(changes)
    return sign_reviewed_case(state.row, **args)


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_original_temporary_artifacts_actions_and_distinct_reviewer_sign_only_one_case(domain, tmp_path, case_id):
    state = prepared(domain, case_id, tmp_path)
    original = deepcopy(state.row), state.primary, state.review_bytes
    signed = sign(state)
    assert (state.row, state.primary, state.review_bytes) == original
    assert len(state.calls) == 1
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state.pin['jwk']}})
    assert verifier(signed) is True
    assert verifier(dict(signed, test_case='artifact_produce' if case_id != 'general:artifact_produce' else 'review')) is False
    projection = AgentCertificationRegistry(state.root, source_revision=SOURCE,
        verify_record=verifier)._project_from_rows('a19', 'responsibility.a19', datetime.now(timezone.utc),
            [signed], agent_record('a19'))
    assert projection['valid_cases'] == [case_id]
    assert len(projection['missing_cases']) == 73 and projection['level'] == 'L0'
    assert projection['trust_state'] != 'L7-CURRENT'
    assert state.execution['objective_read'][1]['execution_metadata']['jobs'] == []


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_later_protected_verification_preserves_original_fresh_review_and_binds_verifier_code(domain, tmp_path, case_id):
    state = prepared(domain, case_id, tmp_path)
    original = deepcopy(state.row), state.primary, state.review_bytes
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    verifier_code = 'f' * 40
    signed = sign(state, now=later, verifier_code_revision=verifier_code)
    assert (state.row, state.primary, state.review_bytes) == original
    assert len(state.calls) == 1
    assert signed['reviewer_code_revision'] == CODE
    assert signed['verifier_code_revision'] == verifier_code
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state.pin['jwk']}})
    assert verifier(signed) is True
    assert verifier(dict(signed, verifier_code_revision=CODE)) is False
    projection = AgentCertificationRegistry(state.root, source_revision=SOURCE,
        verify_record=verifier)._project_from_rows('a19', 'responsibility.a19', later,
            [signed], agent_record('a19'))
    assert projection['valid_cases'] == [case_id]
    assert len(projection['missing_cases']) == 73 and projection['level'] == 'L0'
    assert projection['trust_state'] != 'L7-CURRENT'


@pytest.mark.parametrize('review_delay_seconds', [-1, events.MAX_AGE_SECONDS + 1])
def test_original_review_cannot_consume_future_or_already_stale_event(domain, tmp_path, review_delay_seconds):
    state = prepared(domain, events.SUPPORTED_CASES[1], tmp_path)
    completed = events._utc(state.execution['dispatch']['artifact_event']['completed_at'])
    reviewed = completed + timedelta(seconds=review_delay_seconds)
    with pytest.raises(events.ArtifactEventError, match='ARTIFACT_EVENT_STALE_OR_UNBOUNDED'):
        artifact_event_review_join(state.execution, source_revision=SOURCE,
            runtime_image_id=IMAGE, registry_sha256=state.review['observations']['registry_sha256'], now=reviewed)
    mutate_reviewer_artifact(state, lambda content: content.update(reviewed_at=reviewed.isoformat()))
    persist(state)
    with pytest.raises(CertificationReviewError):
        sign(state, now=completed + timedelta(minutes=10))
    assert state.calls == []


@pytest.mark.parametrize('defect', ['unbound_timestamp', 'future_review', 'review_after_artifact',
    'review_after_certification', 'expired_record'])
def test_later_verification_still_rejects_review_time_custody_order_and_current_expiry(domain, tmp_path, defect):
    state = prepared(domain, events.SUPPORTED_CASES[1], tmp_path)
    proof = state.review['observations']['reviewer_execution']
    content = json.loads(proof['artifact_content_utf8'])
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    if defect == 'unbound_timestamp':
        content['reviewed_at'] = (events._utc(content['reviewed_at']) + timedelta(microseconds=1)).isoformat()
        proof['artifact_content_utf8'] = json.dumps(content, ensure_ascii=False)
    elif defect == 'future_review':
        mutate_reviewer_artifact(state, lambda value: value.update(reviewed_at=(later + timedelta(seconds=1)).isoformat()))
    elif defect == 'review_after_artifact':
        stamp = events._utc(proof['dispatch']['artifact']['timestamp']) + timedelta(seconds=1)
        mutate_reviewer_artifact(state, lambda value: value.update(reviewed_at=stamp.isoformat()))
    elif defect == 'review_after_certification':
        state.row['certified_at'] = (events._utc(content['reviewed_at']) - timedelta(microseconds=1)).isoformat()
    else:
        later = events._utc(state.row['expires_at'])
    persist(state)
    with pytest.raises(CertificationReviewError):
        sign(state, now=later)
    assert state.calls == []


@pytest.mark.parametrize('defect', ['self_review', 'source', 'image', 'case', 'borrowed_oracle',
    'model_boolean', 'missing_subject_actions', 'missing_input_actions', 'raw_output', 'new_queue_job',
    'review_action_type', 'review_nonce', 'reviewer_artifact_subject', 'review_join', 'review_zero_boolean',
    'review_not_durable', 'subject_stale', 'review_transport', 'registry'])
def test_semantic_or_custody_tamper_never_reaches_signing(domain, tmp_path, defect):
    state = prepared(domain, events.SUPPORTED_CASES[0], tmp_path)
    proof = state.review['observations']['reviewer_execution']
    if defect == 'self_review': state.row['verifier'] = 'a19'
    elif defect == 'source': state.row['source_revision'] = 'c' * 40
    elif defect == 'image': state.execution['runtime_after']['image_digest'] = 'sha256:' + 'c' * 64
    elif defect == 'case': state.row['test_case'] = 'artifact_produce'
    elif defect == 'borrowed_oracle': state.row['review_test_version'] = 'a19-substantive-quality-oracle.v1'
    elif defect == 'model_boolean': state.execution['dispatch']['model_calls'] = False
    elif defect == 'missing_subject_actions': state.execution['action_records'] = []
    elif defect == 'missing_input_actions': state.execution['input_action_records'] = []
    elif defect == 'raw_output': state.execution['artifact_content_utf8'] += '\n'
    elif defect == 'new_queue_job': state.execution['objective_read'][1]['execution_metadata']['jobs'] = [{'id': str(uuid.uuid4())}]
    elif defect == 'review_action_type':
        lines = [json.loads(line) for line in proof['action_records']]
        for line in lines: line['action_type'] = 'agent.certification.role.review'
        from tests.test_agent_cert_identity_signing import rechain_reviewer
        rechain_reviewer(state, lines)
    elif defect == 'review_nonce': mutate_reviewer_artifact(state, lambda v: v.update(review_nonce='-' * 36))
    elif defect == 'reviewer_artifact_subject': mutate_reviewer_artifact(state, lambda v: v.update(subject_agent_id='a20'))
    elif defect == 'review_join': mutate_reviewer_artifact(state, lambda v: v['subject_domain_join'].update(subject_action_sha256='c' * 64))
    elif defect == 'review_zero_boolean': proof['dispatch']['model_calls'] = False
    elif defect == 'review_not_durable': proof['dispatch']['review_action_durable'] = False
    elif defect == 'subject_stale':
        state.execution['dispatch']['artifact_event']['completed_at'] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    elif defect == 'review_transport': proof['transport']['authentication'] = 'SELF_DECLARED'
    elif defect == 'registry': state.execution['dispatch']['artifact_event']['registry_sha256'] = 'c' * 64
    persist(state)
    with pytest.raises(CertificationReviewError): sign(state)
    assert state.calls == []


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_artifact_event_signing_forbids_any_cloud_claim(domain, tmp_path, case_id):
    state = prepared(domain, case_id, tmp_path)
    with pytest.raises(CertificationReviewError, match='ARTIFACT_CLOUD_TRANSPORT_FORBIDDEN'):
        sign(state, cloud_policy={})
    assert state.calls == []


def test_review_time_is_original_event_completion_not_later_observer_timestamp(domain, tmp_path):
    state = prepared(domain, events.SUPPORTED_CASES[1], tmp_path)
    content = json.loads(state.review['observations']['reviewer_execution']['artifact_content_utf8'])
    assert content['subject_domain_join']['completed_at'] == state.execution['dispatch']['artifact_event']['completed_at']
    assert content['subject_domain_join']['completed_at'] != state.execution['observation']['completed_at']
    assert content['subject_domain_join']['case_spec_sha256'] == events.sha(events.canonical(state.execution['case_spec']))


def test_baseline_rejection_is_not_masked_by_timing_diagnostic_failure(domain, tmp_path, monkeypatch):
    original = events.ArtifactEventError('ARTIFACT_OBSERVATION_UNBOUND')
    def rejected(*args, **kwargs):
        raise original
    def unavailable(*args, **kwargs):
        raise ValueError('malformed diagnostic input')
    monkeypatch.setitem(globals(), 'artifact_event_review_join', rejected)
    monkeypatch.setitem(globals(), 'observation_failure_metrics', unavailable)
    with pytest.raises(events.ArtifactEventError, match='ARTIFACT_OBSERVATION_UNBOUND') as caught:
        prepared(domain, events.SUPPORTED_CASES[0], tmp_path)
    assert caught.value is original
    assert caught.value.__notes__ == ['TIMING_DIAGNOSTIC_UNAVAILABLE']
