"""Source-owned numeric role variants; no execution, recovery or L7 award.

Each verdict recomputes a bounded synthetic problem from its supplied typed
facts. A prior draft is unverified input, never an observed failure event. The
frozen role:normal requests and oracles are not changed or used as answer keys.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
import re


ORACLE_VERSION = 'cert.role-numeric-variants.v1'
SUPPORTED_CASES = ('role:difficult', 'role:edge', 'role:invalid_input', 'role:failure')
SUPPORTED_AGENTS = ('a01', 'a04', 'a05', 'a12', 'a20', 'a21')
PRIMARY_PAIRS = frozenset((agent, 'responsibility.'+agent) for agent in SUPPORTED_AGENTS)
MAX_RESPONSE_BYTES = 8192

_INPUTS = {
    'a01': {
        'role:difficult': {'available_days': 4, 'projects': [
            {'id': 'Alpha', 'days': 3, 'points': 8}, {'id': 'Beta', 'days': 2, 'points': 6},
            {'id': 'Gamma', 'days': 2, 'points': 7}, {'id': 'Delta', 'days': 1, 'points': 2}]},
        'role:edge': {'available_days': 0, 'projects': [
            {'id': 'Alpha', 'days': 3, 'points': 8}, {'id': 'Beta', 'days': 2, 'points': 6}]},
        'role:invalid_input': {'available_days': -1, 'projects': [
            {'id': 'Alpha', 'days': 3, 'points': 8}]},
        'role:failure': {'available_days': 3, 'projects': [
            {'id': 'Alpha', 'days': 3, 'points': 8}, {'id': 'Beta', 'days': 2, 'points': 6},
            {'id': 'Gamma', 'days': 1, 'points': 5}],
            'prior_result': {'selected_projects': ['Alpha'], 'total_points': 8}},
    },
    'a04': {
        'role:difficult': {'weights': {'reliability': 4, 'speed': 2, 'maintainability': 1},
            'options': [{'id': 'A', 'scores': {'reliability': 7, 'speed': 4, 'maintainability': 8}},
                        {'id': 'B', 'scores': {'reliability': 5, 'speed': 8, 'maintainability': 6}},
                        {'id': 'C', 'scores': {'reliability': 8, 'speed': 5, 'maintainability': 3}}]},
        'role:edge': {'weights': {'reliability': 0, 'speed': 0},
            'options': [{'id': 'A', 'scores': {'reliability': 4, 'speed': 1}},
                        {'id': 'B', 'scores': {'reliability': 2, 'speed': 5}}]},
        'role:invalid_input': {'weights': {'reliability': 2, 'speed': 1},
            'options': [{'id': 'A', 'scores': {'reliability': 4}}]},
        'role:failure': {'weights': {'reliability': 1, 'speed': 4},
            'options': [{'id': 'A', 'scores': {'reliability': 4, 'speed': 1}},
                        {'id': 'B', 'scores': {'reliability': 2, 'speed': 5}}],
            'prior_result': {'winners': ['A']}},
    },
    'a05': {
        'role:difficult': {'available_slots': 4, 'projects': [
            {'id': 'P', 'slots': 3, 'value': 8}, {'id': 'Q', 'slots': 2, 'value': 7},
            {'id': 'R', 'slots': 2, 'value': 9}, {'id': 'S', 'slots': 1, 'value': 1}]},
        'role:edge': {'available_slots': 0, 'projects': [
            {'id': 'P', 'slots': 1, 'value': 8}, {'id': 'Q', 'slots': 1, 'value': 5}]},
        'role:invalid_input': {'available_slots': 1, 'projects': [
            {'id': 'P', 'slots': 1, 'value': 8}, {'id': 'P', 'slots': 1, 'value': 5}]},
        'role:failure': {'available_slots': 2, 'projects': [
            {'id': 'P', 'slots': 1, 'value': 8}, {'id': 'Q', 'slots': 2, 'value': 11},
            {'id': 'R', 'slots': 1, 'value': 7}], 'prior_result': {'selected_projects': ['Q']}},
    },
    'a12': {
        'role:difficult': {'before': {'failures': 9, 'requests': 120},
                           'after': {'failures': 6, 'requests': 30}},
        'role:edge': {'before': {'failures': 0, 'requests': 10},
                     'after': {'failures': 0, 'requests': 20}},
        'role:invalid_input': {'before': {'failures': 0, 'requests': 0},
                              'after': {'failures': 1, 'requests': 20}},
        'role:failure': {'before': {'failures': 2, 'requests': 20},
                         'after': {'failures': 1, 'requests': 5},
                         'prior_result': {'lower_failure_rate': 'after'}},
    },
    'a20': {
        'role:difficult': {'units': 125, 'unit_price_cents': 2400,
            'unit_variable_cost_cents': 1400, 'unit_discount_cents': 200, 'currency': 'USD'},
        'role:edge': {'units': 0, 'unit_price_cents': 2000,
            'unit_variable_cost_cents': 1200, 'unit_discount_cents': 0, 'currency': 'USD'},
        'role:invalid_input': {'units': 10, 'unit_price_cents': 100,
            'unit_variable_cost_cents': 50, 'unit_discount_cents': 101, 'currency': 'USD'},
        'role:failure': {'units': 80, 'unit_price_cents': 2000,
            'unit_variable_cost_cents': 1200, 'unit_discount_cents': 0, 'currency': 'USD',
            'prior_result': {'gross_margin_fraction': {'numerator': 2, 'denominator': 3}}},
    },
    'a21': {
        'role:difficult': {'fixed_cost_cents': 10000, 'unit_variable_cost_cents': 375,
                           'units': 24, 'currency': 'USD'},
        'role:edge': {'fixed_cost_cents': 10000, 'unit_variable_cost_cents': 375,
                     'units': 0, 'currency': 'USD'},
        'role:invalid_input': {'fixed_cost_cents': 10000,
                              'unit_variable_cost_cents': 375, 'currency': 'USD'},
        'role:failure': {'fixed_cost_cents': 12000, 'unit_variable_cost_cents': 200,
                         'units': 30, 'currency': 'USD',
                         'prior_result': {'total_cost_cents': 14000}},
    },
}

_OBJECTIVES = {
    'a01': ('Select indivisible projects maximizing TOTAL estimated points within available engineer-days. '
            'Break ties by fewer days used, then lexicographic project IDs. Result fields: '
            'selected_projects (sorted IDs), used_days (integer), total_points (integer).'),
    'a04': ('Multiply every supplied criterion score by its weight and sum each option. Include all tied '
            'winners in lexicographic order. Result fields: scores (option-ID to integer total), '
            'winners (sorted IDs), maximum_score (integer). Zero weights are valid.'),
    'a05': ('Select independent, indivisible projects maximizing TOTAL expected value within available '
            'slots. Break ties by fewer slots used, then lexicographic IDs. Result fields: '
            'selected_projects (sorted IDs), used_slots (integer), total_value (integer).'),
    'a12': ('Compare failure COUNTS and failure RATES separately. Result fields: before_rate_fraction, '
            'after_rate_fraction, failure_count_change (after minus before), lower_failure_rate '
            '(before, after or equal), relative_failure_rate_change_fraction ((after rate minus before '
            'rate) divided by before rate; null when the before rate is zero). Each exact fraction is '
            'a reduced object with integer numerator and positive integer denominator.'),
    'a20': ('Apply the per-unit discount to selling price before computing revenue, variable cost and '
            'gross profit. Gross margin divides gross profit by REVENUE, not variable cost. Result '
            'fields: currency, revenue_cents, variable_cost_cents, gross_profit_cents, '
            'gross_margin_fraction (reduced integer numerator/positive denominator, null for zero '
            'revenue). Fixed costs and market demand are not supplied; do not invent them.'),
    'a21': ('Compute fixed cost plus variable cost times volume. Result fields: currency, '
            'total_cost_cents (integer), unit_cost_cents_fraction (reduced integer numerator/positive '
            'denominator, null for zero volume). Revenue and profit are not supplied.'),
}


def _integer(value, *, minimum=0, maximum=10**9):
    return type(value) is int and minimum <= value <= maximum


def _field(source, key, errors, *, path='', minimum=0):
    if not isinstance(source, dict) or not _integer(source.get(key), minimum=minimum):
        errors.append(path+key)


def _fraction(value):
    return {'numerator': value.numerator, 'denominator': value.denominator}


def _allocate(source, *, budget, demand, reward, used, total, errors):
    _field(source, budget, errors)
    projects = source.get('projects')
    if type(projects) is not list or not 1 <= len(projects) <= 8:
        errors.append('projects'); return None
    names = set()
    for i, row in enumerate(projects):
        path = f'projects[{i}].'
        if (type(row) is not dict or type(row.get('id')) is not str
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,19}', row['id']) or row['id'] in names):
            errors.append(path+'id')
        else:
            names.add(row['id'])
        _field(row, demand, errors, path=path, minimum=1)
        _field(row, reward, errors, path=path)
    if errors:
        return None
    choices = []
    for mask in range(1 << len(projects)):
        selected = [row for i, row in enumerate(projects) if mask & (1 << i)]
        amount = sum(row[demand] for row in selected)
        if amount <= source[budget]:
            choices.append((sum(row[reward] for row in selected), amount,
                            tuple(sorted(row['id'] for row in selected))))
    value, amount, names = min(choices, key=lambda item: (-item[0], item[1], item[2]))
    return {'selected_projects': list(names), used: amount, total: value}


def _weighted(source, errors):
    weights, options = source.get('weights'), source.get('options')
    if (type(weights) is not dict or not 1 <= len(weights) <= 8
            or any(type(key) is not str or not key or not _integer(value)
                   for key, value in weights.items())):
        errors.append('weights')
    if type(options) is not list or not 1 <= len(options) <= 8:
        errors.append('options')
    if errors:
        return None
    names = set()
    for i, row in enumerate(options):
        path = f'options[{i}].'
        if type(row) is not dict or type(row.get('id')) is not str or not row['id'] or row['id'] in names:
            errors.append(path+'id')
        else:
            names.add(row['id'])
        scores = row.get('scores') if type(row) is dict else None
        if type(scores) is not dict:
            errors.append(path+'scores'); continue
        for key in sorted(set(scores) | set(weights)):
            if key not in weights or not _integer(scores.get(key)):
                errors.append(path+'scores.'+key)
    if errors:
        return None
    scores = {row['id']: sum(weights[key]*row['scores'][key] for key in weights) for row in options}
    maximum = max(scores.values())
    return {'scores': scores, 'winners': sorted(key for key in scores if scores[key] == maximum),
            'maximum_score': maximum}


def _rates(source, errors):
    for key in ('before', 'after'):
        period = source.get(key)
        _field(period, 'failures', errors, path=key+'.')
        _field(period, 'requests', errors, path=key+'.', minimum=1)
        if (type(period) is dict and _integer(period.get('failures'))
                and _integer(period.get('requests')) and period['failures'] > period['requests']):
            errors.append(key+'.failures')
    if errors:
        return None
    before = Fraction(source['before']['failures'], source['before']['requests'])
    after = Fraction(source['after']['failures'], source['after']['requests'])
    return {'before_rate_fraction': _fraction(before), 'after_rate_fraction': _fraction(after),
            'failure_count_change': source['after']['failures']-source['before']['failures'],
            'lower_failure_rate': 'before' if before < after else 'after' if after < before else 'equal',
            'relative_failure_rate_change_fraction': _fraction((after-before)/before) if before else None}


def _money(agent, source, errors):
    keys = (('units', 'unit_price_cents', 'unit_variable_cost_cents', 'unit_discount_cents')
            if agent == 'a20' else ('fixed_cost_cents', 'unit_variable_cost_cents', 'units'))
    for key in keys:
        _field(source, key, errors)
    if source.get('currency') != 'USD':
        errors.append('currency')
    if (agent == 'a20' and _integer(source.get('unit_price_cents'))
            and _integer(source.get('unit_discount_cents'))
            and source['unit_discount_cents'] > source['unit_price_cents']):
        errors.append('unit_discount_cents')
    if errors:
        return None
    units = source['units']
    variable = units*source['unit_variable_cost_cents']
    if agent == 'a20':
        revenue = units*(source['unit_price_cents']-source['unit_discount_cents'])
        profit = revenue-variable
        return {'currency': 'USD', 'revenue_cents': revenue, 'variable_cost_cents': variable,
                'gross_profit_cents': profit,
                'gross_margin_fraction': _fraction(Fraction(profit, revenue)) if revenue else None}
    total = source['fixed_cost_cents']+variable
    return {'currency': 'USD', 'total_cost_cents': total,
            'unit_cost_cents_fraction': _fraction(Fraction(total, units)) if units else None}


def _equal(actual, expected):
    """Typed equality keeps booleans, integers, lists and null distinct."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(_equal(actual[k], expected[k]) for k in expected)
    if type(expected) is list:
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _derive(agent, source):
    errors = []
    if agent == 'a01':
        result = _allocate(source, budget='available_days', demand='days', reward='points',
                           used='used_days', total='total_points', errors=errors)
    elif agent == 'a05':
        result = _allocate(source, budget='available_slots', demand='slots', reward='value',
                           used='used_slots', total='total_value', errors=errors)
    elif agent == 'a04':
        result = _weighted(source, errors)
    elif agent == 'a12':
        result = _rates(source, errors)
    else:
        result = _money(agent, source, errors)
    prior = source.get('prior_result')
    prior_supported = None
    if prior is not None and result is not None:
        prior_supported = (type(prior) is dict and bool(prior)
                           and all(key in result and _equal(value, result[key]) for key, value in prior.items()))
    return {'input_status': 'INVALID' if errors else 'VALID', 'errors': sorted(set(errors)),
            'result': result, 'prior_result_supported': prior_supported, 'execution_performed': False}


def _owned(agent_id, capability_id, case_id):
    if (agent_id, capability_id) not in PRIMARY_PAIRS or case_id not in SUPPORTED_CASES:
        raise ValueError('NUMERIC_VARIANT_UNSUPPORTED')
    from .agent_registry import responsibility_owner
    if responsibility_owner(capability_id) != agent_id:
        raise ValueError('NUMERIC_VARIANT_OWNER_MISMATCH')


def canonical_numeric_variant_case(case_id, *, agent_id, capability_id):
    """Return only the fixed source-owned case, without derived answer values."""
    _owned(agent_id, capability_id, case_id)
    from .agent_cert_role_review import canonical_role_spec
    baseline = canonical_role_spec(agent_id, capability_id)
    request = deepcopy(baseline['request'])
    request.pop('response_schema', None)
    request.pop('response_schema_order', None)
    request.update(objective=(
        'For this bounded synthetic numeric-role exercise: '+_OBJECTIVES[agent_id]+
        ' Validate required input fields before arithmetic; budgets, counts and money use integers '
        '(booleans are not integers). Demands must be positive, identifiers unique, failure counts '
        'no greater than positive request counts, and discounts no greater than price. '
        'Return only a strict JSON object with input_status (VALID or INVALID), errors (sorted exact '
        'missing/invalid input field paths), result (the stated result object, or null for invalid '
        'inputs), prior_result_supported (null when inputs are invalid or no prior_result is supplied, '
        'otherwise whether the nonempty prior draft contains only supported fields and every supplied '
        'field follows from the current facts), and execution_performed (boolean). This last field '
        'describes tests, tools, recovery or external actions, not model inference: this supplied-facts '
        'exercise performs none of those actions. '
        'A prior draft is unverified input. Derive the answer from facts; do not invent missing values '
        'or claim tests, tools, recovery, external actions, independent review or certification occurred.'),
        context=json.dumps({'input_version': ORACLE_VERSION, 'facts': deepcopy(_INPUTS[agent_id][case_id])},
                           sort_keys=True, separators=(',', ':'), allow_nan=False),
        response_format='strict_json')
    return {'agent_id': agent_id, 'capability_id': capability_id, 'case': case_id,
            'oracle_version': ORACLE_VERSION, 'request': request,
            'independent_review': ('authenticated_owner', 'registered_owned_capability_route',
                                   'original_numeric_role_output', 'registered_peer_review',
                                   'source_and_execution_artifact_join', 'independent_verifier'),
            'expected_discriminants': ('Derive role-specific quantities from supplied typed inputs',
                                      'Reject invalid inputs without invented numeric results',
                                      'Unverified prior drafts and synthetic facts are not execution events'),
            'certification': 'UNVERIFIED'}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_FIELD')
        result[key] = value
    return result


def review_numeric_variant_output(agent_id, capability_id, case_id, response):
    """Grade only this source-owned numeric output, never an execution event."""
    try:
        _owned(agent_id, capability_id, case_id)
        if type(response) is not str or not 0 < len(response.encode('utf-8')) <= MAX_RESPONSE_BYTES:
            raise ValueError('RESPONSE_SIZE')
        actual = json.loads(response, object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE')))
        expected = _derive(agent_id, _INPUTS[agent_id][case_id])
        if not _equal(actual, expected):
            return False, ('numeric_variant_fact_or_type_mismatch',)
        return True, ()
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return False, ('numeric_variant_invalid_or_unsupported',)
