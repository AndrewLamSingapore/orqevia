"""Public source-quality graph discriminators; no model calls or L7 proof."""
import copy
import json
import pytest
from app import agent_cert_a19_cases as cases
from tests.test_agent_cert_a19_cases import answer,wire

CASE='broad_transfer:complete'

@pytest.mark.parametrize('field,value',[
 ('potentially_affected_nodes',['mailer','archive','cache']),
 ('potentially_affected_nodes',['jobs']),('unobserved_nodes',[]),
 ('actual_propagation_proven',True),('current_health','PASS'),
 ('global_failure_proven',True),('general_model_transfer_proven',True),
 ('cause_known',True),('independent_branch_sample','FAIL'),
 ('restart_authorized',True),('actions_executed',True),
 ('topology_scope','GLOBAL_CONFIRMED'),('evidence_refs',['BT-GRAPH','copied-memory','BT-CACHE'])])
def test_wrong_topology_or_authority_claim_is_rejected(field,value):
 result=answer(CASE);result[field]=value
 ok,errors=cases.review_a19_case_output(CASE,wire(result))
 assert ok is False and field in errors

def test_changed_graph_requires_data_derived_upstream_set(monkeypatch):
 objective,facts=cases._SCENARIOS[CASE]
 changed=copy.deepcopy(facts)
 changed['dependency_edges']=[['jobs','mailer'],['ingress','cache']]
 monkeypatch.setitem(cases._SCENARIOS,CASE,(objective,changed))
 old=answer(CASE)
 assert cases.review_a19_case_output(CASE,wire(old))[0] is False
 old['potentially_affected_nodes']=['jobs']
 assert cases.review_a19_case_output(CASE,wire(old))==(True,())

def test_cycle_terminates_without_inventing_propagation(monkeypatch):
 objective,facts=cases._SCENARIOS[CASE]
 changed=copy.deepcopy(facts)
 changed['dependency_edges'].append(['mailer','jobs'])
 monkeypatch.setitem(cases._SCENARIOS,CASE,(objective,changed))
 assert cases.review_a19_case_output(CASE,wire(answer(CASE)))==(True,())

def test_source_case_preserves_complex_reasoning_and_declares_limited_scope():
 from app.agent_cert_cases import challenge
 from app.compute_catalog import task_tier
 spec=cases.canonical_a19_case(CASE)
 original=challenge(CASE,agent_id='a19',capability_id='responsibility.a19')
 for key in ('minimum_tier','task_class','classification','data_classification','max_cost_usd'):
  assert spec['request'][key]==original['request'][key]
 assert task_tier(spec['request']['task_class'])==task_tier(original['request']['task_class'])
 assert json.loads(spec['request']['context'])['facts']['challenge_scope']=='FIXED_PUBLIC_TOPOLOGY_QUALITY_ONLY'
 assert spec['certification']=='UNVERIFIED'
 assert 'general_model_transfer_proven' in spec['expected_discriminants']
