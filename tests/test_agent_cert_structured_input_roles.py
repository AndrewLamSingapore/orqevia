"""Source/task version checks; fixtures never count as actual competence."""
import copy
import json

import pytest

from app.agent_cert_role_review import canonical_case_spec, review_case_output
from app.agent_cert_structured_roles import CASE_ID, INPUT_CASE_VERSION as CASE_VERSION
from app.agent_cert_transport import transport_digest, canonical_cert_case
from app.agent_registry import registered_agent_ids
from app.response_schema import canonical_schema_json, validated_wire_schema


def test_a19_historical_contract_and_pin_are_unchanged():
    legacy = canonical_case_spec('a19', 'responsibility.a19', 'role:normal')
    assert legacy['case_version'] == 'a19-role-normal-operation-id.v2'
    assert transport_digest(legacy) == 'd4ecfa3e97d0ec7b842dffac2b64fd431c40b45f98c9951d18b09ee3a724e929'
    assert 'response_schema' not in legacy['request']


@pytest.mark.parametrize('agent', registered_agent_ids(include_orchestrator=False))
def test_new_contract_is_explicit_independent_source_bound_and_local_only(agent):
    capability = f'responsibility.{agent}'
    legacy = canonical_case_spec(agent, capability, 'role:normal')
    saved = copy.deepcopy(legacy)
    new = canonical_case_spec(agent, capability, CASE_ID)
    assert new['case'] == CASE_ID and new['case_version'] == CASE_VERSION
    assert new['oracle_id'] in {'existing.role-normal.v1', 'group_two_exact_role_oracle/v1'}
    assert new['independent_review'] == legacy['independent_review']
    assert new['expected_discriminants'] == legacy['expected_discriminants']
    assert new['agent_id'] == legacy['agent_id'] and new['capability_id'] == legacy['capability_id']
    assert new['request']['data_classification'] == 'LOCAL_ONLY'
    assert new['request']['max_cost_usd'] == 0
    assert new['request']['objective'].startswith(legacy['request']['objective'])
    context = json.loads(new['request']['context'])
    assert context['original_source_context'] == legacy['request']['context']
    assert set(context) == {'original_source_context', 'raw_source_facts'}
    assert transport_digest(new) != transport_digest(legacy)
    assert legacy == saved
    new['request']['response_schema']['properties'].clear()
    assert canonical_case_spec(agent, capability, CASE_ID)['request']['response_schema']['properties']
    # This new local contract acquires neither historical HF authority nor a
    # provider policy merely because a prior role-normal policy existed.
    with pytest.raises(ValueError):
        canonical_cert_case(agent, capability, CASE_ID)


def test_new_contract_uses_the_same_semantic_oracle_and_rejects_wrong_math():
    result = json.dumps({'reliability_weight': 2, 'speed_weight': 1, 'a_reliability': 4,
        'a_speed': 1, 'b_reliability': 2, 'b_speed': 5, 'a_score': 1, 'b_score': 5,
        'decision': 'TIE', 'missing_tie_breaker': True})
    legacy = review_case_output('a04', 'responsibility.a04', 'role:normal', result)
    new = review_case_output('a04', 'responsibility.a04', CASE_ID, result)
    assert new == legacy and new[0] is False
    assert 'a_score' in new[1] and 'b_score' in new[1]


def test_input_renderer_rejects_changed_source_instead_of_using_stale_facts():
    from app.agent_cert_role_inputs import normal_role_raw_input_facts
    with pytest.raises(ValueError, match='Original source context differs'):
        normal_role_raw_input_facts('a04', 'some new arbitrary production context')


def test_wire_field_order_survives_sorted_storage_without_changing_semantic_digest():
    new = canonical_case_spec('a04', 'responsibility.a04', CASE_ID)
    declared = new['request']['response_schema']
    saved = json.loads(json.dumps(validated_wire_schema(declared), sort_keys=True))
    restored = validated_wire_schema(saved)
    fields = list(declared['properties'])
    assert list(restored['properties']) == fields
    assert restored['required'] == fields
    assert fields.index('reliability_weight') < fields.index('a_score') < fields.index('decision')
    opposite = copy.deepcopy(declared)
    opposite['properties'] = dict(reversed(list(opposite['properties'].items())))
    opposite['required'].reverse()
    assert canonical_schema_json(declared) == canonical_schema_json(opposite)


def test_primary_structured_contract_cannot_borrow_another_responsibility():
    with pytest.raises(ValueError):
        canonical_case_spec('a18', 'responsibility.a27', CASE_ID)
