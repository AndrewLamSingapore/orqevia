"""Independent arithmetic, exhaustive allocation and contract boundary checks."""

from copy import deepcopy
from decimal import Decimal
import itertools
import json
import math
import random

import pytest

from app.fabric_analytics import CONTRACTS, execute


def run(fabric_id, payload):
    return execute(fabric_id, CONTRACTS[fabric_id]["operations"][0]["operation"], payload)


def financial_inputs():
    return {
        "revenue": 1000,
        "rent": 100,
        "salaries": 200,
        "inventory": 200,
        "utilities": 20,
        "marketing": 50,
        "other_expenses": 30,
    }


EXAMPLES = {
    "f21": {"initial_stock": 10, "arrivals": [0, 3, 0], "demands": [4, 12, 2]},
    "f22": {
        "criteria": [
            {"id": "quality", "weight": 3, "direction": "maximize"},
            {"id": "cost", "weight": 1, "direction": "minimize", "maximum": 10},
        ],
        "alternatives": [
            {"id": "A", "values": {"quality": 9, "cost": 8}},
            {"id": "B", "values": {"quality": 5, "cost": 2}},
            {"id": "C", "values": {"quality": 100, "cost": 101}},
        ],
    },
    "f25": {
        "variables": [
            {"name": "x", "intercept": 2, "parents": {}, "noise": 0},
            {"name": "y", "intercept": 1, "parents": {"x": 3}, "noise": 0},
        ],
        "interventions": {"x": 5},
    },
    "f26": {"series": [1, 2, 4, 7], "horizon": 3},
    "f27": {
        "capacity": 5,
        "items": [
            {"id": "A", "cost": 2, "value": 3},
            {"id": "B", "cost": 3, "value": 4},
            {"id": "C", "cost": 4, "value": 5},
        ],
    },
    "f34": {
        "inputs": financial_inputs(),
        "parameters": {"inventory_reduction_percent": 10, "marketing_increase_percent": 100, "revenue_lift_percent": 0},
    },
    "f35": {"values": [1, 2, 3, 4, 5]},
}


def test_contracts_declare_only_supported_scoped_operations():
    assert set(CONTRACTS) == {"f21", "f22", "f25", "f26", "f27", "f34", "f35"}
    for contract in CONTRACTS.values():
        assert contract["version"] == "0.1.0"
        assert "state" not in contract
        assert contract["limitations"]
        assert len(contract["operations"]) == 1
        operation = contract["operations"][0]
        assert operation["scope"]
        assert operation["input_schema"]["additionalProperties"] is False
        assert operation["output_schema"]["additionalProperties"] is False


@pytest.mark.parametrize("fabric_id", EXAMPLES)
def test_execute_serializes_and_does_not_mutate_input(fabric_id):
    payload = deepcopy(EXAMPLES[fabric_id])
    before = deepcopy(payload)
    first = run(fabric_id, payload)
    assert first == run(fabric_id, payload)
    assert payload == before
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    declared = CONTRACTS[fabric_id]["operations"][0]["output_schema"]["properties"]
    assert set(first) == set(declared)


def test_inventory_conservation_and_lost_demand():
    result = run("f21", EXAMPLES["f21"])
    assert [row["stock"] for row in result["steps"]] == [6, 0, 0]
    assert [row["served"] for row in result["steps"]] == [4, 9, 0]
    assert result["total_served"] == 13
    assert result["total_shortage"] == 5
    assert result["ending_stock"] == 0
    assert result["conservation_error"] == 0


def test_ranking_respects_constraint_and_cost_direction():
    result = run("f22", EXAMPLES["f22"])
    assert [(row["id"], row["score"]) for row in result["ranking"]] == [("A", 0.75), ("B", 0.25)]
    assert result["excluded"] == [{"id": "C", "violations": ["cost"]}]
    assert result["normalized_weights"] == {"quality": 0.75, "cost": 0.25}


def test_ranking_no_feasible_alternative_has_no_winner():
    payload = deepcopy(EXAMPLES["f22"])
    payload["criteria"][1]["maximum"] = 1
    result = run("f22", payload)
    assert result["ranking"] == []
    assert len(result["excluded"]) == 3


def test_ranking_equal_values_are_neutral_and_ties_stable():
    result = run(
        "f22",
        {
            "criteria": [{"id": "quality", "weight": 1, "direction": "maximize"}],
            "alternatives": [{"id": "B", "values": {"quality": 5}}, {"id": "A", "values": {"quality": 5}}],
        },
    )
    assert [(row["id"], row["score"]) for row in result["ranking"]] == [("A", 0.5), ("B", 0.5)]


def test_supplied_scm_counterfactual_propagates_and_keeps_noise():
    result = run("f25", EXAMPLES["f25"])
    assert result["baseline"] == {"x": 2, "y": 7}
    assert result["counterfactual"] == {"x": 5, "y": 16}
    assert result["difference"] == {"x": 3, "y": 9}
    assert result["causal_identification_performed"] is False
    payload = deepcopy(EXAMPLES["f25"])
    payload["variables"][1]["noise"] = 2
    payload["interventions"] = {"y": 99}
    result = run("f25", payload)
    assert result["baseline"]["y"] == 9
    assert result["counterfactual"] == {"x": 2, "y": 99}


def test_last_value_forecast_backtest_and_uncalibrated_bands():
    result = run("f26", EXAMPLES["f26"])
    assert [row["value"] for row in result["forecast"]] == [7, 7, 7]
    assert result["backtest"]["points"] == 3
    assert result["backtest"]["mae"] == 2
    assert result["backtest"]["mean_error"] == 2
    assert result["backtest"]["rmse"] == pytest.approx(math.sqrt(14 / 3))
    assert result["drift"]["mean_increment_shift"] == 1.5
    assert result["interval"]["calibrated"] is False
    radius_one = result["forecast"][0]["upper"] - 7
    assert result["forecast"][2]["upper"] - 7 == pytest.approx(radius_one * math.sqrt(3))


def test_constant_forecast_has_zero_historic_error_not_future_guarantee():
    result = run("f26", {"series": [4, 4], "horizon": 1})
    assert result["backtest"]["rmse"] == 0
    assert result["forecast"] == [{"step": 1, "value": 4, "lower": 4, "upper": 4}]
    assert result["interval"]["calibrated"] is False


def test_exact_knapsack_beats_greedy_value_and_respects_no_reuse():
    result = run("f27", EXAMPLES["f27"])
    assert result["selected"] == ["A", "B"]
    assert result["total_cost"] == 5
    assert result["total_value"] == 7
    result = run("f27", {"capacity": 4, "items": [{"id": "once", "cost": 2, "value": 3}]})
    assert result["total_value"] == 3
    assert result["total_cost"] == 2


def test_knapsack_matches_independent_exhaustive_search():
    generator = random.Random(612)
    for _ in range(24):
        items = [
            {"id": str(index), "cost": generator.randint(1, 9), "value": generator.randint(0, 99) / 10}
            for index in range(8)
        ]
        capacity = generator.randint(0, 22)
        result = run("f27", {"capacity": capacity, "items": items})
        feasible = []
        for bits in itertools.product([0, 1], repeat=len(items)):
            cost = sum(item["cost"] for item, bit in zip(items, bits) if bit)
            value = sum((Decimal(str(item["value"])) for item, bit in zip(items, bits) if bit), Decimal(0))
            if cost <= capacity:
                feasible.append((value, -cost))
        best = max(feasible)
        assert result["total_value"] == float(best[0])
        assert result["total_cost"] == -best[1]


def test_knapsack_comparison_preserves_tiny_positive_values():
    result = run(
        "f27",
        {
            "capacity": 2,
            "items": [{"id": "large", "cost": 1, "value": 1e12}, {"id": "tiny", "cost": 1, "value": 1e-300}],
        },
    )
    assert result["selected"] == ["large", "tiny"]
    assert result["total_cost"] == 2


def test_financials_reuse_existing_calculation_and_rank_actual_results():
    result = run("f34", EXAMPLES["f34"])
    assert result["baseline"]["total_expenses"] == 600
    assert result["baseline"]["monthly_profit"] == 400
    profits = {row["scenario_id"]: row["monthly_profit"] for row in result["scenarios"]}
    assert profits == {"S1": 420, "S2": 350, "S3": 370}
    assert result["ranking"] == ["S1", "BASELINE", "S3", "S2"]
    assert result["best_modelled_scenario"] == "S1"
    assert result["currency"] == "SGD"
    assert "recommendation" not in result


def test_financial_ranking_retains_unchanged_baseline():
    payload = deepcopy(EXAMPLES["f34"])
    payload["parameters"]["inventory_reduction_percent"] = 0
    result = run("f34", payload)
    assert result["best_modelled_scenario"] == "BASELINE"


def test_statistics_match_hand_calculated_sample_moments():
    result = run("f35", EXAMPLES["f35"])
    assert result["count"] == 5
    assert result["mean"] == 3
    assert result["median"] == 3
    assert result["minimum"] == 1
    assert result["maximum"] == 5
    assert result["sample_variance"] == 2.5
    assert result["sample_standard_deviation"] == pytest.approx(math.sqrt(2.5))
    assert result["standard_error"] == pytest.approx(math.sqrt(0.5))
    assert result["mean_interval"]["lower"] == pytest.approx(3 - 1.959963984540054 * math.sqrt(0.5))


@pytest.mark.parametrize("fabric_id", EXAMPLES)
def test_unknown_fields_are_rejected(fabric_id):
    payload = deepcopy(EXAMPLES[fabric_id])
    payload["command"] = "arbitrary execution is not an operation"
    with pytest.raises(ValueError):
        run(fabric_id, payload)


@pytest.mark.parametrize("invalid", [True, False, None, "2", float("nan"), float("inf"), -float("inf"), 1e13, 10**1000])
def test_invalid_numeric_inputs_are_rejected(invalid):
    with pytest.raises(ValueError):
        run("f35", {"values": [1, invalid]})


@pytest.mark.parametrize(
    "fabric_id,payload",
    [
        ("f21", {"initial_stock": 0, "arrivals": [1], "demands": [1, 2]}),
        ("f21", {"initial_stock": -1, "arrivals": [1], "demands": [1]}),
        ("f21", {"initial_stock": 0, "arrivals": [1] * 513, "demands": [1] * 513}),
        (
            "f22",
            {
                "criteria": [{"id": "x", "weight": 0, "direction": "maximize"}],
                "alternatives": [{"id": "a", "values": {"x": 1}}],
            },
        ),
        (
            "f22",
            {
                "criteria": [{"id": "x", "weight": 1, "direction": []}],
                "alternatives": [{"id": "a", "values": {"x": 1}}],
            },
        ),
        (
            "f25",
            {"variables": [{"name": "x", "parents": {"x": 1}, "intercept": 0, "noise": 0}], "interventions": {"x": 1}},
        ),
        (
            "f25",
            {"variables": [{"name": "x", "parents": {}, "intercept": 0, "noise": 0}], "interventions": {"missing": 1}},
        ),
        ("f25", {"variables": [{"name": "x", "parents": {}, "intercept": 0, "noise": 0}], "interventions": {}}),
        ("f26", {"series": [1], "horizon": 1}),
        ("f26", {"series": [1, 2], "horizon": True}),
        ("f26", {"series": [1, 2], "horizon": 366}),
        ("f26", {"series": [1] * 4097, "horizon": 1}),
        ("f27", {"capacity": 10001, "items": [{"id": "a", "cost": 1, "value": 1}]}),
        ("f27", {"capacity": 1, "items": [{"id": "a", "cost": 0, "value": 1}]}),
        ("f27", {"capacity": 1, "items": [{"id": "a", "cost": 1, "value": -1}]}),
        ("f35", {"values": [1]}),
    ],
)
def test_structural_and_resource_bounds(fabric_id, payload):
    with pytest.raises(ValueError):
        run(fabric_id, payload)


@pytest.mark.parametrize("field,value", [("revenue", True), ("revenue", 0), ("rent", 0.001)])
def test_financial_input_precision_and_positive_revenue(field, value):
    payload = deepcopy(EXAMPLES["f34"])
    payload["inputs"][field] = value
    with pytest.raises(ValueError):
        run("f34", payload)


def test_unknown_fabric_or_operation_is_rejected():
    with pytest.raises(ValueError):
        execute("f01", "inventory_simulate", {})
    with pytest.raises(ValueError):
        execute("f35", "arbitrary_python", {"expression": "print('not executed')"})
