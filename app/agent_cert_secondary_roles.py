"""Eight distinct secondary role oracles, not execution or L7 evidence.

The existing 21 registered agents own all 29 responsibilities. These small
public synthetic challenges exercise the eight merged responsibilities, not
aliases of the owners' primary tests. Arithmetic is independently recomputed
from bounded source facts; no answer, registry entry, or fixture grants a level,
authorizes a provider, signs evidence, or claims work actually happened.
"""
from __future__ import annotations

from fractions import Fraction
from itertools import combinations
import json
import math
import re
from types import MappingProxyType


CASE_VERSION = 'secondary-role-normal.v1'
ORACLE_ID = 'secondary-role-exact.v1'
MAX_RESPONSE_BYTES = 16384
SUPPORTED_CAPABILITIES = MappingProxyType({
    'responsibility.a03': 'a02', 'responsibility.a08': 'a04',
    'responsibility.a23': 'a05', 'responsibility.a11': 'a12',
    'responsibility.a27': 'a18', 'responsibility.a24': 'a20',
    'responsibility.a22': 'a21', 'responsibility.a25': 'a26',
})

# Strings keep canonical source facts immutable; every consumer gets a new
# decoded object. They retain the already-existing public synthetic quantities.
_SOURCE_JSON = MappingProxyType({
    'responsibility.a03': '{"milestones":[{"id":"contract","days":2,"requires":[]},{"id":"parser","days":3,"requires":["contract"]},{"id":"review","days":1,"requires":["parser"]}]}',
    'responsibility.a08': '{"options":[{"id":"X","cost_usd":10,"duration_days":4,"error_rate_basis_points":null},{"id":"Y","cost_usd":12,"duration_days":2,"error_rate_basis_points":100}]}',
    'responsibility.a23': '{"capacity_days":2,"tasks":[{"id":"A","days":2,"estimated_points":7},{"id":"B","days":1,"estimated_points":4},{"id":"C","days":1,"estimated_points":2}]}',
    'responsibility.a11': '{"due_this_week":12,"completed_on_time":9,"completed_late":2,"still_open":1,"duplicates":0,"target":null}',
    'responsibility.a27': '{"required_controls":{"A":"PASS","B":"PASS","C":"NOT_TESTED"},"promotion_authorized":false}',
    'responsibility.a24': '{"price_usd":30,"variable_cost_usd":18,"pilot_units":40,"competitor_price_usd":25,"fixed_costs_usd":null,"elasticity":null,"acquisition_cost_usd":null}',
    'responsibility.a22': '{"one_period_benefit":150,"upfront_cost":100,"future_periods":null,"discount_rate":null,"benefit_timing":null}',
    'responsibility.a25': '{"required_tests":{"unit_1":"PASS","unit_2":"PASS","unit_3":"PASS","unit_4":"PASS","unit_5":"PASS","unit_6":"PASS","unit_7":"PASS","unit_8":"PASS","boundary":"FAIL"},"author_claim":"READY","promotion_authorized":false}',
})

_INSTRUCTIONS = MappingProxyType({
    'responsibility.a03': 'Compute dependency-constrained earliest starts/finishes from day zero. Return milestone_schedule entries with exactly id, start_day, finish_day in contract/parser/review order; critical_path, earliest_completion_day, parser_can_precede_contract, and actions_executed. Durations are whole days; no dependency may be bypassed.',
    'responsibility.a08': 'Normalize X and Y using exactly the supplied USD/day/basis-point units. Return options, cost_delta_y_minus_x, days_saved_by_y, cost_and_time_dominating_option, quality_ranking_known, and actions_executed. options entries have exactly id, cost_usd, duration_days, error_rate_basis_points in X/Y order. A dominating option must be no worse in BOTH cost and time and strictly better in at least one. Unknown error rate is JSON null, never zero; do not rank quality without both measurements.',
    'responsibility.a23': 'Enumerate EVERY feasible subset of the three indivisible tasks under capacity_days, including empty. Return feasible_allocations entries with exactly task_ids, used_days, estimated_points, ordered lexicographically by task_ids with empty first; selected_task_ids, selected_points, selected_days, best_alternative_task_ids, best_alternative_points, all_tasks_feasible, values_are_estimates, and actions_executed. Maximize total estimated points; ties use fewer days then lexicographic task IDs. Do not substitute efficiency for the stated total-value objective.',
    'responsibility.a11': 'Define the weekly on-time completion KPI, not eventual completion. Return numerator, denominator, on_time_rate, on_time_percentage, eventual_completed, late_excluded_from_numerator, denominator_includes_late_and_open, window, target_known, and actions_executed. Express rate and percentage as reduced fraction strings including /1; window is THIS_WEEK. Late/open tasks remain in denominator; late tasks do not enter on-time numerator.',
    'responsibility.a27': 'Verify the ALL-required-controls rule from individual observations. Return observed_pass_controls, observed_fail_controls, missing_control_evidence, all_required_controls_observed, compliance_status, promotion_authorized, and actions_executed. Arrays are alphabetically ordered. compliance_status is FAIL on an observed failure, PASS only when every required control passed, otherwise UNVERIFIED. NOT_TESTED is missing evidence, not a measured failure or pass.',
    'responsibility.a24': 'Calculate contribution, not profit or optimal price. Return unit_contribution_usd, pilot_contribution_before_fixed_usd, price_premium_over_competitor_usd, profit_known, optimal_price_proven, elasticity_known, acquisition_cost_known, and actions_executed. Unknown fixed costs prevent a profit claim; a competitor quote and small pilot do not prove demand or optimal pricing.',
    'responsibility.a22': 'Calculate the single-period net benefit and SIMPLE undiscounted ROI, not lifetime value. Return periods_supported, one_period_net_benefit, simple_roi, simple_roi_percentage, payback_time, discounted_value, lifetime_value, and actions_executed. ROI and percentage are reduced fraction strings including /1. Unknown timing, discount rate, and future periods must remain JSON null for their unsupported results.',
    'responsibility.a25': 'Assess the required quality gate independently of the author READY flag. Return required_tests, observed_passes, observed_failures, missing_tests, failed_test_ids, clean_quality_gate, author_ready_claim_is_evidence, next_required_action, promotion_authorized, and actions_executed. Failed IDs are alphabetically ordered. On a required failure, next_required_action is repair_then_rerun_same_failed_case_and_regressions; do not erase the eight observed passes or grant release authority.',
})


def _require(value):
    if value is not True:
        raise ValueError('SECONDARY_SOURCE_INVALID') from None


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _int(value, *, minimum=0, maximum=1000000):
    _require(type(value) is int and minimum <= value <= maximum)
    return value


def _fraction(value):
    return f'{value.numerator}/{value.denominator}'


def _ownership(agent, capability):
    """Require the actual actor and secondary responsibility, never an alias."""
    _require(type(agent) is str and type(capability) is str
             and SUPPORTED_CAPABILITIES.get(capability) == agent)
    from .agent_registry import RegistryError, agent_record, responsibility_owner
    try:
        record = agent_record(agent)
        declared = [r for r in record['responsibilities'] if r['id'] == capability]
        _require(record['id'] == agent and responsibility_owner(capability) == agent
                 and capability in record['capability_requirements']
                 and len(declared) == 1 and record['authority'] == 'advisory'
                 and all(type(declared[0].get(k)) is str and declared[0][k]
                         for k in ('description', 'input', 'output')))
        return declared[0]
    except (RegistryError, KeyError, TypeError):
        raise ValueError('SECONDARY_OWNER_INVALID') from None


def source_facts(capability):
    if type(capability) is not str or capability not in SUPPORTED_CAPABILITIES:
        raise ValueError('SECONDARY_CASE_UNSUPPORTED') from None
    return json.loads(_SOURCE_JSON[capability])


def calculate_secondary_facts(capability, source):
    """Small independent oracle calculations; arbitrary sources are NOT cases.

    This pure helper accepts bounded same-schema facts for boundary regression
    tests. The certification reviewer below always uses the immutable canonical
    public source instead, so caller data cannot redefine the oracle.
    """
    _require(type(capability) is str and capability in SUPPORTED_CAPABILITIES)
    if capability == 'responsibility.a03':
        _fields(source, ('milestones',))
        rows = source['milestones']
        _require(type(rows) is list and len(rows) == 3)
        indexed = {}
        for row in rows:
            _fields(row, ('id', 'days', 'requires'))
            _require(type(row['id']) is str and row['id'] in {'contract', 'parser', 'review'}
                     and row['id'] not in indexed and type(row['requires']) is list
                     and all(type(x) is str for x in row['requires']))
            _int(row['days'], minimum=1, maximum=365)
            indexed[row['id']] = row
        deps = {'contract': [], 'parser': ['contract'], 'review': ['parser']}
        _require(set(indexed) == set(deps) and all(indexed[k]['requires'] == v for k, v in deps.items()))
        schedule = []; finished = {}
        for key in ('contract', 'parser', 'review'):
            start = max((finished[d] for d in deps[key]), default=0)
            finished[key] = start + indexed[key]['days']
            schedule.append(dict(id=key, start_day=start, finish_day=finished[key]))
        return dict(milestone_schedule=schedule, critical_path=['contract', 'parser', 'review'],
            earliest_completion_day=finished['review'], parser_can_precede_contract=False, actions_executed=False)

    if capability == 'responsibility.a08':
        _fields(source, ('options',)); rows = source['options']
        _require(type(rows) is list and len(rows) == 2)
        indexed = {}
        for row in rows:
            _fields(row, ('id', 'cost_usd', 'duration_days', 'error_rate_basis_points'))
            _require(type(row['id']) is str and row['id'] in {'X', 'Y'} and row['id'] not in indexed)
            _int(row['cost_usd']); _int(row['duration_days'], minimum=1, maximum=365)
            if row['error_rate_basis_points'] is not None:
                _int(row['error_rate_basis_points'], maximum=10000)
            indexed[row['id']] = dict(row)
        _require(set(indexed) == {'X', 'Y'})
        x, y = indexed['X'], indexed['Y']
        def dominates(a, b):
            return (a['cost_usd'] <= b['cost_usd'] and a['duration_days'] <= b['duration_days']
                    and (a['cost_usd'], a['duration_days']) != (b['cost_usd'], b['duration_days']))
        winner = 'X' if dominates(x, y) else 'Y' if dominates(y, x) else None
        return dict(options=[x, y], cost_delta_y_minus_x=y['cost_usd'] - x['cost_usd'],
            days_saved_by_y=x['duration_days'] - y['duration_days'],
            cost_and_time_dominating_option=winner,
            quality_ranking_known=all(row['error_rate_basis_points'] is not None for row in (x, y)),
            actions_executed=False)

    if capability == 'responsibility.a23':
        _fields(source, ('capacity_days', 'tasks'))
        capacity = _int(source['capacity_days'], minimum=1, maximum=30)
        rows = source['tasks']; _require(type(rows) is list and len(rows) == 3)
        indexed = {}
        for row in rows:
            _fields(row, ('id', 'days', 'estimated_points'))
            _require(type(row['id']) is str and row['id'] in {'A', 'B', 'C'} and row['id'] not in indexed)
            _int(row['days'], minimum=1, maximum=30); _int(row['estimated_points'])
            indexed[row['id']] = row
        _require(set(indexed) == {'A', 'B', 'C'})
        feasible = []
        for size in range(4):
            for ids in combinations(sorted(indexed), size):
                days = sum(indexed[k]['days'] for k in ids)
                if days <= capacity:
                    feasible.append(dict(task_ids=list(ids), used_days=days,
                        estimated_points=sum(indexed[k]['estimated_points'] for k in ids)))
        feasible.sort(key=lambda item: tuple(item['task_ids']))
        ranked = sorted(feasible, key=lambda item: (-item['estimated_points'], item['used_days'], item['task_ids']))
        best = ranked[0]; alternate = ranked[1] if len(ranked) > 1 else None
        return dict(feasible_allocations=feasible, selected_task_ids=best['task_ids'],
            selected_points=best['estimated_points'], selected_days=best['used_days'],
            best_alternative_task_ids=alternate['task_ids'] if alternate else None,
            best_alternative_points=alternate['estimated_points'] if alternate else None,
            all_tasks_feasible=sum(row['days'] for row in rows) <= capacity,
            values_are_estimates=True, actions_executed=False)

    if capability == 'responsibility.a11':
        _fields(source, ('due_this_week', 'completed_on_time', 'completed_late', 'still_open', 'duplicates', 'target'))
        due = _int(source['due_this_week'], minimum=1)
        on_time, late, opened = (_int(source[k]) for k in ('completed_on_time', 'completed_late', 'still_open'))
        _require(on_time + late + opened == due and type(source['duplicates']) is int
                 and source['duplicates'] == 0 and source['target'] is None)
        rate = Fraction(on_time, due)
        return dict(numerator=on_time, denominator=due, on_time_rate=_fraction(rate),
            on_time_percentage=_fraction(rate * 100), eventual_completed=on_time + late,
            late_excluded_from_numerator=True, denominator_includes_late_and_open=True,
            window='THIS_WEEK', target_known=False, actions_executed=False)

    if capability in {'responsibility.a27', 'responsibility.a25'}:
        control = capability == 'responsibility.a27'
        name = 'required_controls' if control else 'required_tests'
        _fields(source, (name, 'promotion_authorized') if control else (name, 'author_claim', 'promotion_authorized'))
        rows = source[name]
        _require(type(rows) is dict and 1 <= len(rows) <= 32
                 and all(type(k) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,39}', k) is not None
                         and type(v) is str and v in {'PASS', 'FAIL', 'NOT_TESTED'} for k, v in rows.items())
                 and source['promotion_authorized'] is False)
        if control:
            _require(set(rows) == {'A', 'B', 'C'})
        else:
            _require(type(source['author_claim']) is str and source['author_claim'] == 'READY')
        passed = sorted(k for k, v in rows.items() if v == 'PASS')
        failed = sorted(k for k, v in rows.items() if v == 'FAIL')
        missing = sorted(k for k, v in rows.items() if v == 'NOT_TESTED')
        if control:
            return dict(observed_pass_controls=passed, observed_fail_controls=failed,
                missing_control_evidence=missing, all_required_controls_observed=not missing,
                compliance_status='FAIL' if failed else 'UNVERIFIED' if missing else 'PASS',
                promotion_authorized=False, actions_executed=False)
        return dict(required_tests=len(rows), observed_passes=len(passed), observed_failures=len(failed),
            missing_tests=len(missing), failed_test_ids=failed, clean_quality_gate=not failed and not missing,
            author_ready_claim_is_evidence=False,
            next_required_action='repair_then_rerun_same_failed_case_and_regressions' if failed else
                'obtain_missing_required_test_evidence' if missing else 'independent_review_before_release_decision',
            promotion_authorized=False, actions_executed=False)

    if capability == 'responsibility.a24':
        _fields(source, ('price_usd', 'variable_cost_usd', 'pilot_units', 'competitor_price_usd',
                         'fixed_costs_usd', 'elasticity', 'acquisition_cost_usd'))
        price, cost, units, competitor = (_int(source[k]) for k in
            ('price_usd', 'variable_cost_usd', 'pilot_units', 'competitor_price_usd'))
        _require(all(source[k] is None for k in ('fixed_costs_usd', 'elasticity', 'acquisition_cost_usd')))
        contribution = price - cost
        return dict(unit_contribution_usd=contribution, pilot_contribution_before_fixed_usd=contribution * units,
            price_premium_over_competitor_usd=price - competitor, profit_known=False,
            optimal_price_proven=False, elasticity_known=False, acquisition_cost_known=False, actions_executed=False)

    _fields(source, ('one_period_benefit', 'upfront_cost', 'future_periods', 'discount_rate', 'benefit_timing'))
    benefit = _int(source['one_period_benefit']); cost = _int(source['upfront_cost'], minimum=1)
    _require(all(source[k] is None for k in ('future_periods', 'discount_rate', 'benefit_timing')))
    net = benefit - cost; roi = Fraction(net, cost)
    return dict(periods_supported=1, one_period_net_benefit=net, simple_roi=_fraction(roi),
        simple_roi_percentage=_fraction(roi * 100), payback_time=None, discounted_value=None,
        lifetime_value=None, actions_executed=False)


def canonical_secondary_spec(agent, capability):
    """Return one source-owned request; no custom facts, model or tier override."""
    responsibility = _ownership(agent, capability)
    from .agent_cert_cases import challenge
    spec = challenge('role:normal', agent_id=agent, capability_id=capability)
    expected = calculate_secondary_facts(capability, source_facts(capability))
    objective = (f'For registered {agent}, owned capability {capability} '
        f'({responsibility["description"]}), complete this public synthetic advisory case. '
        'Return ONLY one strict JSON object with EXACTLY the named fields and their '
        'literal JSON types. Do not add explanations, Markdown, tool results, '
        'credentials, certification, signed status or executed actions. ' + _INSTRUCTIONS[capability])
    context = 'PUBLIC SYNTHETIC source=secondary-role-normal.v1; facts=' + _SOURCE_JSON[capability]
    # The base challenge provides unchanged runtime/reviewer obligations, not
    # the primary role's answer oracle. A merged capability has its own facts.
    primary_oracles = frozenset(('exact_numeric_oracle', 'exact_rate_oracle',
        'exact_weighted_oracle', 'exact_zero_boundary_oracle', 'exact_a17_boundary_oracle',
        'exact_data_quality_oracle', 'exact_portfolio_oracle', 'exact_cost_oracle',
        'exact_risk_oracle', 'exact_release_oracle', 'exact_role_g1_oracle',
        'group_two_exact_role_oracle'))
    review = tuple(item for item in spec['independent_review'] if item not in primary_oracles)
    return {**spec, 'case_version': CASE_VERSION, 'oracle_id': ORACLE_ID,
        'request': {**spec['request'], 'objective': objective, 'context': context,
            'minimum_tier': 'MINI', 'task_class': 'planning', 'response_format': 'strict_json'},
        'independent_review': (*review, 'exact_secondary_role_oracle'),
        'expected_discriminants': tuple(sorted(expected)),
        'proven_limits': ('one_bounded_public_synthetic_secondary_role_case',
            'no_execution_or_tool_or_recovery_or_general_quality_or_L7_claim'),
        'certification': 'UNVERIFIED'}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_FIELD')
        result[key] = value
    return result


def _finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('NONFINITE_NUMBER')
    return value


def _same_literal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return set(actual) == set(expected) and all(_same_literal(actual[k], expected[k]) for k in expected)
    if type(expected) is list:
        return len(actual) == len(expected) and all(_same_literal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def review_secondary_output(agent, capability, response):
    """Fixed-key, literal-type verdict only; never return raw/private answers."""
    try:
        _ownership(agent, capability)
        expected = calculate_secondary_facts(capability, source_facts(capability))
    except (ValueError, TypeError, KeyError, RuntimeError):
        return False, ('case_oracle_unsupported',)
    if type(response) is not str:
        return False, ('response_not_bounded_text',)
    try:
        if not 1 <= len(response.encode('utf-8')) <= MAX_RESPONSE_BYTES:
            return False, ('response_not_bounded_text',)
        answer = json.loads(response, object_pairs_hook=_unique, parse_float=_finite,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_NUMBER')))
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return False, ('not_strict_json',)
    if type(answer) is not dict or set(answer) != set(expected):
        return False, ('field_contract_mismatch',)
    errors = tuple(k for k in sorted(expected) if not _same_literal(answer[k], expected[k]))
    return not errors, errors
