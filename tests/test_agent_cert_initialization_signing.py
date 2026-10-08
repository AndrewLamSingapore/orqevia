"""Temporary actual event/reviewer joins and ephemeral signing; NOT live/L7.

The owned initializer and registered reviewer run against temporary domains.
No model, production identity, Azure operation or installed trust key is used.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_identity_review import canonical, sha, read_action_span
from app.agent_cert_initialization_review import ORACLE_ID
from app.agent_certification import AgentCertificationRegistry
from app.agent_registry import REGISTRY_PATH, agent_record
from app.artifact_factory import ArtifactFactory
from scripts.agent_cert_reviewed_signing import CertificationReviewError, SERVICE, sign_reviewed_case
from tests.test_agent_cert_initialization_dispatch import configured, event, initialization, run
from tests.test_agent_cert_review_dispatch import SOURCE, IMAGE
from tests.test_agent_cert_reviewed_signing import fixture as ephemeral_key, REVIEWER_CODE, KEY


@pytest.fixture
def signed_input(initialization, tmp_path):
    result = run(initialization)
    metadata, raw = ArtifactFactory(initialization.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    assert metadata == result['artifact']
    content = json.loads(raw)
    join = content['subject_domain_join']
    primary = canonical(initialization.payload['execution'])
    now = datetime.now(timezone.utc)
    row = dict(agent_id='a19', capability_id='responsibility.a19', dimension='baseline',
        test_case='initialization', certification_test='baseline-initialization', test_version=ORACLE_ID,
        test_result='PASS', verifier='a26', executor_identity='a19', evidence='execution.json',
        evidence_sha256=sha(primary), certified_at=now.isoformat(), last_revalidated=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(), source_revision=SOURCE,
        authority_scope=agent_record('a19')['authority'], review_evidence='review.json',
        review_evidence_sha256='', review_run_id='temporary-owned-initialization-review',
        review_test_version=ORACLE_ID, review_source_revision=SOURCE, reviewer_code_revision=REVIEWER_CODE)
    # Preserve the full original subject+review ledger. Sign only the review's
    # original owned endpoint span, never a reconstructed or rehashed pair.
    ledger_before = initialization.ledger.path.read_bytes()
    lines = read_action_span(initialization.ledger.path, result['task_id'],
                             'agent.certification.initialization.review')
    assert initialization.ledger.path.read_bytes() == ledger_before
    review = dict(schema_version='prime.agent-certification.review.v1', reviewer_identity='a26',
        review_run_id=row['review_run_id'], source_revision=SOURCE, agent_id='a19',
        capability_id='responsibility.a19', dimension='baseline', test_case='initialization',
        execution_evidence_sha256=sha(primary), test_result='PASS', review_test_version=ORACLE_ID,
        observations=dict(execution_task_id=join['task_id'], result_sha256=join['result_sha256'],
            case_spec_sha256=join['case_spec_sha256'], runtime_image_id=IMAGE,
            registry_sha256=sha(REGISTRY_PATH.read_bytes()), reviewer_code_revision=REVIEWER_CODE,
            oracle_id=ORACLE_ID, oracle_pass=True, reviewer_execution=dict(dispatch=result,
                artifact_content_utf8=raw.decode(), action_records=lines,
                transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
                    artifact_http_status=200, runtime_source_revision=SOURCE, actual_runtime_image=IMAGE))))
    root = tmp_path / 'owned-initialization-signing'
    (root / 'a19').mkdir(parents=True)
    key = ephemeral_key(tmp_path / 'ephemeral-key-only')
    state = SimpleNamespace(row=row, execution=initialization.payload['execution'], review=review,
        root=root, pin=key['pin'], sign=key['sign'], calls=key['calls'], now=now)
    persist(state)
    return state


def persist(state):
    primary = canonical(state.execution)
    state.row['evidence_sha256'] = sha(primary)
    state.review['execution_evidence_sha256'] = sha(primary)
    reviewed = canonical(state.review)
    state.row['review_evidence_sha256'] = sha(reviewed)
    (state.root / 'a19' / 'execution.json').write_bytes(primary)
    (state.root / 'a19' / 'review.json').write_bytes(reviewed)


def sign(state, **changes):
    options = dict(evidence_root=state.root, execution_sha256=state.row['evidence_sha256'],
        review_sha256=state.row['review_evidence_sha256'], execution_source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE,
        public_pin=state.pin, sign_digest=state.sign, now=state.now)
    return sign_reviewed_case(state.row, **{**options, **changes})


def denied(state):
    with pytest.raises(CertificationReviewError):
        sign(state)
    assert state.calls == []


def test_actual_temporary_initialization_review_sign_verify_tamper_remains_one_case(signed_input):
    state = signed_input
    original = deepcopy(state.row)
    signed = sign(state)
    assert len(state.calls) == 1 and state.row == original
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state.pin['jwk']}})
    assert verifier(signed) is True
    assert verifier({**signed, 'test_case': 'identity'}) is False
    projected = AgentCertificationRegistry(state.root, source_revision=SOURCE,
        verify_record=verifier)._project_from_rows('a19', 'responsibility.a19', state.now,
                                                  [signed], agent_record('a19'))
    assert projected['valid_cases'] == ['baseline:initialization']
    assert len(projected['missing_cases']) == 73 and projected['level'] == 'L0'
    assert projected['health'] == 'UNKNOWN' and projected['trust_state'] != 'L7-CURRENT'


@pytest.mark.parametrize('field,value', [
    ('test_case', 'identity'), ('dimension', 'role'), ('capability_id', 'responsibility.a25'),
    ('verifier', 'a19'), ('executor_identity', 'a26'), ('review_test_version', 'generic.pass.v1'),
    ('review_source_revision', 'a' * 40), ('authority_scope', 'Owner')])
def test_record_case_actor_and_authority_cannot_be_relabelled(signed_input, field, value):
    signed_input.row[field] = value
    denied(signed_input)


@pytest.mark.parametrize('change', [
    lambda e: e['dispatch'].update(model_calls=False),
    lambda e: e['artifact_metadata'].update(creator_agents=['a26']),
    lambda e: e['runtime'].update(image_digest='sha256:' + 'a' * 64),
    lambda e: e['case_spec'].update(case='baseline:identity'),
    lambda e: e['objective_read'][1]['execution_metadata'].update(jobs=[{'id': 'invented'}]),
    lambda e: e.update(action_records=[]),
    lambda e: e['observation'].update(registry_sha256='a' * 64),
])
def test_rehashed_subject_mutations_do_not_create_initialized_pass(signed_input, change):
    change(signed_input.execution)
    persist(signed_input)
    denied(signed_input)


@pytest.mark.parametrize('field,value', [('oracle_pass', 1), ('oracle_id', 'generic.pass.v1'),
    ('registry_sha256', 'a' * 64), ('execution_task_id', '11111111-1111-4111-8111-111111111111')])
def test_rehashed_review_observations_fail_closed(signed_input, field, value):
    signed_input.review['observations'][field] = value
    persist(signed_input)
    denied(signed_input)


@pytest.mark.parametrize('target', ['undurable', 'wrong-actor', 'identity-action', 'wrong-schema', 'missing-pair'])
def test_real_reviewer_event_cannot_be_replaced_with_identity_or_missing_originals(signed_input, target):
    proof = signed_input.review['observations']['reviewer_execution']
    if target == 'undurable':
        proof['dispatch']['review_action_durable'] = False
    elif target == 'wrong-actor':
        proof['dispatch']['agent_id'] = 'a19'
    elif target == 'identity-action':
        proof['action_records'] = [line.replace('initialization.review', 'identity.review')
                                   for line in proof['action_records']]
    elif target == 'wrong-schema':
        content = json.loads(proof['artifact_content_utf8'])
        content['schema_version'] = 'prime.agent-cert-identity-review.v1'
        proof['artifact_content_utf8'] = canonical(content).decode()
    else:
        proof['action_records'] = []
    persist(signed_input)
    denied(signed_input)


def test_event_case_cannot_be_silently_given_cloud_authority(signed_input):
    with pytest.raises(CertificationReviewError, match='IDENTITY_CLOUD_TRANSPORT_FORBIDDEN'):
        sign(signed_input, cloud_binding={})
    assert signed_input.calls == []
