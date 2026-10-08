"""Injected secondary queue observations; never live execution or certification."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_execution import observe_cert_case
from app.agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, canonical_secondary_spec
from tests.test_agent_cert_execution import _run
from tests.test_agent_cert_secondary_roles import EXPECTED


CAPS = tuple(EXPECTED)


@pytest.mark.parametrize('capability', CAPS)
def test_secondary_observer_reviews_its_own_hand_calculated_case(capability):
    actor = SUPPORTED_CAPABILITIES[capability]
    spec = canonical_secondary_spec(actor, capability)
    raw = json.dumps(EXPECTED[capability])
    observation = _run(spec, raw)
    assert observation['state'] == 'EXECUTED'
    assert observation['case_review'] == 'SECONDARY_ROLE_CHECK_PASS'
    assert observation['agent_id'] == actor
    assert observation['capability_id'] == capability
    assert observation['result_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert observation['review_errors'] == ()
    assert observation['certification'] == 'UNVERIFIED'
    assert 'result' not in observation


@pytest.mark.parametrize('capability', CAPS)
def test_secondary_prose_false_action_or_forged_pass_never_borrows_primary_oracle(capability):
    actor = SUPPORTED_CAPABILITIES[capability]
    spec = canonical_secondary_spec(actor, capability)
    for answer in ('Plausible role prose', '{"test_result":"PASS"}',
                   json.dumps({**EXPECTED[capability], 'actions_executed': True})):
        observed = _run(spec, answer)
        assert observed['state'] == 'EXECUTED'
        assert observed['case_review'] == 'SECONDARY_ROLE_CHECK_FAIL'
        assert observed['review_errors']
        assert observed['certification'] == 'UNVERIFIED'


@pytest.mark.parametrize('field', ['context', 'objective', 'max_cost_usd'])
def test_modified_secondary_source_rejected_before_any_dispatch(field):
    spec = canonical_secondary_spec('a02', 'responsibility.a03')
    forged = copy.deepcopy(spec)
    forged['request'][field] = False if field == 'max_cost_usd' else 'Caller-selected source'
    observed = observe_cert_case(forged,
        dispatch=lambda _: pytest.fail('Changed source must not dispatch'),
        get_job=lambda _: pytest.fail('Changed source must not read jobs'))
    assert observed['state'] == 'REJECTED'
    assert observed['reason'] == 'secondary_role_oracle_source_mismatch'


def test_forged_secondary_oracle_markers_cannot_replace_canonical_contract():
    spec = canonical_secondary_spec('a12', 'responsibility.a11')
    forged = {**spec, 'independent_review': (*spec['independent_review'], 'exact_rate_oracle')}
    observed = observe_cert_case(forged,
        dispatch=lambda _: pytest.fail('Changed oracle must not dispatch'),
        get_job=lambda _: pytest.fail('Changed oracle must not read jobs'))
    assert observed['state'] == 'REJECTED'
    assert observed['reason'] == 'secondary_role_oracle_source_mismatch'


def test_old_merged_agent_alias_cannot_submit_secondary_case():
    spec = canonical_secondary_spec('a02', 'responsibility.a03')
    forged = {**spec, 'agent_id': 'a03'}
    with pytest.raises(ValueError, match='bounded registered route'):
        observe_cert_case(forged,
            dispatch=lambda _: pytest.fail('Alias cannot dispatch'),
            get_job=lambda _: pytest.fail('Alias cannot read jobs'))


def test_secondary_completed_job_still_requires_original_worker_identity():
    spec = canonical_secondary_spec('a26', 'responsibility.a25')
    raw = json.dumps(EXPECTED['responsibility.a25'])
    assert _run(spec, raw, row_changes={'agent': 'a19'})['reason'] == 'job_identity_mismatch'
    assert _run(spec, raw, row_changes={'provider': None})['reason'] == 'worker_evidence_missing'
    assert _run(spec, raw, row_changes={'attempts': True})['reason'] == 'worker_evidence_missing'
    assert _run(spec, raw, row_changes={'error': 'failed'})['reason'] == 'worker_evidence_missing'
