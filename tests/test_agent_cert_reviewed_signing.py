"""Synthetic artifact and ephemeral-key tests; no Azure/GitHub/live execution."""
import base64
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
import traceback

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_cases import challenge
from app.agent_cert_role_g1 import SOURCES, role_facts
from app.agent_cert_role_group_two import _CASES as GROUP_TWO_CASES, role_case as group_two_role_case
from app.agent_cert_role_review import canonical_role_spec, review_role_output
from app.agent_registry import agent_record, registered_agent_ids
from app.agent_cert_numeric import priority_facts
from app.agent_cert_weighted import weighted_facts
from app.agent_cert_rates import rate_facts
from app.agent_cert_data_quality import data_quality_facts
from app.agent_cert_portfolio import portfolio_facts
from app.agent_cert_cost import cost_facts
from app.agent_cert_risk import risk_facts
from app.agent_cert_release import release_facts
from app.agent_cert_execution import (_A01_SOURCE, _A04_SOURCE, _A05_SOURCE,
    _A12_SOURCE, _A14_SOURCE, _A21_SOURCE, _A28_SOURCE, _A29_SOURCE)
from scripts.agent_cert_reviewed_signing import (
    CertificationReviewError, SERVICE, sign_reviewed_case,
)


NOW = datetime(2026, 10, 7, 8, tzinfo=timezone.utc)
EXECUTION_SOURCE = 'd' * 40
REVIEWER_CODE = 'f' * 40
IMAGE = 'sha256:' + 'a' * 64
JOB = '11111111-1111-4111-8111-111111111111'
REVIEW_TASK = '22222222-2222-4222-8222-222222222222'
REVIEW_ACTION = '33333333-3333-4333-8333-333333333333'
SUBJECT_OBJECTIVE = '44444444-4444-4444-8444-444444444444'
REVIEW_NONCE = '55555555-5555-4555-8555-555555555555'
KEY = 'https://samplevault.vault.azure.net/keys/test-key/' + 'b' * 32
ANSWER = {'required_zero_result': True, 'buggy_zero_result': False,
          'corrected_zero_result': True, 'negative_one_result': False,
          'positive_one_result': True, 'corrected_condition': 'n >= 0',
          'discriminating_assertion': 'assert is_nonnegative(0) is True',
          'tests_executed': False}


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture(tmp_path, agent='a18', answer=None):
    # The numeric oracle exposes exact Fraction facts; its output contract
    # requires reduced fraction strings, never floats or arithmetic expressions.
    source_answer = ANSWER if answer is None else answer
    serialized_answer = {key: f'{value.numerator}/{value.denominator}' if isinstance(value, Fraction) else value
                         for key, value in source_answer.items()}
    raw = json.dumps(serialized_answer, ensure_ascii=False)
    spec = group_two_role_case(agent) if agent in GROUP_TWO_CASES else challenge(
        'role:normal', agent_id=agent, capability_id=f'responsibility.{agent}')
    oracle_id = 'group_two_exact_role_oracle/v1' if agent in GROUP_TWO_CASES else 'existing.role-normal.v1'
    review_version = 'group_two_exact_role_oracle.v1' if agent in GROUP_TWO_CASES else 'oracle.1'
    execution = {'schema_version': 'prime.agent-certification.execution.v1',
        'agent_id': agent, 'capability_id': f'responsibility.{agent}',
        'dimension': 'role', 'test_case': 'normal', 'source_revision': EXECUTION_SOURCE,
        'runtime_image_id': IMAGE, 'environment': 'LIVE_RUNTIME',
        'executor_identity': agent, 'case_spec': spec,
        'dispatch': {'capability': f'responsibility.{agent}', 'job': {'id': JOB, 'agent': agent}},
        'job': {'id': JOB, 'agent': agent, 'status': 'completed', 'result': raw,
                'result_sha256': sha(raw.encode()), 'provider': 'ollama-deep', 'attempts': 1,
                'started_at': (NOW - timedelta(seconds=2)).isoformat(),
                'completed_at': (NOW - timedelta(seconds=1)).isoformat(), 'error': None},
        'transport': {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
                      'job_http_status': 200, 'provider_locality': 'LOCAL',
                      'runtime_source_revision': EXECUTION_SOURCE, 'actual_runtime_image': IMAGE}}
    reviewer = 'a26' if agent != 'a26' else 'a18'
    row = {'agent_id': agent, 'capability_id': f'responsibility.{agent}',
           'dimension': 'role', 'test_case': 'normal', 'certification_test': 'role-normal',
           'test_version': '1', 'test_result': 'PASS', 'verifier': reviewer,
           'executor_identity': agent, 'evidence': 'execution.json', 'evidence_sha256': '',
           'certified_at': NOW.isoformat(), 'last_revalidated': NOW.isoformat(),
           'expires_at': (NOW + timedelta(hours=1)).isoformat(),
           'source_revision': EXECUTION_SOURCE, 'authority_scope': agent_record(agent)['authority'],
           'review_evidence': 'review.json', 'review_evidence_sha256': '',
           'review_run_id': 'synthetic-protected-review-123', 'review_test_version': review_version,
           'review_source_revision': EXECUTION_SOURCE, 'reviewer_code_revision': REVIEWER_CODE}
    review = {'schema_version': 'prime.agent-certification.review.v1',
              'reviewer_identity': reviewer, 'review_run_id': row['review_run_id'],
              'source_revision': EXECUTION_SOURCE, 'agent_id': agent,
              'capability_id': row['capability_id'], 'dimension': 'role', 'test_case': 'normal',
              'execution_evidence_sha256': '', 'test_result': 'PASS',
              'review_test_version': review_version,
              'observations': {'execution_job_id': JOB, 'result_sha256': sha(raw.encode()),
                               'case_spec_sha256': sha(canon(spec)), 'runtime_image_id': IMAGE,
                               'reviewer_code_revision': REVIEWER_CODE,
                               'oracle_id': oracle_id, 'oracle_pass': True}}
    root = tmp_path / 'evidence'
    (root / agent).mkdir(parents=True)
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    encode = lambda n: base64.urlsafe_b64encode(n.to_bytes(32, 'big')).rstrip(b'=').decode()
    pin = {'key_id': KEY, 'jwk': {'kty': 'EC', 'crv': 'P-256', 'x': encode(point.x), 'y': encode(point.y)}}
    calls = []
    def sign(digest):
        calls.append(digest)
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return KEY, r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    state = {'row': row, 'execution': execution, 'review': review, 'root': root, 'pin': pin,
             'calls': calls, 'sign': sign}
    # Explicit synthetic artifact/action fixtures, never actual reviewer proof.
    # Live callers must capture these independently from the owning runtime.
    review['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    return state


def mocked_reviewer_execution(state):
    execution, row = state['execution'], state['row']
    reviewer = row['verifier']
    cap = 'responsibility.a27' if row['agent_id'] == 'a26' else 'responsibility.a26'
    timestamp = lambda milliseconds: (NOW - timedelta(milliseconds=milliseconds)).isoformat()
    content = {
        'schema_version': 'prime.agent-cert-role-review.v1', 'task_id': REVIEW_TASK,
        'reviewer_id': reviewer, 'reviewer_capability_id': cap,
        'subject_agent_id': row['agent_id'], 'subject_capability_id': row['capability_id'],
        'dimension': 'role', 'test_case': 'normal', 'source_revision': EXECUTION_SOURCE,
        'runtime_image_id': IMAGE, 'subject_job_id': JOB, 'review_nonce': REVIEW_NONCE,
        'reviewed_at': timestamp(800), 'execution_evidence_sha256': sha(canon(execution)),
        'case_spec_sha256': sha(canon(execution['case_spec'])),
        'result_sha256': execution['job']['result_sha256'],
        'oracle_id': state['review']['observations']['oracle_id'], 'test_result': 'PASS',
        'review_errors': [], 'model_calls': 0, 'execution_model': 'DETERMINISTIC',
        'subject_execution_verification': 'QUEUE_AND_OBJECTIVE_JOINED', 'certification': 'UNVERIFIED',
        'subject_domain_join': {'objective_id': SUBJECT_OBJECTIVE, 'objective_revision': 0,
            'job_id': JOB, 'runtime': {'host_id': 'ABEX', 'source_revision': EXECUTION_SOURCE,
                'version': 'fixture-current', 'image_digest': IMAGE},
            'observed_at': timestamp(700), 'execution_metadata_sha256': 'c' * 64,
            'prompt_sha256': 'b' * 64, 'case_spec_sha256': sha(canon(execution['case_spec']))},
    }
    raw = json.dumps(content)  # Preserve actual-factory noncanonical byte format.
    metadata = {'artifact_id': 'e' * 32, 'task_id': REVIEW_TASK, 'type': 'json',
        'creator_agents': [reviewer], 'timestamp': timestamp(300), 'version': '1.0.0',
        'provenance': 'Deterministic computation; zero model calls',
        'runtime_revision': EXECUTION_SOURCE, 'validation_state': 'STRUCTURE_VALIDATED',
        'content_validation': 'Not independently established by structural validation',
        'location': 'artifact.json', 'sha256': sha(raw.encode()), 'bytes': len(raw.encode()),
        'delivery_state': 'AVAILABLE'}
    dispatch = {'task_id': REVIEW_TASK, 'state': 'COMPLETED', 'artifact': metadata,
        'model_calls': 0, 'execution_model': 'DETERMINISTIC', 'agent_id': reviewer,
        'capability': cap, 'runtime_source_revision': EXECUTION_SOURCE,
        'review_action_id': REVIEW_ACTION, 'review_action_durable': True, 'certification': 'UNVERIFIED'}
    base = {'task_id': REVIEW_TASK, 'agent_id': reviewer,
        'action_type': 'agent.certification.role.review', 'tool': 'artifact-factory', 'target': '',
        'classification': 'R0', 'parameters_summary': {'schema_version': content['schema_version'],
            'read_only_observations': True}, 'model_backend': 'deterministic',
        'execution_location': 'local', 'parent_agent': None, 'workflow_id': None, 'action_id': REVIEW_ACTION}
    start = dict(base, phase='started', timestamp=timestamp(500), sequence=10, previous_sha256='0' * 64)
    start['sha256'] = sha(canon(start))
    completed = dict(base, phase='completed', timestamp=timestamp(100), sequence=11,
        previous_sha256=start['sha256'], success=True, duration_ms=400.0,
        result_summary={'type': 'dict', 'artifact_id': metadata['artifact_id'],
            'sha256': metadata['sha256'], 'location': 'artifact.json'})
    completed['sha256'] = sha(canon(completed))
    return {'dispatch': dispatch, 'artifact_content_utf8': raw,
        'transport': {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
            'artifact_http_status': 200, 'runtime_source_revision': EXECUTION_SOURCE, 'actual_runtime_image': IMAGE},
        'action_records': [json.dumps(start), json.dumps(completed)]}


def persist(state):
    primary = canon(state['execution'])
    state['row']['evidence_sha256'] = sha(primary)
    state['review']['execution_evidence_sha256'] = sha(primary)
    reviewed = canon(state['review'])
    state['row']['review_evidence_sha256'] = sha(reviewed)
    subject = state['root'] / state['row']['agent_id']
    (subject / 'execution.json').write_bytes(primary)
    (subject / 'review.json').write_bytes(reviewed)


def run(state, **kwargs):
    options = {'evidence_root': state['root'], 'execution_sha256': state['row']['evidence_sha256'],
               'review_sha256': state['row']['review_evidence_sha256'],
               'execution_source_revision': EXECUTION_SOURCE, 'runtime_image_id': IMAGE,
               'reviewer_code_revision': REVIEWER_CODE, 'public_pin': state['pin'],
               'sign_digest': state['sign'], 'now': NOW}
    return sign_reviewed_case(state['row'], **dict(options, **kwargs))


def test_one_case_sign_verify_tamper_and_distinct_source_provenance(tmp_path):
    state = fixture(tmp_path)
    signed = run(state)
    assert len(state['calls']) == 1
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state['pin']['jwk']}})
    assert verifier(signed)
    assert not verifier(dict(signed, reviewer_code_revision=EXECUTION_SOURCE))
    assert signed['source_revision'] == signed['review_source_revision'] == EXECUTION_SOURCE
    assert signed['reviewer_code_revision'] == REVIEWER_CODE
    assert 'l7_status' not in signed and 'result' not in signed


@pytest.mark.parametrize('agent', sorted(SOURCES))
def test_six_distinct_existing_group_one_oracles(tmp_path, agent):
    state = fixture(tmp_path, agent, role_facts(agent, SOURCES[agent]))
    assert run(state)['agent_id'] == agent
    assert len(state['calls']) == 1


@pytest.mark.parametrize('agent,answer', [
    ('a01', priority_facts(_A01_SOURCE)), ('a04', weighted_facts(_A04_SOURCE)),
    ('a05', portfolio_facts(_A05_SOURCE)), ('a12', rate_facts(_A12_SOURCE)),
    ('a14', data_quality_facts(_A14_SOURCE)), ('a21', cost_facts(_A21_SOURCE)),
    ('a28', risk_facts(_A28_SOURCE)), ('a29', release_facts(_A29_SOURCE)),
    ('a17', {'type_guard': 'type(n) is int', 'accepted_range': '0 <= n <= 9',
             'zero_result': 0, 'nine_result': 9, 'negative_one_error': True,
             'ten_error': True, 'string_error': True, 'float_error': True, 'tests_executed': False}),
])
def test_other_nine_scoped_oracles_use_their_own_domain_inputs(tmp_path, agent, answer):
    state = fixture(tmp_path, agent, answer)
    assert run(state)['agent_id'] == agent
    assert len(state['calls']) == 1


@pytest.mark.parametrize('answer', [dict(ANSWER, discriminating_assertion='assert is_nonnegative(0) is False'),
                                  dict(ANSWER, tests_executed=True), dict(ANSWER, required_zero_result=False)])
def test_failed_original_boundary_answers_cannot_sign_self_declared_pass(tmp_path, answer):
    state = fixture(tmp_path, answer=answer)
    with pytest.raises(CertificationReviewError, match='CASE_ORACLE_FAILED'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'agent_id': 'a17'}, {'source_revision': 'e' * 40}, {'runtime_image_id': 'sha256:' + 'b' * 64},
    {'environment': 'SIMULATION'}, {'executor_identity': 'a26'}, {'dimension': 'general'},
])
def test_false_execution_metadata_denied_even_if_all_candidate_hashes_updated(tmp_path, change):
    state = fixture(tmp_path)
    state['execution'].update(change)
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('mutate', [
    lambda e: e['case_spec']['request'].update(data_classification='CLOUD_PERMITTED'),
    lambda e: e['case_spec']['request'].update(context='different source'),
    lambda e: e['transport'].update(provider_locality='CLOUD'),
    lambda e: e['transport'].update(dispatch_http_status=202.0),
    lambda e: e['transport'].update(job_http_status=True),
    lambda e: e['job'].update(attempts=True),
    lambda e: e['job'].update(status='failed'),
    lambda e: e['job'].update(result_sha256='0' * 64),
    lambda e: e['job'].update(completed_at=(NOW + timedelta(seconds=1)).isoformat()),
    lambda e: e['dispatch']['job'].update(id='22222222-2222-4222-8222-222222222222'),
])
def test_strict_challenge_live_transport_job_and_literal_joins(tmp_path, mutate):
    state = fixture(tmp_path)
    mutate(state['execution'])
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'verifier': 'a18'}, {'verifier': 'not-registered'}, {'executor_identity': 'a26'},
    {'authority_scope': 'owner'}, {'test_result': 'FAIL'}, {'test_case': 'edge'},
    {'review_source_revision': REVIEWER_CODE}, {'reviewer_code_revision': EXECUTION_SOURCE},
    {'review_evidence': 'execution.json'}, {'test_version': ''},
    {'certified_at': (NOW - timedelta(seconds=3)).isoformat()},
])
def test_invalid_record_never_calls_key_vault(tmp_path, change):
    state = fixture(tmp_path)
    state['row'].update(change)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'reviewer_identity': 'a18'}, {'review_run_id': 'different-run'},
    {'test_result': 'FAIL'}, {'source_revision': REVIEWER_CODE},
    {'execution_evidence_sha256': '0' * 64},
])
def test_distinct_independent_review_artifact_exact_binding(tmp_path, change):
    state = fixture(tmp_path)
    state['review'].update(change)
    persist(state)
    if 'execution_evidence_sha256' in change:
        state['review'].update(change)
        raw = canon(state['review'])
        (state['root'] / 'a18' / 'review.json').write_bytes(raw)
        state['row']['review_evidence_sha256'] = sha(raw)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


def test_fenced_model_answer_is_not_coerced_into_strict_json(tmp_path):
    state = fixture(tmp_path)
    result = '```json\n' + state['execution']['job']['result'] + '\n```'
    state['execution']['job'].update(result=result, result_sha256=sha(result.encode()))
    state['review']['observations']['result_sha256'] = sha(result.encode())
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


def test_nested_number_types_do_not_collapse_under_python_list_equality(tmp_path):
    answer = role_facts('a13', SOURCES['a13'])
    answer['weekly_units'][0] = 10.0
    state = fixture(tmp_path, 'a13', answer)
    with pytest.raises(CertificationReviewError, match='CASE_ORACLE_FAILED'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'PRIVATE_RESULT_ERROR'])
def test_duplicate_nonfinite_and_raw_payload_errors_are_sanitized(tmp_path, raw):
    state = fixture(tmp_path)
    (state['root'] / 'a18' / 'execution.json').write_bytes(raw)
    state['row']['evidence_sha256'] = sha(raw)
    with pytest.raises(CertificationReviewError) as error:
        run(state)
    assert 'PRIVATE_RESULT' not in str(error.value) and state['calls'] == []


def test_external_protected_pin_mismatch_not_taken_from_candidate_record(tmp_path):
    state = fixture(tmp_path)
    with pytest.raises(CertificationReviewError, match='APPROVED_ARTIFACT_MISMATCH'):
        run(state, execution_sha256='0' * 64)
    assert state['calls'] == []


def test_unrelated_role_answer_is_not_given_a_generic_oracle(tmp_path):
    state = fixture(tmp_path, 'a20', ANSWER)
    with pytest.raises(CertificationReviewError, match='CASE_ORACLE_FAILED'):
        run(state)
    assert state['calls'] == []


def test_wrong_signature_key_or_secret_error_is_not_exported(tmp_path):
    state = fixture(tmp_path)
    with pytest.raises(CertificationReviewError, match='REVIEWED_CASE_SIGNING_REJECTED'):
        run(state, sign_digest=lambda digest: (KEY, b'x' * 64))
    def private_failure(digest):
        raise RuntimeError('PRIVATE_SYNTHETIC_SECRET_ERROR')
    with pytest.raises(CertificationReviewError) as error:
        run(state, sign_digest=private_failure)
    assert 'PRIVATE_' not in str(error.value) and error.value.__cause__ is None
    assert 'PRIVATE_SYNTHETIC_SECRET_ERROR' not in ''.join(traceback.format_exception(error.value))


@pytest.mark.parametrize('raw', [
    '{"required_zero_result":true,"required_zero_result":false}',
    '{"x":1,"\\u0078":2}', '{"x":NaN}', '{"x":1e999}',
])
def test_raw_model_result_unique_finite_json_guard_precedes_sign(tmp_path, raw):
    state = fixture(tmp_path)
    state['execution']['job'].update(result=raw, result_sha256=sha(raw.encode()))
    state['review']['observations']['result_sha256'] = sha(raw.encode())
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'oracle_pass': 1}, {'execution_job_id': 'different-job'},
    {'result_sha256': '0' * 64}, {'case_spec_sha256': '0' * 64},
    {'reviewer_code_revision': EXECUTION_SOURCE},
])
def test_review_observations_not_an_unbound_candidate_pass_flag(tmp_path, change):
    state = fixture(tmp_path)
    state['review']['observations'].update(change)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REVIEW_OBSERVATIONS_INVALID'):
        run(state)
    assert state['calls'] == []


def test_path_escape_and_changed_artifact_are_denied_before_signing(tmp_path):
    state = fixture(tmp_path)
    state['row']['evidence'] = '../outside.json'
    with pytest.raises(CertificationReviewError):
        run(state)
    state['row']['evidence'] = 'execution.json'
    (state['root'] / 'a18' / 'execution.json').write_bytes(b'changed after independent review')
    with pytest.raises(CertificationReviewError, match='APPROVED_ARTIFACT_MISMATCH'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('extra', [{'l7_status': 'L7'}, {'health': 'HEALTHY'},
                                 {'recovery_result': 'PASS'}, {'tools_executed': True}])
def test_one_role_record_cannot_smuggle_unproven_other_dimension_claims(tmp_path, extra):
    state = fixture(tmp_path)
    state['row'].update(extra)
    with pytest.raises(CertificationReviewError, match='PROTECTED_BINDINGS_REQUIRED'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('agent', sorted(GROUP_TWO_CASES))
def test_group_two_uses_actual_versioned_spec_and_its_distinct_domain_oracle(tmp_path, agent):
    state = fixture(tmp_path, agent, GROUP_TWO_CASES[agent][2])
    signed = run(state)
    assert signed['agent_id'] == agent and len(state['calls']) == 1
    assert state['execution']['case_spec']['request']['response_format'] == 'strict_json'
    assert signed['review_test_version'] == 'group_two_exact_role_oracle.v1'
    assert state['review']['observations']['oracle_id'] == 'group_two_exact_role_oracle/v1'
    assert 'l7_status' not in signed


@pytest.mark.parametrize('change', [
    {'continuous_health_proven': True}, {'initial_check_pass': True},
    {'retry_check_pass': False}, {'restart_authorized': True},
    {'latest_check_time': '10:00Z'}, {'next_read_only_check': 'restart_service'},
    {'continuous_health_proven': 0},
])
def test_a19_failure_retry_continuity_and_authority_errors_cannot_sign(tmp_path, change):
    answer = dict(GROUP_TWO_CASES['a19'][2], **change)
    state = fixture(tmp_path, 'a19', answer)
    with pytest.raises(CertificationReviewError, match='CASE_ORACLE_FAILED'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('agent', sorted(GROUP_TWO_CASES))
def test_group_two_generic_old_prompt_cannot_replace_exact_contract(tmp_path, agent):
    state = fixture(tmp_path, agent, GROUP_TWO_CASES[agent][2])
    old = challenge('role:normal', agent_id=agent, capability_id=f'responsibility.{agent}')
    state['execution']['case_spec'] = old
    state['review']['observations']['case_spec_sha256'] = sha(canon(old))
    persist(state)
    with pytest.raises(CertificationReviewError, match='EXECUTION_BINDING_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('version', ['', 'oracle.1', 'group_two_exact_role_oracle/v1',
                                     'group_two_exact_role_oracle.v2', True])
def test_group_two_unproved_oracle_version_cannot_be_substituted(tmp_path, version):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    state['row']['review_test_version'] = version
    state['review']['review_test_version'] = version
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


def test_group_two_signed_result_and_source_tamper_are_rejected(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    signed = run(state)
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state['pin']['jwk']}})
    assert verifier(signed)
    assert not verifier(dict(signed, review_test_version='group_two_exact_role_oracle/v2'))
    assert not verifier(dict(signed, evidence_sha256='0' * 64))
    assert not verifier(dict(signed, reviewer_code_revision=EXECUTION_SOURCE))


def test_service_only_reviewer_not_misrepresented_as_registered_agent_execution(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    state['row']['verifier'] = SERVICE
    state['review']['reviewer_identity'] = SERVICE
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []  # Requires a genuine registered review or explicit policy repair.


def test_declared_registered_reviewer_name_without_actual_artifact_never_signs(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    state['review']['observations'].pop('reviewer_execution', None)
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('agent', registered_agent_ids(include_orchestrator=False))
def test_shared_oracle_uses_exact_primary_spec_for_actual_21(agent):
    cap = f'responsibility.{agent}'
    expected = group_two_role_case(agent) if agent in GROUP_TWO_CASES else challenge(
        'role:normal', agent_id=agent, capability_id=cap)
    assert canon(canonical_role_spec(agent, cap)) == canon(expected)
    assert canonical_role_spec(agent, cap)['request']['data_classification'] == 'LOCAL_ONLY'


@pytest.mark.parametrize('agent,cap', [('a19', 'responsibility.a01'),
    ('a01', 'responsibility.a03'), ('A19', 'responsibility.a19'),
    ('reliability', 'responsibility.a19'), ('private-unregistered-identity', 'responsibility.a19'),
    ('prime', 'responsibility.prime'), (None, 'responsibility.a19'), ('a19', None)])
def test_shared_oracle_denies_secondary_alias_and_unknown_scope_without_raw_error(agent, cap):
    with pytest.raises(ValueError, match='^CASE_ORACLE_UNSUPPORTED$'):
        canonical_role_spec(agent, cap)
    assert review_role_output(agent, cap, '{}') == (False, ('case_oracle_unsupported',))


@pytest.mark.parametrize('response', ['{"x":1,"x":2}', '{"x":1,"\\u0078":2}',
    '{"x":NaN}', '{"x":1e999}', '```json\n{}\n```', 'PRIVATE_BAD_OUTPUT',
    '[1]', '"object-required"', '\ud800', '', None])
def test_shared_oracle_strict_json_failure_has_no_raw_answer(response):
    passed, errors = review_role_output('a19', 'responsibility.a19', response)
    assert passed is False and type(passed) is bool and type(errors) is tuple
    assert all('PRIVATE' not in error and len(error) <= 80 for error in errors)


def test_shared_oracle_a19_correct_retry_does_not_prove_continuous_health():
    answer = dict(GROUP_TWO_CASES['a19'][2])
    assert review_role_output('a19', 'responsibility.a19', json.dumps(answer)) == (True, ())
    answer['continuous_health_proven'] = True
    assert review_role_output('a19', 'responsibility.a19', json.dumps(answer)) == (
        False, ('continuous_health_proven',))


def test_shared_oracle_never_equates_nested_float_and_integer():
    answer = role_facts('a13', SOURCES['a13'])
    answer['weekly_units'][0] = 10.0
    assert review_role_output('a13', 'responsibility.a13', json.dumps(answer)) == (
        False, ('literal_field_type_mismatch',))


def proof(state):
    return state['review']['observations']['reviewer_execution']


def rehash_review_artifact_and_chain(state):
    evidence = proof(state)
    metadata = evidence['dispatch']['artifact']
    metadata['sha256'] = sha(evidence['artifact_content_utf8'].encode())
    metadata['bytes'] = len(evidence['artifact_content_utf8'].encode())
    events = [json.loads(raw) for raw in evidence['action_records']]
    for index, event in enumerate(events):
        if index:
            event['previous_sha256'] = events[index - 1]['sha256']
        if event.get('phase') == 'completed' and event.get('action_id') == REVIEW_ACTION:
            event['result_summary']['sha256'] = metadata['sha256']
        event.pop('sha256', None)
        event['sha256'] = sha(canon(event))
    evidence['action_records'] = [json.dumps(event) for event in events]


@pytest.mark.parametrize('change', [
    {'review_action_durable': False}, {'review_action_durable': 1},
    {'model_calls': True}, {'model_calls': 1}, {'state': 'PENDING'},
    {'agent_id': 'a18'}, {'capability': 'responsibility.a27'},
    {'task_id': JOB}, {'runtime_source_revision': REVIEWER_CODE},
    {'review_action_id': 'not-an-action-id'}, {'certification': 'L7'},
])
def test_actual_reviewer_dispatch_literal_identity_and_durability_are_required(tmp_path, change):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    proof(state)['dispatch'].update(change)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REGISTERED_REVIEW_DISPATCH_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'creator_agents': ['a19']}, {'task_id': JOB}, {'runtime_revision': REVIEWER_CODE},
    {'artifact_id': 'not-an-artifact'}, {'location': '../secret.json'},
    {'sha256': '0' * 64}, {'bytes': True}, {'validation_state': 'INDEPENDENTLY_VERIFIED'},
    {'provenance': 'Candidate self-review'}, {'content_validation': 'PASS'},
])
def test_immutable_reviewer_artifact_metadata_is_exact_bound_and_not_uplifted(tmp_path, change):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    proof(state)['dispatch']['artifact'].update(change)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REGISTERED_REVIEW_ARTIFACT_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'reviewer_id': 'a19'}, {'reviewer_capability_id': 'responsibility.a27'},
    {'subject_job_id': REVIEW_TASK}, {'subject_agent_id': 'a18'},
    {'source_revision': REVIEWER_CODE}, {'runtime_image_id': 'sha256:' + 'f' * 64},
    {'execution_evidence_sha256': '0' * 64}, {'case_spec_sha256': '0' * 64},
    {'result_sha256': '0' * 64}, {'model_calls': True}, {'model_calls': 1},
    {'test_result': 'FAIL'}, {'review_errors': ['continuous_health_proven']},
    {'subject_execution_verification': 'DOMAIN_JOIN_REQUIRED'}, {'certification': 'L7'},
    {'oracle_id': 'group_two_exact_role_oracle/v2'}, {'review_nonce': JOB.upper()},
])
def test_actual_reviewer_content_joins_even_if_candidate_rehashes_everything(tmp_path, change):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    content = json.loads(proof(state)['artifact_content_utf8'])
    # UUID fixture consists of digits; use a genuinely noncanonical string.
    if 'review_nonce' in change:
        change = {'review_nonce': 'not-a-review-nonce'}
    content.update(change)
    proof(state)['artifact_content_utf8'] = json.dumps(content)
    rehash_review_artifact_and_chain(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REGISTERED_REVIEW_CONTENT_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'objective_id': JOB}, {'objective_id': REVIEW_TASK}, {'objective_revision': True},
    {'job_id': REVIEW_TASK}, {'execution_metadata_sha256': 'unknown'},
    {'prompt_sha256': 'unknown'}, {'case_spec_sha256': '0' * 64},
    {'runtime': {'host_id': 'ABEX', 'source_revision': REVIEWER_CODE, 'version': '1', 'image_digest': IMAGE}},
    {'runtime': {'host_id': 'UNKNOWN', 'source_revision': EXECUTION_SOURCE, 'version': '1', 'image_digest': IMAGE}},
])
def test_reviewer_current_queue_objective_join_cannot_be_replaced(tmp_path, change):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    content = json.loads(proof(state)['artifact_content_utf8'])
    content['subject_domain_join'].update(change)
    proof(state)['artifact_content_utf8'] = json.dumps(content)
    rehash_review_artifact_and_chain(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REGISTERED_REVIEW_DOMAIN_JOIN_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'success': 1}, {'success': False}, {'agent_id': 'a19'},
    {'task_id': JOB}, {'action_type': 'inference.enqueue'}, {'model_backend': 'ollama'},
    {'duration_ms': True}, {'duration_ms': -1},
])
def test_actual_action_record_semantics_are_checked_even_with_recomputed_chain(tmp_path, change):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    events = [json.loads(raw) for raw in proof(state)['action_records']]
    events[-1].update(change)
    proof(state)['action_records'] = [json.dumps(event) for event in events]
    rehash_review_artifact_and_chain(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REVIEW_ACTION_BINDING_INVALID'):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('mutate', [
    lambda events: events.pop(0),
    lambda events: events.append(events[-1]),
    lambda events: events[-1].update(previous_sha256='f' * 64),
    lambda events: events[-1].update(sequence=True),
    lambda events: events[-1].update(sha256='f' * 64),
])
def test_missing_truncated_duplicate_or_broken_action_chain_never_signs(tmp_path, mutate):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    events = [json.loads(raw) for raw in proof(state)['action_records']]
    mutate(events)
    proof(state)['action_records'] = [json.dumps(event) for event in events]
    persist(state)
    with pytest.raises(CertificationReviewError):
        run(state)
    assert state['calls'] == []


def test_interleaved_real_ledger_events_need_an_intact_contiguous_segment(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    start, completed = [json.loads(raw) for raw in proof(state)['action_records']]
    middle = {'action_id': '66666666-6666-4666-8666-666666666666',
        'sequence': 11, 'previous_sha256': start['sha256'], 'phase': 'started',
        'timestamp': (NOW - timedelta(milliseconds=450)).isoformat()}
    middle['sha256'] = sha(canon(middle))
    completed['sequence'] = 12
    proof(state)['action_records'] = [json.dumps(event) for event in (start, middle, completed)]
    rehash_review_artifact_and_chain(state)
    persist(state)
    assert run(state)['agent_id'] == 'a19'
    assert len(state['calls']) == 1


def test_raw_review_artifact_duplicate_fields_remain_rejected_even_with_hash_update(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    raw = proof(state)['artifact_content_utf8']
    proof(state)['artifact_content_utf8'] = raw[:-1] + ', "model_calls": 1}'
    rehash_review_artifact_and_chain(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='DUPLICATE_FIELD'):
        run(state)
    assert state['calls'] == []


def cloud_fixture(tmp_path):
    from app.agent_cert_transport import (MODEL, POLICY_SCHEMA, PROVIDER_ID,
        bind_cloud_case, case_transport_identity, transport_digest)
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    spec = state['execution']['case_spec']
    policy = {'schema': POLICY_SCHEMA, 'policy_version': 'synthetic-owner-role-trial/v1',
        'owner_authorization_ref': 'synthetic-protected-owner-policy',
        'source_revision': EXECUTION_SOURCE, **case_transport_identity(spec),
        'data_classification': 'CLOUD_PERMITTED', 'public_synthetic': True,
        'provider_id': PROVIDER_ID, 'provider_kind': 'huggingface', 'model': MODEL,
        'minimum_tier': 'MINI', 'max_cost_usd': 0.002, 'context_tokens': 4096,
        'output_tokens': 1024, 'timeout_seconds': 35, 'max_retries': 0, 'concurrency_limit': 1}
    policy_sha = transport_digest(policy)
    binding = bind_cloud_case(spec, policy, expected_source_revision=EXECUTION_SOURCE,
        expected_policy_sha256=policy_sha)
    state['execution']['transport']['provider_locality'] = 'CLOUD'
    state['execution']['job']['provider'] = PROVIDER_ID
    state['execution']['cloud_transport'] = {'binding': binding.receipt(), 'queue_route': {
        'preferred_provider': PROVIDER_ID, 'model': MODEL, 'allow_cloud': 1,
        'data_classification': 'CLOUD_PERMITTED', 'task_class': 'planning', 'classification': 'R0',
        'max_retries': 0, 'max_cost_usd': 0.002, 'prompt_sha256': 'b' * 64,
        'input_tokens': 100, 'output_tokens': 20, 'actual_cost_usd': 0.0001}}
    state['review']['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    return state, {'cloud_binding': binding, 'cloud_policy': policy,
        'expected_owner_policy_sha256': policy_sha}


def test_explicit_external_cloud_policy_preserves_role_and_actual_review_not_prepared_pass(tmp_path):
    state, args = cloud_fixture(tmp_path)
    signed = run(state, **args)
    assert len(state['calls']) == 1 and signed['agent_id'] == 'a19'
    assert state['execution']['case_spec']['request']['data_classification'] == 'LOCAL_ONLY'
    assert state['execution']['cloud_transport']['binding']['state'] == 'PREPARED_NOT_EXECUTED'
    assert state['execution']['transport']['provider_locality'] == 'CLOUD'
    assert 'l7_status' not in signed and 'provider_qualification' not in signed


@pytest.mark.parametrize('missing', ['all', 'cloud_binding', 'cloud_policy', 'expected_owner_policy_sha256'])
def test_cloud_case_needs_separately_protected_pins_not_its_own_receipt(tmp_path, missing):
    state, args = cloud_fixture(tmp_path)
    if missing == 'all':
        args = {}
    else:
        args[missing] = None
    with pytest.raises(CertificationReviewError):
        run(state, **args)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [
    {'preferred_provider': 'hf-gemma-nano'}, {'model': 'Qwen/Qwen3-32B:other'},
    {'allow_cloud': True}, {'data_classification': 'LOCAL_ONLY'}, {'task_class': 'classification'},
    {'classification': 'R1'}, {'max_retries': 1}, {'max_retries': False},
    {'max_cost_usd': 0.003}, {'max_cost_usd': True}, {'prompt_sha256': 'unknown'},
    {'input_tokens': True}, {'input_tokens': 4097}, {'input_tokens': None},
    {'output_tokens': 1025}, {'output_tokens': None}, {'actual_cost_usd': None},
    {'actual_cost_usd': -1}, {'actual_cost_usd': 0.003}, {'actual_cost_usd': True},
])
def test_actual_cloud_route_usage_bounds_and_no_fallback_are_not_candidate_labels(tmp_path, change):
    state, args = cloud_fixture(tmp_path)
    state['execution']['cloud_transport']['queue_route'].update(change)
    state['review']['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='CLOUD_QUEUE_BINDING_INVALID'):
        run(state, **args)
    assert state['calls'] == []


@pytest.mark.parametrize('change', [{'provider': 'hf-alternate'}, {'attempts': 2}])
def test_completed_cloud_provider_fallback_or_retry_does_not_match_approved_single_attempt(tmp_path, change):
    state, args = cloud_fixture(tmp_path)
    state['execution']['job'].update(change)
    state['review']['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='CLOUD_QUEUE_BINDING_INVALID'):
        run(state, **args)
    assert state['calls'] == []


def test_preparation_receipt_tamper_is_denied_even_with_new_candidate_artifact_hashes(tmp_path):
    state, args = cloud_fixture(tmp_path)
    state['execution']['cloud_transport']['binding']['state'] = 'EXECUTED_PASS'
    state['review']['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='CLOUD_TRANSPORT_BINDING_INVALID'):
        run(state, **args)
    assert state['calls'] == []


def test_mutated_policy_source_or_scope_not_reauthorized_from_evidence(tmp_path):
    state, args = cloud_fixture(tmp_path)
    args['cloud_policy']['source_revision'] = REVIEWER_CODE
    with pytest.raises(CertificationReviewError, match='PROTECTED_CLOUD_POLICY_REQUIRED'):
        run(state, **args)
    assert state['calls'] == []


def test_cloud_reviewer_prompt_digest_must_bind_the_actual_route(tmp_path):
    state, args = cloud_fixture(tmp_path)
    content = json.loads(proof(state)['artifact_content_utf8'])
    content['subject_domain_join']['prompt_sha256'] = 'f' * 64
    proof(state)['artifact_content_utf8'] = json.dumps(content)
    rehash_review_artifact_and_chain(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='REGISTERED_REVIEW_DOMAIN_JOIN_INVALID'):
        run(state, **args)
    assert state['calls'] == []


def test_local_default_cannot_be_relabelled_as_cloud_without_policy(tmp_path):
    state = fixture(tmp_path, 'a19', GROUP_TWO_CASES['a19'][2])
    state['execution']['transport']['provider_locality'] = 'CLOUD'
    state['review']['observations']['reviewer_execution'] = mocked_reviewer_execution(state)
    persist(state)
    with pytest.raises(CertificationReviewError, match='LIVE_AUTHORIZED_TRANSPORT_REQUIRED'):
        run(state)
    assert state['calls'] == []
