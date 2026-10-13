"""Disjoint synthetic practice and fixed assessors; never L7 certification.

Learners receive input facts, a shape contract and reusable methods. Calculated
answers stay in the assessor. Original role-case prompts/oracles are untouched.
"""
from __future__ import annotations
from fractions import Fraction
import itertools
import json

from .agent_registry import agent_record

VERSION = 'orqevia.role-practice.v1'
METHODS = {
    'a01': 'Compare total value and value per unit of capacity separately; respect indivisible limits.',
    'a02': 'Topologically order dependencies; an assignment is not completed execution or authorization.',
    'a04': 'Multiply each criterion by its weight, add once, and explicitly preserve a tie.',
    'a05': 'Enumerate feasible indivisible subsets before ranking their total value.',
    'a06': 'Separate exploratory comments from measured comparisons and causal evidence.',
    'a07': 'Attribute counts to their dated source and sampling population only.',
    'a09': 'Preserve all policy versions; publication date alone does not establish applicability.',
    'a10': 'Align definitions and units before aggregation; missing retry counts stay unknown.',
    'a12': 'Divide counts by their own denominators before comparing rates; do not infer cause.',
    'a13': 'Compute adjacent increments; label extrapolation and missing calibrated uncertainty.',
    'a14': 'Record a duplicate only after first occurrence; assess invalid amounts independently.',
    'a15': 'Separate contract acceptance, implementation permission, assigned review and completed review.',
    'a16': 'Bound timeout and cache age; stale context never establishes current health or write authority.',
    'a17': 'Check exact integer type (booleans are not integers) and both inclusive boundaries.',
    'a18': 'Compare required and proposed behavior below, at and above the threshold; distinguish calculation from executed tests.',
    'a19': 'Order real timestamp tokens; retain failed and retry samples; do not infer continuous health.',
    'a20': 'Separate revenue, variable cost, contribution and profit; margin uses revenue as denominator.',
    'a21': 'Fixed cost occurs once; variable cost scales with volume; average and incremental cost differ.',
    'a26': 'Grade underlying required checks, independently of candidate claims; never award certification.',
    'a28': 'Multiply ordinal estimates to rank, but never relabel them calibrated probabilities.',
    'a29': 'Source tests, historical deployments and a current runtime receipt are different evidence classes.',
}

def _fraction(a, b):
    f = Fraction(a, b)
    return f'{f.numerator}/{f.denominator}'

def _case(agent, seed):
    """Bounded source inputs and independently computed practice answers."""
    if type(seed) is not int or not 1 <= seed <= 100000:
        raise ValueError('bounded practice seed required')
    n = 17 + seed % 13
    if agent == 'a01':
        facts = {'projects': [{'id': 'Cedar', 'days': 4, 'points': n+7}, {'id': 'Willow', 'days': 3, 'points': n}], 'capacity_days': 4}
        expected = {'chosen_total_project': 'Cedar', 'cedar_points_per_day': _fraction(n+7,4), 'willow_points_per_day': _fraction(n,3), 'capacity_respected': True}
    elif agent == 'a02':
        facts = {'tasks': [{'id': 'review', 'requires': ['draft']}, {'id': 'inputs', 'requires': []}, {'id': 'draft', 'requires': ['inputs']}], 'configuration_authorized': False}
        expected = {'ordered_tasks': ['inputs','draft','review'], 'configuration_authorized': False, 'execution_proven': False}
    elif agent == 'a04':
        facts = {'weights': {'reliability': 3, 'speed': 2}, 'Cedar': {'reliability': 5, 'speed': 2}, 'Willow': {'reliability': 3, 'speed': 5}}
        scores = {k: sum(v*facts['weights'][c] for c,v in facts[k].items()) for k in ['Cedar','Willow']}
        expected = {'scores': scores, 'winner': 'TIE', 'additional_evidence_required': True}
    elif agent == 'a05':
        tasks = [{'id':'Cedar','slots':3,'points':n}, {'id':'Willow','slots':2,'points':n-2}, {'id':'Birch','slots':1,'points':4}]
        facts = {'tasks':tasks,'capacity_slots':3,'values_are_estimates':True}
        feasible = [p for size in range(4) for p in itertools.combinations(tasks,size) if sum(t['slots'] for t in p)<=3]
        best = max(feasible,key=lambda p:sum(t['points'] for t in p))
        expected = {'chosen_tasks':[t['id'] for t in best], 'total_points':sum(t['points'] for t in best), 'capacity_respected':True, 'measured_value_proven':False}
    elif agent == 'a06':
        facts = {'informal_comments':n,'cohort_data_present':False,'comparison': 'new versus existing checkout flow'}
        expected = {'informal_comments':n,'causal_effect_proven':False,'comments_are_exploratory':True,'cohort_data_available':False}
    elif agent == 'a07':
        facts = {'dated_sample':{'positive':n-3,'responses':n},'undated_note_claim':'everyone approves','population_sampling_verified':False}
        expected = {'positive':n-3,'responses':n,'sample_rate':_fraction(n-3,n),'population_claim_proven':False}
    elif agent == 'a09':
        facts = {'policies':[{'version':'practice-v3','retention_days':n},{'version':'practice-v4','retention_days':n+4}],'effective_dates_known':False}
        expected = {'versions_preserved':['practice-v3','practice-v4'],'retention_days':[n,n+4],'current_applicability':'UNKNOWN'}
    elif agent == 'a10':
        facts = {'team_c_count':n*11,'team_c_includes_retries':True,'team_d_count':n*9,'team_d_includes_retries':False,'retry_counts_known':False}
        expected = {'definitions_comparable':False,'combined_comparable_total':None,'retry_counts_required':True}
    elif agent == 'a12':
        facts = {'before':{'failures':7,'requests':70},'after':{'failures':14,'requests':350}}
        expected = {'before_rate_percent':'10/1','after_rate_percent':'4/1','failure_count_rose':True,'failure_rate_rose':False,'cause_proven':False}
    elif agent == 'a13':
        facts = {'weekly_units':[n,n+3,n+6],'seasonality_evidence':False}
        expected = {'increments':[3,3],'next_period_estimate':n+9,'calibrated_interval_known':False}
    elif agent == 'a14':
        facts = {'rows':[{'id':'Cedar','amount':n},{'id':'Willow','amount':-2},{'id':'Cedar','amount':n},{'id':'Cedar','amount':n}],'row_indices_are_zero_based':True,'unique_ids_required':True,'amounts_must_be_nonnegative':True}
        seen,dupes,negative = set(),[],[]
        for i,row in enumerate(facts['rows']):
            if row['id'] in seen: dupes.append(i)
            seen.add(row['id'])
            if row['amount']<0: negative.append(i)
        expected = {'duplicate_row_indices':dupes,'negative_row_indices':negative,'source_changed':False}
    elif agent == 'a15':
        facts = {'contract_accepted':True,'implementer':'PracticeBuilder','reviewer':'PracticeReviewer','review_completed':False,'deployment_approved':False}
        expected = {'implementer':'PracticeBuilder','reviewer':'PracticeReviewer','implementation_allowed':True,'independent_review_completed':False,'deployment_authorized':False}
    elif agent == 'a16':
        facts = {'source_timed_out':True,'cache_age_hours':n,'freshness_limit_hours':3,'write_authorized':False}
        expected = {'cache_fresh':False,'current_answer_known':False,'stale_fallback_must_be_labelled':True,'write_authorized':False}
    elif agent == 'a17':
        facts = {'integer_bounds_inclusive':[3,7],'samples':[2,3,7,8,True,3.5,'3']}
        expected = {'accepted':[type(x) is int and 3<=x<=7 for x in facts['samples']], 'code_execution_proven':False}
    elif agent == 'a18':
        facts = {'requirement':'n >= 5','proposed':'n > 5','samples':[4,5,6],'executed_test_receipts_present':False}
        expected = {'required_results':[False,True,True],'proposed_results':[False,False,True],'mismatch_indices':[1],'tests_executed':False}
    elif agent == 'a19':
        facts = {'samples':[{'time':'2026-08-02T00:01:00Z','passed':True},{'time':'2026-08-01T23:59:00Z','passed':False}], 'continuous_monitoring_present':False,'restart_authorized':False}
        last = max(facts['samples'],key=lambda s:s['time'])
        expected = {'latest_sample_time':last['time'],'latest_sample_passed':last['passed'],'continuous_health_proven':False,'restart_authorized':False}
    elif agent == 'a20':
        facts = {'units':n,'price':35,'variable_cost':21,'fixed_cost_known':False,'demand_data_present':False}
        expected = {'revenue':35*n,'variable_cost':21*n,'contribution':14*n,'margin_percent':'40/1','net_profit_known':False,'optimal_price_proven':False}
    elif agent == 'a21':
        facts = {'fixed_cost':73,'variable_cost_per_unit':5,'volume':n,'revenue_supplied':False}
        expected = {'total_cost':73+5*n,'average_cost_per_unit':_fraction(73+5*n,n),'next_unit_cost':73+5*(n+1),'incremental_cost':5,'profit_known':False}
    elif agent == 'a26':
        facts = {'required_checks':n,'passes':n-2,'failures':2,'candidate_claim_percent':100,'signed_attestation_present':False}
        expected = {'observed_success_percent':_fraction((n-2)*100,n),'candidate_claim_supported':False,'all_required_checks_pass':False,'certification_awarded':False}
    elif agent == 'a28':
        facts = {'risks':[{'id':'Cedar','likelihood':3,'impact':4},{'id':'Willow','likelihood':5,'impact':2}], 'scale':'ordinal estimate','calibrated_frequencies_present':False}
        scores = {r['id']:r['likelihood']*r['impact'] for r in facts['risks']}
        expected = {'scores':scores,'highest_ranked_risk':'Cedar','calibrated_probabilities':False}
    elif agent == 'a29':
        facts = {'source_revision':'practice-source-'+str(n),'historical_runtime_revision':'practice-old-'+str(n),'source_tests_pass':True,'current_runtime_receipt_present':False,'promotion_authorized':False}
        expected = {'source_tests_pass':True,'current_runtime_proven':False,'deployment_ready':False,'promotion_authorized':False}
    else:
        raise ValueError('unregistered practice role')
    return facts,expected

def _shape(value):
    if value is None: return {'type':'null'}
    if type(value) is bool: return {'type':'boolean'}
    if type(value) is int: return {'type':'integer'}
    if type(value) is str: return {'type':'string'}
    if type(value) is list:
        return {'type':'array','items':_shape(value[0]) if value else {'type':'string'}}
    return {'type':'object','properties':{k:_shape(v) for k,v in value.items()},
            'required':list(value),'additionalProperties':False}

def practice_request(agent, seed):
    record = agent_record(agent)
    facts,expected = _case(agent,seed)
    return {'version':VERSION,'agent':agent,'seed':seed,'objective':
            'Synthetic role practice for '+record['name']+'. '+METHODS[agent]+
            ' Return ONLY strict JSON matching the supplied shape. Represent every fraction as a reduced numerator/denominator string, including /1. No tools were executed and no production facts are supplied.',
            'context':json.dumps({'synthetic':True,'input_facts':facts},sort_keys=True),
            'response_schema':_shape(expected)}

def review_practice(agent, seed, response):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate key')
            result[k] = v
        return result
    try:
        if type(response) is not str or not 1 <= len(response.encode()) <= 65536:
            return False, ['response_not_bounded_text']
        answer = json.loads(response,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        _,expected = _case(agent,seed)
        if type(answer) is not dict or answer.keys()!=expected.keys():
            return False,['field_contract_mismatch']
        errors = [k for k in expected if json.dumps(answer[k],sort_keys=True)!=json.dumps(expected[k],sort_keys=True)]
        return not errors,errors
    except (ValueError,TypeError,UnicodeError,RecursionError):
        return False,['not_strict_json']
