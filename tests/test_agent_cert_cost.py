"""A21 cost oracle source fixtures are not live execution or L7 evidence."""
import json

import pytest

from app.agent_cert_cost import cost_facts, review_cost_json


SOURCE = {"fixed_cost": 100, "variable_cost_per_unit": 3, "volume": 20}
EXPECTED = {
    **SOURCE, "total_variable_cost": 60, "total_cost": 160,
    "average_cost_per_unit": "8/1", "cost_at_next_unit": 163,
    "incremental_cost_next_unit": 3, "revenue_known": False,
    "profit_known": False,
}


def test_fixed_variable_average_and_incremental_costs_are_distinct():
    assert cost_facts(SOURCE) == EXPECTED
    assert review_cost_json(SOURCE, json.dumps(EXPECTED)) == (True, ())
    for changed, field in (
        ({"total_variable_cost": 160}, "total_variable_cost"),
        ({"total_cost": 60}, "total_cost"),
        ({"average_cost_per_unit": "3/1"}, "average_cost_per_unit"),
        ({"cost_at_next_unit": 263}, "cost_at_next_unit"),
        ({"incremental_cost_next_unit": 8}, "incremental_cost_next_unit"),
        ({"revenue_known": True}, "revenue_known"),
        ({"profit_known": True}, "profit_known"),
    ):
        valid, errors = review_cost_json(SOURCE, json.dumps({**EXPECTED, **changed}))
        assert not valid and field in errors


def test_held_out_source_recomputes_reduced_fraction_and_next_unit():
    held_out = {"fixed_cost": 5, "variable_cost_per_unit": 2, "volume": 3}
    expected = {**held_out, "total_variable_cost": 6, "total_cost": 11,
                "average_cost_per_unit": "11/3", "cost_at_next_unit": 13,
                "incremental_cost_next_unit": 2, "revenue_known": False,
                "profit_known": False}
    assert cost_facts(held_out) == expected
    assert review_cost_json(held_out, json.dumps(expected)) == (True, ())
    assert not review_cost_json(held_out, json.dumps(EXPECTED))[0]


def test_duplicate_keys_extra_profit_and_bool_integer_fail_closed():
    duplicate = json.dumps(EXPECTED)[:-1] + ',"total_cost":0}'
    assert review_cost_json(SOURCE, duplicate)[1] == ("not_strict_json",)
    assert review_cost_json(SOURCE, json.dumps({**EXPECTED, "profit": 100}))[1] == (
        "field_contract_mismatch",)
    assert review_cost_json(SOURCE, json.dumps({**EXPECTED, "volume": True}))[1] == (
        "volume",)


@pytest.mark.parametrize("source", [
    {**SOURCE, "volume": 0},
    {**SOURCE, "fixed_cost": -1},
    {**SOURCE, "variable_cost_per_unit": True},
    {**SOURCE, "variable_cost_per_unit": 1_000_001},
    {**SOURCE, "revenue": 200},
])
def test_invalid_source_is_rejected(source):
    with pytest.raises(ValueError):
        cost_facts(source)
