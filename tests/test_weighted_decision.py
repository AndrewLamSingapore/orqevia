"""Independent changed-input arithmetic and malformed-input checks; no model."""
import json

import pytest

from app.weighted_decision import solve_from_context


def request(weights=None, options=None):
    return {'criterion_weights': weights or {'reliability': 2, 'speed': 1},
        'option_criterion_scores': options or [
            {'option': 'A', 'reliability': 4, 'speed': 1},
            {'option': 'B', 'reliability': 2, 'speed': 5}]}


def solve(value):
    return solve_from_context(json.dumps(value).encode())


def test_original_a04_tie_and_changed_weight_have_independent_expected_answers():
    tied=solve(request())
    assert tied['scores']=={'A':9,'B':9}
    assert tied['decision']=='TIE' and tied['winners']==['A','B']
    assert tied['missing_tie_breaker'] is True
    changed=solve(request(weights={'reliability':1,'speed':3}))
    assert changed['scores']=={'A':7,'B':17}
    assert changed['decision']=='B' and changed['missing_tie_breaker'] is False


def test_arbitrary_criteria_three_options_and_exact_fractional_weights():
    value=request(weights={'quality':'1/2','price':'1/3','service':'1/6'},options=[
        {'option':'first','quality':6,'price':3,'service':0},
        {'option':'second','quality':0,'price':3,'service':6},
        {'option':'third','quality':4,'price':3,'service':6}])
    result=solve(value)
    assert result['scores']=={'first':4,'second':2,'third':4}
    assert result['winners']==['first','third'] and result['missing_tie_breaker']
    value['criterion_weights']['quality']=0.5
    assert solve(value)['scores']==result['scores']


@pytest.mark.parametrize('value', [True, None, 'NaN', '1/0', float('inf'), -1])
def test_invalid_or_negative_weights_never_reach_calculation(value):
    body=request()
    body['criterion_weights']['speed']=value
    with pytest.raises(ValueError):solve(body)


def test_missing_criterion_all_zero_weights_and_duplicate_options_are_rejected():
    body=request();del body['option_criterion_scores'][0]['speed']
    with pytest.raises(ValueError):solve(body)
    body=request();body['criterion_weights']={'reliability':0,'speed':0}
    with pytest.raises(ValueError):solve(body)
    body=request();body['option_criterion_scores'][1]['option']='A'
    with pytest.raises(ValueError):solve(body)


def test_duplicate_json_fields_are_rejected_without_normalizing_away_the_error():
    raw=b'{"criterion_weights":{"quality":1,"quality":2},"option_criterion_scores":[]}'
    with pytest.raises(ValueError):solve_from_context(raw)


def test_booleans_cannot_be_used_as_option_scores():
    body=request();body['option_criterion_scores'][0]['speed']=True
    with pytest.raises(ValueError):solve(body)


def test_json_decimal_precision_is_preserved_before_comparing_scores():
    raw=b'{"criterion_weights":{"quality":1},"option_criterion_scores":[{"option":"A","quality":0.100000000000000001},{"option":"B","quality":0.1}]}'
    result=solve_from_context(raw)
    assert result['decision']=='A' and result['scores']['B']=='1/10'
    scientific=raw.replace(b'0.100000000000000001',b'1.00000000000000001e-1')
    assert solve_from_context(scientific)['scores']==result['scores']


def test_excessive_decimal_exponent_is_rejected_before_integer_allocation():
    raw=b'{"criterion_weights":{"quality":1e-999999999},"option_criterion_scores":[]}'
    with pytest.raises(ValueError):solve_from_context(raw)
    extreme=raw.replace(b'1e-999999999',b'1e9999999999999999999')
    with pytest.raises(ValueError):solve_from_context(extreme)
