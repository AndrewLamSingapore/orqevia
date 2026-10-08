"""Synthetic stores/keys only; not live execution, Azure signing, or an L7 award."""
from copy import deepcopy
import json

import pytest

from app.agent_cert_a19_baseline import ORACLE_ID, SUPPORTED_CASES, canonical_a19_baseline_case
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_role_review import canonical_case_spec, review_case_output
from app.agent_cert_transport import (SUPPORTED_MODELS, bind_cloud_case,
    canonical_cert_case, case_transport_identity, transport_digest)
from scripts import sign_admitted_agent_cases as loader
from tests.test_agent_cert_a19_baseline import answer
from tests.test_agent_cert_case_bridge import QualityOperator, signing_fixture as old_fixture
from tests.test_agent_cert_reviewed_signing import (SERVICE, KEY, canon, sha,
    mocked_reviewer_execution, persist, run)
from tests.test_agent_cert_review_tool_cases import case_fixture
from tests.test_agent_cert_review_tool import repin, run as review_tool
from tests.test_agent_cert_transport_cases import prepared, bind
from tests.test_collect_agent_cert_case import SyntheticOperator, SOURCE, canonical
from tests.test_sign_admitted_agent_cases import entry, manifest


def rebind_review_artifact(proof, case):
    # Explicit synthetic fixture rewrite, never transformation of live evidence.
    content = json.loads(proof['artifact_content_utf8'])
    dimension, test_case = case.split(':')
    content.update(dimension=dimension, test_case=test_case, oracle_id=ORACLE_ID)
    raw = json.dumps(content, indent=2).encode()
    proof['artifact_content_utf8'] = raw.decode()
    metadata = proof['dispatch']['artifact']
    metadata.update(sha256=sha(raw), bytes=len(raw))
    events = [json.loads(line) for line in proof['action_records']]
    events[-1]['result_summary']['sha256'] = metadata['sha256']
    events[-1]['sha256'] = sha(canon({k: v for k, v in events[-1].items() if k != 'sha256'}))
    proof['action_records'] = [json.dumps(event) for event in events]


def signing_fixture(tmp_path, case):
    state = old_fixture(tmp_path, 'role:difficult')
    spec = canonical_case_spec('a19', 'responsibility.a19', case)
    dimension, test_case = case.split(':')
    raw = json.dumps(answer(case))
    state['execution'].update(case_spec=spec, dimension=dimension, test_case=test_case)
    state['execution']['job'].update(result=raw, result_sha256=sha(raw.encode()))
    state['row'].update(dimension=dimension, test_case=test_case, review_test_version=ORACLE_ID)
    state['review'].update(dimension=dimension, test_case=test_case, review_test_version=ORACLE_ID)
    state['review']['observations'].update(case_spec_sha256=sha(canon(spec)),
        oracle_id=ORACLE_ID, result_sha256=sha(raw.encode()))
    proof = mocked_reviewer_execution(state)
    rebind_review_artifact(proof, case)
    state['review']['observations']['reviewer_execution'] = proof
    persist(state)
    return state


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_baseline_shared_reviewer_keeps_distinct_exact_oracle(case):
    assert canonical_case_spec('a19', 'responsibility.a19', case) == canonical_a19_baseline_case(case)
    assert review_case_output('a19', 'responsibility.a19', case, json.dumps(answer(case))) == (True, ())
    assert review_case_output('a18', 'responsibility.a18', case, json.dumps(answer(case)))[0] is False


@pytest.mark.parametrize('case', SUPPORTED_CASES)
@pytest.mark.parametrize('model', sorted(SUPPORTED_MODELS))
def test_cloud_baseline_retains_own_oracle_tier_and_no_execution_claim(case, model):
    spec, policy = prepared(case, model)
    bound = bind(spec, policy)
    assert spec == canonical_cert_case('a19', 'responsibility.a19', case)
    assert spec['oracle_id'] == policy['oracle_id'] == bound.receipt()['oracle_id'] == ORACLE_ID
    assert bound.request()['task_class'] == 'complex_reasoning'
    assert bound.request()['minimum_tier'] == 'FLAGSHIP'
    assert bound.receipt()['state'] == 'PREPARED_NOT_EXECUTED'
    assert bound.receipt()['certification'] == 'UNVERIFIED'
    borrowed = deepcopy(policy)
    borrowed['oracle_id'] = 'a19-general-quality-oracle.v1'
    with pytest.raises(ValueError):
        bind(spec, borrowed)


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_registered_review_checks_baseline_answer_and_rejects_false_claim(case):
    payload = case_fixture('role:difficult')
    execution = payload['execution']
    dimension, test_case = case.split(':')
    execution.update(dimension=dimension, test_case=test_case,
        case_spec=canonical_case_spec('a19', 'responsibility.a19', case))
    raw = json.dumps(answer(case))
    execution['job'].update(result=raw, result_sha256=sha(raw.encode()))
    repin(payload)
    reviewed = review_tool(payload)
    assert reviewed['test_result'] == 'PASS' and reviewed['oracle_id'] == ORACLE_ID
    assert reviewed['certification'] == 'UNVERIFIED'
    assert reviewed['subject_execution_verification'] == 'DOMAIN_JOIN_REQUIRED'
    incorrect = answer(case)
    incorrect['actions_executed'] = True
    raw = json.dumps(incorrect)
    execution['job'].update(result=raw, result_sha256=sha(raw.encode()))
    repin(payload)
    assert review_tool(payload)['test_result'] == 'FAIL'


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_fixture_signer_recomputes_baseline_and_rejects_borrowed_oracle(tmp_path, case):
    state = signing_fixture(tmp_path, case)
    signed = run(state)
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state['pin']['jwk']}})
    assert len(state['calls']) == 1 and verifier(signed) is True
    assert signed['review_test_version'] == ORACLE_ID
    assert not verifier(dict(signed, test_case='normal'))
    assert 'l7_status' not in signed and 'health' not in signed and 'recovery_result' not in signed
    state['calls'].clear()
    state['review']['observations']['oracle_id'] = 'a19-general-quality-oracle.v1'
    persist(state)
    with pytest.raises(ValueError):
        run(state)
    assert state['calls'] == []


@pytest.mark.parametrize('case,path', [
    ('baseline:authorization', ('error_basis_points',)),
    ('baseline:objective', ('error_basis_points', 0)),
    ('baseline:instruction', ('applied_limit_basis_points',)),
    ('baseline:context', ('sample_age_seconds', 0)),
    ('baseline:structured_output', ('assessments', 2, 'error_basis_points')),
    ('baseline:contract', ('output_contract_met',)),
    ('baseline:error', ('valid_error_basis_points', 0)),
    ('baseline:timeout', ('stated_budget_exhausted',)),
    ('baseline:evidence', ('reduction_percent',)),
    ('baseline:result', ('maximum_consecutive_failures',)),
    ('baseline:completion', ('bounded_assessment_complete',)),
    ('baseline:prime_validation', ('expected_error_basis_points',)),
])
def test_fully_rebound_false_baseline_result_is_denied_before_signing(tmp_path, case, path):
    state = signing_fixture(tmp_path, case)
    bad = answer(case)
    parent = bad
    for key in path[:-1]:
        parent = parent[key]
    current = parent[path[-1]]
    parent[path[-1]] = not current if type(current) is bool else current + 1 if type(current) is int else 0
    raw = json.dumps(bad)
    # Preserve coherent synthetic custody and a dishonest PASS reviewer fixture;
    # the protected grader must still derive the right result independently.
    state['execution']['job'].update(result=raw, result_sha256=sha(raw.encode()))
    state['review']['observations']['result_sha256'] = sha(raw.encode())
    proof = mocked_reviewer_execution(state)
    rebind_review_artifact(proof, case)
    state['review']['observations']['reviewer_execution'] = proof
    persist(state)
    with pytest.raises(ValueError):
        run(state)
    assert state['calls'] == []


class BaselineOperator(QualityOperator):
    def __init__(self, case):
        super().__init__('role:difficult')
        self.case = case
        self.spec = canonical_case_spec('a19', 'responsibility.a19', case)
        self.answer = answer(case)
        self.job.update(result=json.dumps(self.answer))
        self.policy.update(case_transport_identity(self.spec))
        self.options = {'cloud_binding': bind_cloud_case(self.spec, self.policy,
            expected_source_revision=SOURCE, expected_policy_sha256=transport_digest(self.policy)),
            'cloud_policy': self.policy, 'expected_owner_policy_sha256': transport_digest(self.policy),
            'expected_provider_entry_sha256': sha(canonical(self.entry))}

    def dispatch_review(self, request):
        status, dispatch = SyntheticOperator.dispatch_review(self, request)
        proof = {'dispatch': dispatch, 'artifact_content_utf8': self.proof['raw'].decode(),
                 'action_records': self.proof['actions']}
        rebind_review_artifact(proof, self.case)
        self.proof.update(dispatch=proof['dispatch'], raw=proof['artifact_content_utf8'].encode(),
                          actions=proof['action_records'])
        return status, deepcopy(self.proof['dispatch'])


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_fixture_collection_retains_unsigned_baseline_not_runtime_event(case):
    observed = BaselineOperator(case).run()
    assert observed.summary['state'] == 'UNSIGNED_CASE_EVIDENCE', observed.summary
    execution = json.loads(observed.execution_bytes)
    assert execution['dimension'] + ':' + execution['test_case'] == case
    assert execution['cloud_transport']['binding']['oracle_id'] == ORACLE_ID
    assert observed.summary['signature'] == 'NOT_PERFORMED'
    assert observed.summary['certification'] == 'UNVERIFIED'


def test_batch_admission_distinguishes_all_twelve_baselines_without_duplicates():
    rows = []
    for case in SUPPORTED_CASES:
        item = entry()
        item['record']['dimension'], item['record']['test_case'] = case.split(':')
        rows.append(item)
    assert len(loader.parse(manifest(rows))) == 12
    with pytest.raises(ValueError):
        loader.parse(manifest(rows + [deepcopy(rows[0])]))


def test_protected_source_pins_include_the_new_baseline_grader():
    assert 'app/agent_cert_a19_baseline.py' in loader.CODE_FILES
