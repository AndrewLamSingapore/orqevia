"""Independent temporary identity signing tests; no live evidence or Azure.

The subject is the portable original-domain fixture. The separate reviewer
artifact and original JSONL pair are produced by the actual temporary artifact
factory/action ledger, not by a declared reviewer name. All keys are ephemeral.
"""
import base64
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
import traceback

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app import action_records, artifact_factory
from app.action_records import ActionLedger, ActionRecord, DirectExecutor
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_identity_review import (
    ORACLE_ID, SCHEMA, validate_identity_execution,
)
from app.agent_certification import AgentCertificationRegistry
from app.agent_registry import REGISTRY_PATH, agent_record
from scripts.agent_cert_reviewed_signing import (
    CertificationReviewError, SERVICE, _RECORD_FIELDS, sign_reviewed_case,
)
from tests.test_agent_cert_identity_review import (
    IMAGE, NOW, SOURCE, TASK, action_lines, canonical, fixture_execution,
    refresh_actions, refresh_artifact, sha, stamp,
)


REVIEWER_CODE = 'e' * 40
REVIEW_TASK = '44444444-4444-4444-8444-444444444444'
REVIEW_NONCE = '55555555-5555-4555-8555-555555555555'
KEY = 'https://fixturevault.vault.azure.net/keys/identity-test/' + 'f' * 32
REGISTRY_BUILD_SHA = sha(REGISTRY_PATH.read_bytes().replace(b'\r\n', b'\n'))


def reviewer_content(state):
    join = validate_identity_execution(state.execution, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=REGISTRY_BUILD_SHA, now=NOW)
    return dict(schema_version=SCHEMA, task_id=REVIEW_TASK, reviewer_id='a26',
        reviewer_capability_id='responsibility.a26', subject_agent_id='a19',
        subject_capability_id='responsibility.a19', dimension='baseline', test_case='identity',
        source_revision=SOURCE, runtime_image_id=IMAGE,
        execution_evidence_sha256=sha(state.primary), case_spec_sha256=join['case_spec_sha256'],
        result_sha256=join['result_sha256'], oracle_id=ORACLE_ID, test_result='PASS',
        review_errors=[], model_calls=0, execution_model='DETERMINISTIC',
        subject_execution_verification='ARTIFACT_OBJECTIVE_ACTION_JOINED',
        subject_domain_join=join, certification='UNVERIFIED', review_nonce=REVIEW_NONCE,
        reviewed_at=stamp(-3.9))


def persist(state, *, primary=None, review=None):
    """Write only owned temporary original evidence, never a production store."""
    if primary is None:
        primary = canonical(state.execution)
    state.primary = primary
    state.row['evidence_sha256'] = sha(primary)
    state.review['execution_evidence_sha256'] = sha(primary)
    if review is None:
        review = canonical(state.review)
    state.review_bytes = review
    state.row['review_evidence_sha256'] = sha(review)
    folder = state.root / 'a19'
    (folder / 'execution.json').write_bytes(primary)
    (folder / 'review.json').write_bytes(review)


def proof(state):
    return state.review['observations']['reviewer_execution']


def rechain_reviewer(state, events):
    proof(state)['action_records'] = action_lines([
        {k: v for k, v in event.items() if k not in ('sequence', 'previous_sha256', 'sha256')}
        for event in events])


def mutate_reviewer_artifact(state, change):
    """Keep raw-artifact and action hashes consistent for semantic negatives."""
    value = json.loads(proof(state)['artifact_content_utf8'])
    change(value)
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    proof(state)['artifact_content_utf8'] = raw.decode('utf-8')
    metadata = proof(state)['dispatch']['artifact']
    metadata.update(sha256=sha(raw), bytes=len(raw))
    events = [json.loads(line) for line in proof(state)['action_records']]
    events[-1]['result_summary']['sha256'] = sha(raw)
    rechain_reviewer(state, events)


@pytest.fixture
def identity(tmp_path, monkeypatch):
    execution = fixture_execution()
    # The portable fixture deliberately has a placeholder registry. This
    # independently binds the actual LF build bytes required by the signer.
    refresh_artifact(execution,
        lambda report: report['registry'].update(source_sha256=REGISTRY_BUILD_SHA))
    execution['observation']['registry_sha256'] = REGISTRY_BUILD_SHA
    primary = canonical(execution)
    join = validate_identity_execution(execution, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=REGISTRY_BUILD_SHA, now=NOW)
    root = tmp_path / 'evidence'
    (root / 'a19').mkdir(parents=True)
    row = dict(agent_id='a19', capability_id='responsibility.a19', dimension='baseline',
        test_case='identity', certification_test='baseline-identity', test_version=ORACLE_ID,
        test_result='PASS', verifier='a26', executor_identity='a19', evidence='execution.json',
        evidence_sha256=sha(primary), certified_at=stamp(-1), last_revalidated=stamp(-0.5),
        expires_at=stamp(3600), source_revision=SOURCE, authority_scope=agent_record('a19')['authority'],
        review_evidence='review.json', review_evidence_sha256='',
        review_run_id='temporary-identity-independent-review', review_test_version=ORACLE_ID,
        review_source_revision=SOURCE, reviewer_code_revision=REVIEWER_CODE)
    state = SimpleNamespace(root=root, row=row, execution=execution, primary=primary,
                            calls=[], review=None)
    content = reviewer_content(state)
    # Generate an actual original ActionLedger span in the isolated fixture,
    # with the same factory serialization used by the application dispatcher.
    ticks = iter((NOW + timedelta(seconds=-3.8), NOW + timedelta(seconds=-3.2)))
    monkeypatch.setattr(action_records, 'datetime', SimpleNamespace(now=lambda _: next(ticks)))
    monkeypatch.setattr(artifact_factory, 'datetime',
                        SimpleNamespace(now=lambda _: NOW + timedelta(seconds=-3.5)))
    ledger = ActionLedger(tmp_path / 'review-actions.jsonl')
    action = ActionRecord(REVIEW_TASK, 'a26', 'agent.certification.identity.review', 'artifact-factory',
        classification='R0', model_backend='deterministic',
        parameters_summary={'schema_version': SCHEMA, 'read_only_observations': True})
    try:
        factory = artifact_factory.ArtifactFactory(tmp_path / 'review-artifacts')
        metadata = DirectExecutor(ledger).execute(action, lambda: factory.create(kind='json',
            content=json.dumps(content, ensure_ascii=False), task_id=REVIEW_TASK, creator='a26',
            provenance='Deterministic computation; zero model calls', runtime_revision=SOURCE))
        assert ledger.flush(timeout=1) is True
        retrieved, raw = factory.retrieve(metadata['artifact_id'])
        assert retrieved == metadata
        original_lines = ledger.path.read_text(encoding='utf-8').splitlines(keepends=True)
    finally:
        assert ledger.close() is True
    dispatch = dict(task_id=REVIEW_TASK, state='COMPLETED', artifact=metadata, model_calls=0,
        execution_model='DETERMINISTIC', agent_id='a26', capability='responsibility.a26',
        runtime_source_revision=SOURCE, review_action_id=action.action_id,
        review_action_durable=True, certification='UNVERIFIED')
    transport = dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
        artifact_http_status=200, runtime_source_revision=SOURCE, actual_runtime_image=IMAGE)
    state.review = dict(schema_version='prime.agent-certification.review.v1',
        reviewer_identity='a26', review_run_id=row['review_run_id'], source_revision=SOURCE,
        agent_id='a19', capability_id='responsibility.a19', dimension='baseline', test_case='identity',
        execution_evidence_sha256=sha(primary), test_result='PASS', review_test_version=ORACLE_ID,
        observations=dict(execution_task_id=TASK, result_sha256=join['result_sha256'],
            case_spec_sha256=join['case_spec_sha256'], runtime_image_id=IMAGE,
            registry_sha256=REGISTRY_BUILD_SHA, reviewer_code_revision=REVIEWER_CODE,
            oracle_id=ORACLE_ID, oracle_pass=True,
            reviewer_execution=dict(dispatch=dispatch, artifact_content_utf8=raw.decode('utf-8'),
                                    transport=transport, action_records=original_lines)))
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    encode = lambda value: base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()
    state.pin = dict(key_id=KEY, jwk=dict(kty='EC', crv='P-256', x=encode(point.x), y=encode(point.y)))
    def sign(digest):
        state.calls.append(digest)
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return KEY, r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    state.sign = sign
    persist(state)
    return state


def sign(state, **changes):
    options = dict(evidence_root=state.root, execution_sha256=state.row['evidence_sha256'],
        review_sha256=state.row['review_evidence_sha256'], execution_source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE, public_pin=state.pin,
        sign_digest=state.sign, now=NOW)
    options.update(changes)
    return sign_reviewed_case(state.row, **options)


def denied(state, **changes):
    with pytest.raises(CertificationReviewError):
        sign(state, **changes)
    assert state.calls == []


def test_real_temporary_reviewer_artifact_and_original_ledger_sign_one_identity_only(identity):
    assert set(identity.row) == _RECORD_FIELDS
    before = deepcopy(identity.row)
    primary_before = identity.primary
    review_before = identity.review_bytes
    signed = sign(identity)
    assert identity.row == before and identity.primary == primary_before and identity.review_bytes == review_before
    assert len(identity.calls) == 1 and type(identity.calls[0]) is bytes and len(identity.calls[0]) == 32
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: identity.pin['jwk']}})
    assert verifier(signed) is True
    assert signed['dimension'] == 'baseline' and signed['test_case'] == 'identity'
    assert signed['attestation']['algorithm'] == 'ES256'
    projected = AgentCertificationRegistry(identity.root, source_revision=SOURCE,
        verify_record=verifier)._project_from_rows('a19', 'responsibility.a19', NOW,
                                                 [signed], agent_record('a19'))
    assert projected['valid_cases'] == ['baseline:identity']
    assert projected['current_dimensions'] == [] and projected['level'] == 'L0'
    assert len(projected['missing_cases']) == 73 and projected['health'] == 'UNKNOWN'
    assert projected['trust_state'] != 'L7-CURRENT'


@pytest.mark.parametrize('field,value', [
    ('agent_id', 'a26'), ('capability_id', 'responsibility.a26'), ('dimension', 'role'),
    ('test_case', 'initialization'), ('executor_identity', 'a26'), ('verifier', 'a19'),
    ('authority_scope', 'Owner'), ('test_result', 'FAIL'), ('source_revision', 'd' * 40),
    ('review_source_revision', 'd' * 40), ('reviewer_code_revision', 'd' * 40),
    ('review_test_version', 'generic.pass.v1'), ('review_run_id', ''),
], ids=lambda value: str(value)[:35])
def test_record_source_case_self_review_and_authority_never_reach_signer(identity, field, value):
    identity.row[field] = value
    denied(identity)


@pytest.mark.parametrize('change', [
    lambda e: e['case_spec']['request'].update(context='noncanonical context'),
    lambda e: e['runtime'].update(source_revision='d' * 40),
    lambda e: e['runtime'].update(image_digest='sha256:' + 'd' * 64),
    lambda e: e['dispatch'].update(agent_id='a26'),
    lambda e: e['dispatch'].update(model_calls=False),
    lambda e: e['artifact_metadata'].update(runtime_revision='d' * 40),
    lambda e: e['artifact_metadata'].update(creator_agents=['a26']),
    lambda e: e['observation'].update(case_review='SELF_DECLARED_PASS'),
    lambda e: e['observation'].update(registry_sha256='d' * 64),
    lambda e: e['submission'][1]['steps'][0].update(capability='responsibility.a26'),
    lambda e: e['objective_read'][1]['execution_metadata'].update(jobs=[{'id': 'invented'}]),
    lambda e: e.update(action_records=[]),
    lambda e: e.update(private_extra='Bearer NEVER_EXPOSE_THIS'),
], ids=[f'original-event-{i}' for i in range(13)])
def test_rehashed_original_identity_mutations_never_reach_signer(identity, change):
    change(identity.execution)
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('change', [
    lambda r: r['registry'].update(agent_count=True),
    lambda r: r['registry'].update(agent_count=20),
    lambda r: r['registry'].update(source_sha256='d' * 64),
    lambda r: r['execution'].update(model_calls=False),
    lambda r: r['execution'].update(model_calls=1),
    lambda r: r['execution'].update(input_tokens=1),
    lambda r: r['execution'].update(fresh_inference_performed=0),
], ids=[f'rehashed-original-report-{i}' for i in range(7)])
def test_raw_report_semantics_reject_after_all_claimed_artifact_hashes_are_refreshed(identity, change):
    refresh_artifact(identity.execution, change)
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('review_action_durable', False), ('review_action_durable', 1), ('model_calls', False),
    ('model_calls', 1), ('agent_id', 'a19'), ('capability', 'responsibility.a19'),
    ('task_id', TASK), ('runtime_source_revision', 'd' * 40), ('certification', 'L7'),
    ('review_action_id', '66666666-6666-4666-8666-666666666666'),
])
def test_reviewer_dispatch_must_be_independent_zero_model_durable_and_current(identity, field, value):
    proof(identity)['dispatch'][field] = value
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('creator_agents', ['a19']), ('provenance', 'Caller declares PASS'),
    ('content_validation', 'L7 verified'), ('validation_state', 'PASS'),
    ('runtime_revision', 'd' * 40), ('bytes', True), ('location', '../artifact.json'),
    ('timestamp', stamp(1)),
])
def test_review_artifact_metadata_provenance_raw_size_and_time_are_required(identity, field, value):
    proof(identity)['dispatch']['artifact'][field] = value
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('reviewer_id', 'a19'), ('reviewer_capability_id', 'responsibility.a19'),
    ('subject_agent_id', 'a26'), ('source_revision', 'd' * 40),
    ('runtime_image_id', 'sha256:' + 'd' * 64), ('oracle_id', 'generic.pass.v1'),
    ('test_result', 'FAIL'), ('review_errors', ['missing_evidence']),
    ('model_calls', False), ('model_calls', 1), ('certification', 'L7'),
    ('subject_execution_verification', 'CALLER_DECLARED'), ('reviewed_at', stamp(1)),
    ('execution_evidence_sha256', 'd' * 64), ('review_nonce', False),
])
def test_rehashed_rechained_reviewer_content_cannot_invent_identity_or_case_pass(identity, field, value):
    mutate_reviewer_artifact(identity, lambda content: content.update({field: value}))
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('registry_sha256', 'd' * 64), ('subject_action_sha256', 'd' * 64),
    ('execution_metadata_sha256', 'd' * 64), ('artifact_id', 'd' * 32),
    ('task_id', REVIEW_TASK), ('completed_at', stamp(-0.1)),
])
def test_reviewer_domain_join_is_exact_original_identity_join(identity, field, value):
    mutate_reviewer_artifact(identity, lambda content: content['subject_domain_join'].update({field: value}))
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('change', [
    lambda e: e[0].update(agent_id='a19'),
    lambda e: e[0].update(classification='R1'),
    lambda e: e[-1].update(success=1),
    lambda e: e[-1].update(duration_ms=True),
    lambda e: e[-1].update(timestamp=stamp(1)),
    lambda e: e[-1]['result_summary'].update(sha256='d' * 64),
    lambda e: e[0].update(parameters_summary={'schema_version': SCHEMA, 'read_only_observations': 1}),
], ids=[f'rechained-review-action-{i}' for i in range(7)])
def test_original_reviewer_action_pair_requires_exact_semantics_not_only_chain_hash(identity, change):
    events = [json.loads(line) for line in proof(identity)['action_records']]
    change(events)
    rechain_reviewer(identity, events)
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('authentication', 'AGENT_AUTHENTICATED'), ('dispatch_http_status', True),
    ('dispatch_http_status', 200), ('artifact_http_status', False),
    ('runtime_source_revision', 'd' * 40), ('actual_runtime_image', 'sha256:' + 'd' * 64),
])
def test_identity_reviewer_transport_is_typed_authenticated_and_bound(identity, field, value):
    proof(identity)['transport'][field] = value
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('kind', ['missing', 'single', 'duplicate', 'broken-predecessor'])
def test_missing_or_non_original_reviewer_action_span_never_signs(identity, kind):
    lines = proof(identity)['action_records']
    if kind == 'missing':
        lines.clear()
    elif kind == 'single':
        lines.pop()
    elif kind == 'duplicate':
        lines.extend(deepcopy(lines))
    else:
        events = [json.loads(line) for line in lines]
        events[-1]['previous_sha256'] = 'f' * 64
        events[-1]['sha256'] = sha(canonical({k: v for k, v in events[-1].items() if k != 'sha256'}))
        lines[-1] = canonical(events[-1]).decode() + '\n'
    persist(identity)
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('expires_at', NOW.isoformat()), ('expires_at', stamp(-1)),
    ('last_revalidated', stamp(1)), ('certified_at', stamp(1)),
    ('certified_at', stamp(-4.1)), ('last_revalidated', '2026-10-07T12:00:00'),
])
def test_expired_future_naive_or_pre_review_records_never_call_signer(identity, field, value):
    identity.row[field] = value
    denied(identity)


@pytest.mark.parametrize('target', ['primary', 'review', 'review-artifact', 'action'])
def test_duplicate_json_fields_in_original_evidence_are_not_normalized(identity, target):
    if target in ('primary', 'review'):
        original = identity.primary if target == 'primary' else identity.review_bytes
        key = 'dispatch' if target == 'primary' else 'schema_version'
        raw = original.rstrip()[:-1] + (',"' + key + '":null}').encode()
        persist(identity, **{target: raw})
    elif target == 'review-artifact':
        raw = proof(identity)['artifact_content_utf8'].rstrip()[:-1] + ',"reviewer_id":"a19"}'
        proof(identity)['artifact_content_utf8'] = raw
        metadata = proof(identity)['dispatch']['artifact']
        metadata.update(sha256=sha(raw.encode()), bytes=len(raw.encode()))
        events = [json.loads(line) for line in proof(identity)['action_records']]
        events[-1]['result_summary']['sha256'] = metadata['sha256']
        rechain_reviewer(identity, events)
        persist(identity)
    else:
        proof(identity)['action_records'][0] = proof(identity)['action_records'][0].rstrip()[:-1] + ',"phase":"completed"}\n'
        persist(identity)
    denied(identity)


@pytest.mark.parametrize('file', ['execution.json', 'review.json'])
def test_missing_original_evidence_file_never_calls_signer(identity, file):
    (identity.root / 'a19' / file).unlink()
    denied(identity)


def test_original_raw_bytes_are_pinned_without_normalization(identity):
    before = identity.row['evidence_sha256']
    original = identity.primary
    (identity.root / 'a19' / 'execution.json').write_bytes(original + b'\n')
    assert sha(original + b'\n') != before
    denied(identity)


@pytest.mark.parametrize('field,value', [
    ('schema_version', 'untrusted.review.v1'), ('reviewer_identity', 'a19'),
    ('review_run_id', 'unbound-review'), ('source_revision', 'd' * 40),
    ('agent_id', 'a26'), ('capability_id', 'responsibility.a26'),
    ('dimension', 'role'), ('test_case', 'normal'), ('test_result', 'FAIL'),
    ('review_test_version', 'untrusted.oracle.v1'),
])
def test_identity_semantic_callback_cannot_bypass_common_protected_review_envelope(identity, field, value):
    identity.review[field] = value
    persist(identity)
    denied(identity)


def test_extra_common_review_field_is_not_signing_authority(identity):
    identity.review['signing_authority'] = 'OWNER_DECLARED'
    persist(identity)
    denied(identity)


def test_noncanonical_original_json_is_valid_only_with_exact_independent_byte_bindings(identity):
    raw = json.dumps(identity.execution, ensure_ascii=False, indent=2).encode()
    assert raw != identity.primary
    identity.primary = raw
    mutate_reviewer_artifact(identity, lambda content: content.update(execution_evidence_sha256=sha(raw)))
    persist(identity, primary=raw)
    signed = sign(identity)
    assert signed['evidence_sha256'] == sha(raw) and len(identity.calls) == 1
    assert (identity.root / 'a19' / 'execution.json').read_bytes() == raw


@pytest.mark.parametrize('option,value', [
    ('execution_source_revision', 'd' * 40), ('runtime_image_id', 'sha256:' + 'd' * 64),
    ('reviewer_code_revision', 'd' * 40), ('cloud_policy', {}),
    ('execution_sha256', 'd' * 64), ('review_sha256', 'd' * 64),
])
def test_external_protected_pins_and_no_cloud_variant_cannot_be_inferred(identity, option, value):
    denied(identity, **{option: value})


@pytest.mark.parametrize('field,value', [
    ('source_revision', 'd' * 40), ('evidence_sha256', 'd' * 64), ('verifier', 'a19'),
    ('review_evidence_sha256', 'd' * 64), ('test_case', 'initialization'),
    ('reviewer_code_revision', 'd' * 40), ('authority_scope', 'Owner'),
])
def test_signed_identity_tamper_is_rejected_by_pinned_public_verifier(identity, field, value):
    signed = sign(identity)
    signed[field] = value
    assert AzureES256CertificationVerifier({SERVICE: {KEY: identity.pin['jwk']}})(signed) is False


def test_signature_bytes_or_artifact_supplied_replacement_key_do_not_verify(identity):
    signed = sign(identity)
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: identity.pin['jwk']}})
    changed = deepcopy(signed)
    changed['attestation']['signature'] = '0' * 128
    assert verifier(changed) is False
    changed = deepcopy(signed)
    changed['attestation']['key_id'] = KEY[:-32] + 'a' * 32
    assert verifier(changed) is False
    assert AzureES256CertificationVerifier({})(signed) is False


def test_fixed_rejection_traceback_contains_no_private_artifact_text(identity):
    identity.execution['artifact_content_utf8'] = 'Bearer NEVER_EXPOSE_THIS'
    persist(identity)
    with pytest.raises(CertificationReviewError) as rejected:
        sign(identity)
    rendered = ''.join(traceback.format_exception(type(rejected.value), rejected.value,
                                                rejected.value.__traceback__))
    assert 'NEVER_EXPOSE_THIS' not in rendered and identity.calls == []
