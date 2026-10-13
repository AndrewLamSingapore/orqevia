"""Independent arithmetic and denial regressions; no model or certification calls."""
from copy import deepcopy
import json

import pytest

from app.agent_cert_role_numeric_variants import (
    ORACLE_VERSION, PRIMARY_PAIRS, SUPPORTED_AGENTS, SUPPORTED_CASES,
    canonical_numeric_variant_case, review_numeric_variant_output, _derive,
)
from app.agent_cert_role_review import canonical_role_spec


def valid(result, prior=None):
    return {'input_status': 'VALID', 'errors': [], 'result': result,
            'prior_result_supported': prior, 'execution_performed': False}


def invalid(field):
    return {'input_status': 'INVALID', 'errors': [field], 'result': None,
            'prior_result_supported': None, 'execution_performed': False}


# These hand-calculated answers are independent of the implementation helpers.
# In particular, 9/120=3/40 vs 6/30=1/5 worsens despite a lower failure count;
# discounted margin is 100000/275000=4/11; 19000/24 cents reduces to2375/3.
ANSWERS = {
    ('a01', 'role:difficult'): valid({'selected_projects': ['Beta', 'Gamma'], 'used_days': 4, 'total_points': 13}),
    ('a01', 'role:edge'): valid({'selected_projects': [], 'used_days': 0, 'total_points': 0}),
    ('a01', 'role:invalid_input'): invalid('available_days'),
    ('a01', 'role:failure'): valid({'selected_projects': ['Beta', 'Gamma'], 'used_days': 3, 'total_points': 11}, False),
    ('a04', 'role:difficult'): valid({'scores': {'A': 44, 'B': 42, 'C': 45}, 'winners': ['C'], 'maximum_score': 45}),
    ('a04', 'role:edge'): valid({'scores': {'A': 0, 'B': 0}, 'winners': ['A', 'B'], 'maximum_score': 0}),
    ('a04', 'role:invalid_input'): invalid('options[0].scores.speed'),
    ('a04', 'role:failure'): valid({'scores': {'A': 8, 'B': 22}, 'winners': ['B'], 'maximum_score': 22}, False),
    ('a05', 'role:difficult'): valid({'selected_projects': ['Q', 'R'], 'used_slots': 4, 'total_value': 16}),
    ('a05', 'role:edge'): valid({'selected_projects': [], 'used_slots': 0, 'total_value': 0}),
    ('a05', 'role:invalid_input'): invalid('projects[1].id'),
    ('a05', 'role:failure'): valid({'selected_projects': ['P', 'R'], 'used_slots': 2, 'total_value': 15}, False),
    ('a12', 'role:difficult'): valid({'before_rate_fraction': {'numerator': 3, 'denominator': 40},
        'after_rate_fraction': {'numerator': 1, 'denominator': 5}, 'failure_count_change': -3,
        'lower_failure_rate': 'before', 'relative_failure_rate_change_fraction': {'numerator': 5, 'denominator': 3}}),
    ('a12', 'role:edge'): valid({'before_rate_fraction': {'numerator': 0, 'denominator': 1},
        'after_rate_fraction': {'numerator': 0, 'denominator': 1}, 'failure_count_change': 0,
        'lower_failure_rate': 'equal', 'relative_failure_rate_change_fraction': None}),
    ('a12', 'role:invalid_input'): invalid('before.requests'),
    ('a12', 'role:failure'): valid({'before_rate_fraction': {'numerator': 1, 'denominator': 10},
        'after_rate_fraction': {'numerator': 1, 'denominator': 5}, 'failure_count_change': -1,
        'lower_failure_rate': 'before', 'relative_failure_rate_change_fraction': {'numerator': 1, 'denominator': 1}}, False),
    ('a20', 'role:difficult'): valid({'currency': 'USD', 'revenue_cents': 275000,
        'variable_cost_cents': 175000, 'gross_profit_cents': 100000,
        'gross_margin_fraction': {'numerator': 4, 'denominator': 11}}),
    ('a20', 'role:edge'): valid({'currency': 'USD', 'revenue_cents': 0,
        'variable_cost_cents': 0, 'gross_profit_cents': 0, 'gross_margin_fraction': None}),
    ('a20', 'role:invalid_input'): invalid('unit_discount_cents'),
    ('a20', 'role:failure'): valid({'currency': 'USD', 'revenue_cents': 160000,
        'variable_cost_cents': 96000, 'gross_profit_cents': 64000,
        'gross_margin_fraction': {'numerator': 2, 'denominator': 5}}, False),
    ('a21', 'role:difficult'): valid({'currency': 'USD', 'total_cost_cents': 19000,
        'unit_cost_cents_fraction': {'numerator': 2375, 'denominator': 3}}),
    ('a21', 'role:edge'): valid({'currency': 'USD', 'total_cost_cents': 10000, 'unit_cost_cents_fraction': None}),
    ('a21', 'role:invalid_input'): invalid('units'),
    ('a21', 'role:failure'): valid({'currency': 'USD', 'total_cost_cents': 18000,
        'unit_cost_cents_fraction': {'numerator': 600, 'denominator': 1}}, False),
}


def review(agent, case, answer):
    return review_numeric_variant_output(agent, 'responsibility.'+agent, case, json.dumps(answer))


@pytest.mark.parametrize('agent,case', ANSWERS)
def test_actual_role_outputs_match_independent_arithmetic_and_refusals(agent, case):
    assert review(agent, case, ANSWERS[agent, case]) == (True, ())


@pytest.mark.parametrize('agent,case', ANSWERS)
def test_every_case_rejects_an_unobserved_execution_claim(agent, case):
    answer = deepcopy(ANSWERS[agent, case]); answer['execution_performed'] = True
    assert not review(agent, case, answer)[0]


def corrupt(value):
    if type(value) is dict:
        for key, item in value.items():
            if type(item) is int:
                value[key] = item+1
                return True
            if corrupt(item):
                return True
    return False


@pytest.mark.parametrize('agent,case', ANSWERS)
def test_wrong_calculation_or_invented_invalid_input_answer_is_rejected(agent, case):
    answer = deepcopy(ANSWERS[agent, case])
    if answer['result'] is None:
        answer.update(input_status='VALID', errors=[], result={'invented_answer': 0})
    else:
        assert corrupt(answer['result'])
    assert not review(agent, case, answer)[0]


@pytest.mark.parametrize('agent', SUPPORTED_AGENTS)
def test_prior_draft_cannot_be_promoted_to_supported(agent):
    answer = deepcopy(ANSWERS[agent, 'role:failure']); answer['prior_result_supported'] = True
    assert not review(agent, 'role:failure', answer)[0]


@pytest.mark.parametrize('agent,case', ANSWERS)
def test_source_contract_is_distinct_bounded_and_preserves_normal_request_route(agent, case):
    capability = 'responsibility.'+agent
    before = canonical_role_spec(agent, capability)
    spec = canonical_numeric_variant_case(case, agent_id=agent, capability_id=capability)
    assert spec['case'] == case and spec['oracle_version'] == ORACLE_VERSION
    assert spec['certification'] == 'UNVERIFIED'
    assert spec['request']['objective'] != before['request']['objective']
    assert spec['request']['context'] != before['request']['context']
    for field in ('classification', 'data_classification', 'minimum_tier', 'priority', 'task_class', 'max_cost_usd'):
        assert spec['request'][field] == before['request'][field]
    assert spec['request']['data_classification'] == 'LOCAL_ONLY'
    assert spec['request']['max_cost_usd'] == 0
    assert spec['request']['response_format'] == 'strict_json'
    inputs = json.loads(spec['request']['context'])
    assert set(inputs) == {'input_version', 'facts'} and inputs['input_version'] == ORACLE_VERSION
    assert 'expected_result' not in inputs['facts'] and 'answer' not in inputs['facts']
    assert canonical_role_spec(agent, capability) == before
    spec['request']['objective'] = 'caller rewrite'
    assert canonical_numeric_variant_case(case, agent_id=agent, capability_id=capability)['request']['objective'] != 'caller rewrite'


@pytest.mark.parametrize('agent,capability,case', [
    ('a19', 'responsibility.a19', 'role:difficult'),
    ('a01', 'responsibility.a04', 'role:edge'),
    ('a20', 'economic.proposition', 'role:failure'),
    ('a01', 'responsibility.a01', 'role:normal'),
    ('a01', 'responsibility.a01', 'role:invalid'),
])
def test_unowned_or_frozen_or_misspelled_cases_are_never_claimed(agent, capability, case):
    with pytest.raises(ValueError):
        canonical_numeric_variant_case(case, agent_id=agent, capability_id=capability)
    assert not review_numeric_variant_output(agent, capability, case, '{}')[0]


@pytest.mark.parametrize('response', [
    '{}', '[]', 'null', '```json\n{}\n```', '{"x":1,"x":2}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '\ud800', 'x'*8193,
])
def test_malformed_nonfinite_duplicate_or_oversized_output_is_rejected(response):
    assert not review_numeric_variant_output('a01', 'responsibility.a01', 'role:difficult', response)[0]


@pytest.mark.parametrize('replacement', [True, 13.0, '13'])
def test_bool_float_or_string_cannot_replace_integer_quantity(replacement):
    answer = deepcopy(ANSWERS['a01', 'role:difficult']); answer['result']['total_points'] = replacement
    assert not review('a01', 'role:difficult', answer)[0]


def test_nested_duplicate_and_extra_certification_field_are_denied():
    answer = deepcopy(ANSWERS['a01', 'role:difficult'])
    raw = json.dumps(answer).replace('"total_points": 13', '"total_points": 0, "total_points": 13')
    assert not review_numeric_variant_output('a01', 'responsibility.a01', 'role:difficult', raw)[0]
    answer['certification'] = 'PASS'
    assert not review('a01', 'role:difficult', answer)[0]


def test_fraction_must_be_reduced_and_denominator_cannot_be_inverted():
    answer = deepcopy(ANSWERS['a20', 'role:difficult'])
    for fraction in ({'numerator': 8, 'denominator': 22}, {'numerator': 11, 'denominator': 4}):
        answer['result']['gross_margin_fraction'] = fraction
        assert not review('a20', 'role:difficult', answer)[0]


def test_allocator_uses_resource_then_lexicographic_tie_break_from_supplied_facts():
    source = {'available_days': 2, 'projects': [{'id': 'C', 'days': 2, 'points': 6},
              {'id': 'B', 'days': 1, 'points': 6}, {'id': 'A', 'days': 1, 'points': 6}]}
    assert _derive('a01', source) == valid({'selected_projects': ['A', 'B'], 'used_days': 2, 'total_points': 12})
    source['available_days'] = 1
    assert _derive('a01', source) == valid({'selected_projects': ['A'], 'used_days': 1, 'total_points': 6})


@pytest.mark.parametrize('source,error', [
    ({'before': {'failures': True, 'requests': 10}, 'after': {'failures': 0, 'requests': 10}}, 'before.failures'),
    ({'before': {'failures': 11, 'requests': 10}, 'after': {'failures': 0, 'requests': 10}}, 'before.failures'),
])
def test_invalid_count_types_and_impossible_counts_are_rejected_before_arithmetic(source, error):
    assert _derive('a12', source) == invalid(error)


def test_exact_matrix_population_and_case_identifiers():
    assert len(PRIMARY_PAIRS) == 6 and len(SUPPORTED_CASES) == 4
    assert set(ANSWERS) == {(agent, case) for agent in SUPPORTED_AGENTS for case in SUPPORTED_CASES}
    from app.agent_cert_cases import case_ids
    assert set(SUPPORTED_CASES) <= set(case_ids())
