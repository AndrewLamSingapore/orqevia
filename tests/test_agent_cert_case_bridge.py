"""Explicit synthetic API/artifact/key fixtures, not live agent certification."""
from copy import deepcopy
import json

import pytest

from app.agent_cert_a19_cases import ORACLE_ID, SUPPORTED_CASES
from app.agent_cert_azure_es256 import AzureES256CertificationVerifier
from app.agent_cert_role_review import canonical_case_spec
from app.agent_cert_transport import (SUPPORTED_MODELS, bind_cloud_case,
    case_transport_identity, transport_digest)
from app.agent_certification import LOGIC_SIGNALS
from scripts import sign_admitted_agent_cases as loader
from tests.test_agent_cert_a19_cases import ANSWERS
from tests.test_agent_cert_reviewed_signing import (
    SERVICE, KEY, fixture, mocked_reviewer_execution, persist, run,
)
from tests.test_collect_agent_cert_case import SyntheticOperator, SOURCE, canonical, sha
from tests.test_sign_admitted_agent_cases import entry, manifest

MODEL = 'Qwen/Qwen3-235B-A22B-Instruct-2507:novita'
assert MODEL in SUPPORTED_MODELS


def answer(case):
    return {'case_id': case, 'restart_authorized': False, 'actions_executed': False,
            **deepcopy(ANSWERS[case])}


def rebind_artifact(proof, case):
    """Rebuild a synthetic fixture only; real operators must read original bytes."""
    dimension, test_case = case.split(':')
    content = json.loads(proof['artifact_content_utf8'])
    content.update(dimension=dimension, test_case=test_case, oracle_id=ORACLE_ID)
    raw = json.dumps(content, indent=2).encode()
    proof['artifact_content_utf8'] = raw.decode()
    metadata = proof['dispatch']['artifact']
    metadata.update(sha256=sha(raw), bytes=len(raw))
    events = [json.loads(line) for line in proof['action_records']]
    events[-1]['result_summary']['sha256'] = metadata['sha256']
    events[-1]['sha256'] = sha(canonical({k: v for k, v in events[-1].items() if k != 'sha256'}))
    proof['action_records'] = [json.dumps(event) for event in events]


def signing_fixture(tmp_path, case):
    state = fixture(tmp_path, 'a19', answer(case))
    dimension, test_case = case.split(':')
    spec = canonical_case_spec('a19', 'responsibility.a19', case)
    state['execution'].update(case_spec=spec, dimension=dimension, test_case=test_case)
    state['row'].update(dimension=dimension, test_case=test_case, review_test_version=ORACLE_ID)
    if dimension == 'logic_quality':
        state['row']['logic_signals'] = {LOGIC_SIGNALS[test_case]: 'PASS'}
    state['review'].update(dimension=dimension, test_case=test_case, review_test_version=ORACLE_ID)
    observations = state['review']['observations']
    observations.update(case_spec_sha256=sha(canonical(spec)), oracle_id=ORACLE_ID)
    proof = mocked_reviewer_execution(state)
    rebind_artifact(proof, case)
    observations['reviewer_execution'] = proof
    persist(state)
    return state


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_each_source_owned_quality_case_signs_only_exact_dimensions(tmp_path, case):
    state = signing_fixture(tmp_path, case)
    signed = run(state)
    assert len(state['calls']) == 1
    verifier = AzureES256CertificationVerifier({SERVICE: {KEY: state['pin']['jwk']}})
    assert verifier(signed) is True
    assert verifier(dict(signed, test_case='normal')) is False
    assert signed['dimension'] + ':' + signed['test_case'] == case
    assert 'l7_status' not in signed and 'recovery_result' not in signed


@pytest.mark.parametrize('case', [c for c in SUPPORTED_CASES if c.startswith('logic_quality:')])
@pytest.mark.parametrize('signals', [{}, {'unrelated': 'PASS'}, {'evidence_support': True}])
def test_logic_signal_cannot_be_invented_or_unbound(tmp_path, case, signals):
    state = signing_fixture(tmp_path, case)
    state['row']['logic_signals'] = signals
    with pytest.raises(ValueError):
        run(state)
    assert not state['calls']


@pytest.mark.parametrize('case', ['recovery:tool_failure', 'general:problem_solving',
                                  'independent_verification:review', 'fresh_challenge:unseen'])
def test_generic_event_cases_cannot_obtain_a_quality_oracle_signature(tmp_path, case):
    state = signing_fixture(tmp_path, SUPPORTED_CASES[0])
    state['row']['dimension'], state['row']['test_case'] = case.split(':')
    with pytest.raises(ValueError):
        run(state)
    assert not state['calls']


class QualityOperator(SyntheticOperator):
    def __init__(self, case):
        super().__init__(agent='a19', cloud=True)
        self.case = case
        self.spec = canonical_case_spec('a19', 'responsibility.a19', case)
        self.answer = answer(case)
        self.job.update(result=json.dumps(self.answer), task_class='complex_reasoning',
                        model=MODEL, actual_cost_usd=0.000038, estimated_cost_usd=0.00096256)
        self.entry.update(model=MODEL, tier='FLAGSHIP',
                          input_usd_million=0.09, output_usd_million=0.58,
                          allowed_task_classes=['complex_reasoning'], task_budgets={
            'complex_reasoning': {'context_tokens': 4096, 'output_tokens': 1024,
                                 'timeout_seconds': 35}})
        self.policy.update(case_transport_identity(self.spec))
        self.policy.update(model=MODEL, minimum_tier='FLAGSHIP')
        self.options = {'cloud_binding': bind_cloud_case(self.spec, self.policy,
            expected_source_revision=SOURCE, expected_policy_sha256=transport_digest(self.policy)),
            'cloud_policy': self.policy, 'expected_owner_policy_sha256': transport_digest(self.policy),
            'expected_provider_entry_sha256': sha(canonical(self.entry))}

    def submit(self, request):
        status, body = super().submit(request)
        body['steps'][0]['dispatch']['tier'] = 'FLAGSHIP'
        return status, body

    def dispatch_review(self, request):
        status, dispatch = super().dispatch_review(request)
        proof = {'dispatch': dispatch, 'artifact_content_utf8': self.proof['raw'].decode(),
                 'action_records': self.proof['actions']}
        rebind_artifact(proof, self.case)
        self.proof.update(dispatch=proof['dispatch'], raw=proof['artifact_content_utf8'].encode(),
                          actions=proof['action_records'])
        return status, deepcopy(self.proof['dispatch'])


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_each_actual_shaped_quality_collection_remains_unsigned(case):
    operator = QualityOperator(case)
    observed = operator.run()
    assert observed.summary['state'] == 'UNSIGNED_CASE_EVIDENCE', observed.summary
    primary = json.loads(observed.execution_bytes)
    assert primary['dimension'] + ':' + primary['test_case'] == case
    assert primary['cloud_transport']['binding']['minimum_tier'] == 'FLAGSHIP'
    assert operator.last_request['task_class'] == 'complex_reasoning'
    assert observed.summary['signature'] == 'NOT_PERFORMED'
    assert observed.summary['certification'] == 'UNVERIFIED'


def test_distinct_source_owned_cases_same_agent_can_be_batched_without_agent22():
    entries = []
    for case in ['role:normal', *SUPPORTED_CASES]:
        item = entry()
        item['record']['dimension'], item['record']['test_case'] = case.split(':')
        entries.append(item)
    assert len(loader.parse(manifest(entries))) == 21
    with pytest.raises(ValueError):
        loader.parse(manifest(entries + [deepcopy(entries[0])]))


@pytest.mark.parametrize('identity', ['a22', 'a03', 'prime', 'A19', '', None])
def test_manifest_rejects_nonpermanent_or_noncanonical_subject(identity):
    item = entry()
    item['record']['agent_id'] = identity
    with pytest.raises(ValueError):
        loader.parse(manifest([item]))


def test_source_owned_case_identity_does_not_justify_unbounded_batch():
    # Size rejects before duplicate/case interpretation, regardless of identity.
    with pytest.raises(ValueError):
        loader.parse(manifest([entry()] * 129))


def test_expanded_signer_oracle_inputs_are_byte_bound():
    required = {'app/agent_cert_a19_cases.py', 'app/agent_dispatch_api.py',
                'app/agent_cert_review_tool.py', 'app/hf_admission.py', 'app/cloud_execution.py'}
    assert required <= set(loader.CODE_FILES)
