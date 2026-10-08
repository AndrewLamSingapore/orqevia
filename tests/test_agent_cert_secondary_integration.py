"""Temporary synthetic domain/crypto integration, NEVER live agent evidence.

Primary model execution is an injected completed queue fixture with each
secondary's independently calculated answer. Actual temporary Objective reads,
registered deterministic reviewer dispatch, ArtifactFactory bytes, ActionLedger
records and the protected semantic signer are exercised. EC keys are ephemeral
test keys; there is no Azure call, production token, agent activation or L7 grant.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app import agent_dispatch_api as dispatch
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_role_review import canonical_role_spec, review_role_output
from app.agent_cert_secondary_roles import ORACLE_ID, CASE_VERSION, SUPPORTED_CAPABILITIES
from app.agent_certification import AgentCertificationRegistry
from app.agent_registry import agent_record
from app.artifact_factory import ArtifactFactory
from app.compute_catalog import task_tier
from app.tier_router import Tier, required_tier
from scripts.agent_cert_reviewed_signing import CertificationReviewError, SERVICE, sign_reviewed_case
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE
from tests.test_agent_cert_reviewed_signing import KEY, REVIEWER_CODE, canon, sha
from tests.test_agent_cert_secondary_roles import EXPECTED


def make_case(configured, monkeypatch, tmp_path, capability, answer=None):
    from app import compute_queue_api, objective_api
    actor = SUPPORTED_CAPABILITIES[capability]
    spec = canonical_role_spec(actor, capability)
    result = canon(EXPECTED[capability] if answer is None else answer).decode('utf-8')
    job_id, objective_id, correlation = (str(uuid.uuid4()) for _ in range(3))
    when = datetime.now(timezone.utc)
    original = dispatch.AgentRequest(**spec['request'])
    tier = max(Tier[original.minimum_tier], task_tier(original.objective, original.task_class),
               required_tier(original.objective, original.context))
    prompt = dispatch.packed_inference_prompt(original, tier, actor, correlation)
    job = dict(id=job_id, agent=actor, status='completed', result=result,
        provider='ollama-deep', model='fixture-model', attempts=1, error=None,
        allow_cloud=0, data_classification='LOCAL_ONLY', classification='R0',
        task_class=original.task_class, max_retries=0, prompt=prompt,
        created_at=(when - timedelta(seconds=3)).isoformat(),
        started_at=(when - timedelta(seconds=2)).isoformat(),
        completed_at=(when - timedelta(seconds=1)).isoformat())
    def get_job(key):
        if key != job_id:
            raise KeyError('SYNTHETIC_JOB_NOT_OWNED')
        return deepcopy(job)
    monkeypatch.setattr(compute_queue_api, 'queue', SimpleNamespace(get=get_job))
    db = objective_api.connect()
    db.execute('INSERT INTO objectives VALUES(?,?,?,?)', (objective_id,
        sha(original.objective.encode()), 'submitted', json.dumps([dict(capability=capability,
            dispatch=dict(job=dict(id=job_id, agent=actor), correlation_id=correlation))])))
    db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',
        (objective_id, 0, job['created_at'], job['completed_at']))
    objective_api.store_runtime(db, objective_id, 0)
    db.commit(); db.close()
    dispatched = []
    def submit_fixture(request):
        dispatched.append(deepcopy(request))
        return dict(capability=capability, job=deepcopy(job))
    observation = observe_cert_case(spec, dispatch=submit_fixture, get_job=get_job,
        pause=lambda _: pytest.fail('Completed fixture must not poll'), timeout_seconds=5)
    assert dispatched == [spec['request']]
    assert observation['state'] == 'EXECUTED' and observation['certification'] == 'UNVERIFIED'
    assert observation['case_review'] == ('SECONDARY_ROLE_CHECK_PASS' if answer is None else 'SECONDARY_ROLE_CHECK_FAIL')
    execution = dict(schema_version='prime.agent-certification.execution.v1',
        agent_id=actor, capability_id=capability, dimension='role', test_case='normal',
        source_revision=SOURCE, runtime_image_id=IMAGE, environment='LIVE_RUNTIME',
        executor_identity=actor, case_spec=spec,
        dispatch=dict(capability=capability, job=dict(id=job_id, agent=actor)),
        job={**{key: job[key] for key in ('id', 'agent', 'status', 'result', 'provider',
            'attempts', 'error', 'started_at', 'completed_at')}, 'result_sha256': sha(result.encode())},
        transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
            job_http_status=200, provider_locality='LOCAL', runtime_source_revision=SOURCE,
            actual_runtime_image=IMAGE))
    primary = canon(execution)
    reviewer = 'a18' if actor == 'a26' else 'a26'
    reviewer_capability = 'responsibility.a27' if actor == 'a26' else 'responsibility.a26'
    payload = dict(execution=execution, expected_execution_sha256=sha(primary),
        expected_source_revision=SOURCE, review_nonce=str(uuid.uuid4()),
        subject_objective_id=objective_id)
    request = dispatch.AgentRequest(capability=reviewer_capability,
        objective=dispatch.ROLE_REVIEW_OBJECTIVE, context=canon(payload).decode(),
        classification='R0', data_classification='LOCAL_ONLY', priority='low',
        max_cost_usd=0, deterministic_operation='certification_role_review')
    reviewed_dispatch = dispatch.dispatch_request(request, 'fixture-owner')
    assert reviewed_dispatch['agent_id'] == reviewer != actor
    assert reviewed_dispatch['capability'] == reviewer_capability
    assert reviewed_dispatch['model_calls'] == 0 and reviewed_dispatch['review_action_durable'] is True
    metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(
        reviewed_dispatch['artifact']['artifact_id'])
    assert metadata == reviewed_dispatch['artifact'] and metadata['sha256'] == sha(raw)
    artifact = json.loads(raw)
    action_records = configured.ledger.path.read_text(encoding='utf-8').splitlines(keepends=True)
    assert len(action_records) == 2
    assert [json.loads(line)['phase'] for line in action_records] == ['started', 'completed']
    assert all(json.loads(line)['task_id'] == reviewed_dispatch['task_id'] for line in action_records)
    certified = datetime.now(timezone.utc)
    run_id = 'synthetic-secondary-review-' + uuid.uuid4().hex
    row = dict(agent_id=actor, capability_id=capability, dimension='role', test_case='normal',
        certification_test='secondary-role-normal', test_version=CASE_VERSION, test_result='PASS',
        verifier=reviewer, executor_identity=actor, evidence='execution.json', evidence_sha256=sha(primary),
        certified_at=certified.isoformat(), last_revalidated=certified.isoformat(),
        expires_at=(certified + timedelta(hours=1)).isoformat(), source_revision=SOURCE,
        authority_scope=agent_record(actor)['authority'], review_evidence='review.json',
        review_evidence_sha256='', review_run_id=run_id, review_test_version=ORACLE_ID,
        review_source_revision=SOURCE, reviewer_code_revision=REVIEWER_CODE)
    proof = dict(dispatch=reviewed_dispatch, artifact_content_utf8=raw.decode(),
        transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
            artifact_http_status=200, runtime_source_revision=SOURCE, actual_runtime_image=IMAGE),
        action_records=action_records)
    review = dict(schema_version='prime.agent-certification.review.v1',
        reviewer_identity=reviewer, review_run_id=run_id, source_revision=SOURCE,
        agent_id=actor, capability_id=capability, dimension='role', test_case='normal',
        execution_evidence_sha256=sha(primary), test_result='PASS', review_test_version=ORACLE_ID,
        observations=dict(execution_job_id=job_id, result_sha256=sha(result.encode()),
            case_spec_sha256=sha(canon(spec)), runtime_image_id=IMAGE,
            reviewer_code_revision=REVIEWER_CODE, oracle_id=ORACLE_ID,
            oracle_pass=True, reviewer_execution=proof))
    root = tmp_path / 'secondary-signing-evidence'
    (root / actor).mkdir(parents=True)
    private = ec.generate_private_key(ec.SECP256R1())  # Ephemeral TEST key only.
    point = private.public_key().public_numbers()
    encode = lambda n: base64.urlsafe_b64encode(n.to_bytes(32, 'big')).rstrip(b'=').decode()
    pin = dict(key_id=KEY, jwk=dict(kty='EC', crv='P-256', x=encode(point.x), y=encode(point.y)))
    calls = []
    def sign(digest):
        calls.append(digest)
        r, s = utils.decode_dss_signature(private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
        return KEY, r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    state = SimpleNamespace(row=row, execution=execution, review=review, root=root,
        primary=primary, artifact=artifact, proof=proof, observation=observation,
        source_objective=objective_id, job=job, pin=pin, calls=calls, sign=sign, now=certified)
    persist(state)
    return state


def persist(state):
    state.primary = canon(state.execution)
    state.row['evidence_sha256'] = sha(state.primary)
    state.review['execution_evidence_sha256'] = sha(state.primary)
    review = canon(state.review)
    state.row['review_evidence_sha256'] = sha(review)
    folder = state.root / state.row['agent_id']
    (folder / 'execution.json').write_bytes(state.primary)
    (folder / 'review.json').write_bytes(review)


def sign_case(state):
    return sign_reviewed_case(state.row, evidence_root=state.root,
        execution_sha256=state.row['evidence_sha256'], review_sha256=state.row['review_evidence_sha256'],
        execution_source_revision=SOURCE, runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE,
        public_pin=state.pin, sign_digest=state.sign, now=state.now)


@pytest.mark.parametrize('capability', tuple(SUPPORTED_CAPABILITIES))
def test_eight_secondary_temporary_domain_review_sign_verify_tamper_not_l7(configured, monkeypatch, tmp_path, capability):
    state = make_case(configured, monkeypatch, tmp_path, capability)
    assert state.execution['case_spec'] == canonical_role_spec(state.row['agent_id'], capability)
    assert review_role_output(state.row['agent_id'], capability, state.job['result']) == (True, ())
    assert state.artifact['oracle_id'] == ORACLE_ID
    assert state.artifact['subject_capability_id'] == capability
    assert state.artifact['subject_domain_join']['objective_id'] == state.source_objective
    assert state.artifact['subject_execution_verification'] == 'QUEUE_AND_OBJECTIVE_JOINED'
    assert state.artifact['test_result'] == 'PASS' and state.artifact['certification'] == 'UNVERIFIED'
    signed = sign_case(state)
    assert len(state.calls) == 1
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state.pin['jwk']}})
    assert verifier(signed) is True
    assert verifier({**signed, 'capability_id': 'responsibility.' + state.row['agent_id']}) is False
    assert verifier({**signed, 'verifier': state.row['agent_id']}) is False
    assert verifier({**signed, 'evidence_sha256': '0' * 64}) is False
    projection = AgentCertificationRegistry(state.root, source_revision=SOURCE,
        verify_record=verifier)._project_from_rows(state.row['agent_id'], capability,
            state.now, [signed], agent_record(state.row['agent_id']))
    assert projection['valid_cases'] == ['role:normal']
    assert len(projection['missing_cases']) == 73 and projection['level'] == 'L0'
    assert projection['health'] == 'UNKNOWN' and projection['trust_state'] != 'L7-CURRENT'


@pytest.mark.parametrize('capability', tuple(SUPPORTED_CAPABILITIES))
def test_bad_secondary_oracle_result_never_reaches_ephemeral_signer(configured, monkeypatch, tmp_path, capability):
    answer = deepcopy(EXPECTED[capability]); answer['actions_executed'] = True
    state = make_case(configured, monkeypatch, tmp_path, capability, answer)
    assert state.observation['case_review'] == 'SECONDARY_ROLE_CHECK_FAIL'
    assert state.artifact['test_result'] == 'FAIL'
    with pytest.raises(CertificationReviewError):
        sign_case(state)
    assert state.calls == []


@pytest.mark.parametrize('mutation', ['primary_capability', 'wrong_owner', 'self_reviewer',
    'missing_original_actions', 'source', 'oracle_version', 'raw_answer'])
def test_secondary_scope_action_provenance_and_oracle_negatives(configured, monkeypatch, tmp_path, mutation):
    state = make_case(configured, monkeypatch, tmp_path, 'responsibility.a03')
    if mutation == 'primary_capability':
        state.row['capability_id'] = 'responsibility.a02'
    elif mutation == 'wrong_owner':
        state.execution['agent_id'] = 'a03'
    elif mutation == 'self_reviewer':
        state.row['verifier'] = 'a02'
    elif mutation == 'missing_original_actions':
        state.proof['action_records'].pop()
    elif mutation == 'source':
        state.execution['source_revision'] = 'f' * 40
    elif mutation == 'oracle_version':
        state.review['observations']['oracle_id'] = 'existing.role-normal.v1'
    else:
        state.execution['job']['result'] = json.dumps({'copied_primary_answer': True})
        state.execution['job']['result_sha256'] = sha(state.execution['job']['result'].encode())
    persist(state)
    with pytest.raises(CertificationReviewError):
        sign_case(state)
    assert state.calls == []
