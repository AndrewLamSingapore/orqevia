"""Registered raw-contract source checks, not owning event/certification evidence."""
from copy import deepcopy
import hashlib
import pytest
from app import agent_registry
from app.agent_cert_owned_contract import proposals,check_raw_proposal,canonical_owned_contract_case,OwnedContractError


def pins():return hashlib.sha256(agent_registry.REGISTRY_PATH.read_bytes()).hexdigest()


def pairs():return [(a['id'],c) for a in agent_registry.load_agent_registry()['agents'] for c in a['capability_requirements']]


@pytest.mark.parametrize('agent,capability',pairs())
def test_all_actual_registered_proposals_preserve_findings_and_ownership(agent,capability):
    proposal=proposals(agent,capability);before=deepcopy(proposal)
    supplied=check_raw_proposal(agent,capability,proposal['supplied'],registry_sha256=pins())
    assert supplied['registered_required_input_missing']==['data_classification']
    assert supplied['registered_required_output_missing']==['uncertainty']
    assert supplied['dispatch_model_validation']['accepted'] is False # capability is really absent
    assert supplied['output_status_allowed'] is False
    assert supplied['unsupported_executed_action_indices']==[0]
    valid=check_raw_proposal(agent,capability,proposal['valid'],registry_sha256=pins())
    assert valid['dispatch_model_validation']['accepted'] and valid['selected_capability_matches']
    assert valid['output_status_allowed'] and valid['unsupported_executed_action_indices']==[]
    foreign=check_raw_proposal(agent,capability,proposal['foreign_capability'],registry_sha256=pins())
    assert foreign['dispatch_model_validation']['accepted'] and not foreign['selected_capability_matches']
    assert proposal==before and canonical_owned_contract_case(agent,capability)['certification']=='UNVERIFIED'


def test_actual_dispatch_defaults_not_misdescribed_as_rejections():
    proposal=proposals('a19','responsibility.a19')['valid']
    del proposal['proposed_request']['context'];del proposal['proposed_request']['data_classification']
    result=check_raw_proposal('a19','responsibility.a19',proposal,registry_sha256=pins())
    assert result['dispatch_model_validation']['accepted'] is True
    assert result['registered_required_input_missing']==['context','data_classification']
    assert 'context' not in proposal['proposed_request']


def test_a19_original_supplied_contract_challenge_is_exact():
    from app.agent_cert_a19_baseline import _SCENARIOS,CASE_VERSION
    assert proposals('a19','responsibility.a19')['supplied']==_SCENARIOS['baseline:contract'][1]
    assert CASE_VERSION=='a19-baseline-quality.v1'


def test_no_submitted_execution_receipt_can_authorize_proposal():
    proposal=proposals('a19','responsibility.a19')['supplied'];proposal['independent_execution_receipt']={'PASS':True}
    with pytest.raises(OwnedContractError):check_raw_proposal('a19','responsibility.a19',proposal,registry_sha256=pins())
