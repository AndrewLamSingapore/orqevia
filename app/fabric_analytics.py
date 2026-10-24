"""Bounded, deterministic analytical operations for the fabric execution router.

These are calculations over caller-supplied data, not model certifications.
There is no network access, arbitrary expression execution or physical action.
The causal operation propagates a supplied linear structural model; it neither
discovers a causal graph nor estimates an intervention from observational data.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
import math
import re
import statistics


def _object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _array(items, minimum=0, maximum=4096):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


NUMBER = {"type": "number", "minimum": -1e12, "maximum": 1e12}
NONNEGATIVE = {"type": "number", "minimum": 0, "maximum": 1e12}
MONEY = {**NONNEGATIVE, "multipleOf": 0.01}
RESULT_NUMBER = {"type": "number"}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 64}
NUMBERS = _array(NUMBER, 2)
RESULT_MAP = {"type": "object", "additionalProperties": RESULT_NUMBER, "maxProperties": 64}
FINANCIAL_BASELINE = _object(
    {
        **{key: RESULT_NUMBER for key in ["revenue", "total_expenses", "monthly_profit", "net_margin_percent"]},
        "expense_lines": _object(
            {
                key: RESULT_NUMBER
                for key in ["rent", "salaries", "inventory", "utilities", "marketing", "other_expenses"]
            }
        ),
        "formulas": _object(
            {key: {"type": "string"} for key in ["total_expenses", "monthly_profit", "net_margin_percent"]}
        ),
    }
)
FINANCIAL_SCENARIO = _object(
    {
        "scenario_id": {"type": "string", "enum": ["S1", "S2", "S3"]},
        "name": {"type": "string"},
        **{
            key: RESULT_NUMBER
            for key in [
                "revenue",
                "total_expenses",
                "monthly_profit",
                "profit_change",
                "net_margin_percent",
                "annualized_profit_change",
            ]
        },
        "assumptions": _array({"type": "string"}, 1, 8),
        "risks": _array({"type": "string"}, 1, 8),
    }
)


def _contract(operation, scope, input_schema, output_schema, limitations):
    return {
        "version": "0.1.0",
        "operations": [
            {
                "operation": operation,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "scope": scope,
            }
        ],
        "limitations": limitations,
    }


CONTRACTS = {
    "f21": _contract(
        "inventory_simulate",
        "DETERMINISTIC_DISCRETE_INVENTORY_SIMULATION",
        _object(
            {
                "initial_stock": NONNEGATIVE,
                "arrivals": _array(NONNEGATIVE, 1, 512),
                "demands": _array(NONNEGATIVE, 1, 512),
            }
        ),
        _object(
            {
                "steps": _array(
                    _object(
                        {key: RESULT_NUMBER for key in ["step", "arrival", "demand", "served", "shortage", "stock"]}
                    ),
                    1,
                    512,
                ),
                "ending_stock": RESULT_NUMBER,
                "total_served": RESULT_NUMBER,
                "total_shortage": RESULT_NUMBER,
                "conservation_error": RESULT_NUMBER,
                "assumptions": _array({"type": "string"}, 1, 8),
            }
        ),
        ["No stochastic demand inference or physical inventory integration.", "At most 512 time steps."],
    ),
    "f22": _contract(
        "rank_alternatives",
        "SUPPLIED_CRITERIA_WEIGHTED_MINMAX_RANKING",
        _object(
            {
                "criteria": _array(
                    _object(
                        {
                            "id": IDENTIFIER,
                            "weight": NONNEGATIVE,
                            "direction": {"type": "string", "enum": ["maximize", "minimize"]},
                            "minimum": NUMBER,
                            "maximum": NUMBER,
                        },
                        ["id", "weight", "direction"],
                    ),
                    1,
                    32,
                ),
                "alternatives": _array(
                    _object(
                        {
                            "id": IDENTIFIER,
                            "values": {"type": "object", "additionalProperties": NUMBER, "maxProperties": 32},
                        }
                    ),
                    1,
                    64,
                ),
            }
        ),
        _object(
            {
                "ranking": _array(
                    _object({"id": IDENTIFIER, "score": RESULT_NUMBER, "normalized_values": RESULT_MAP}), 0, 64
                ),
                "excluded": _array(_object({"id": IDENTIFIER, "violations": _array(IDENTIFIER, 1, 32)}), 0, 64),
                "normalized_weights": RESULT_MAP,
                "method": {"type": "string"},
                "assumptions": _array({"type": "string"}, 1, 8),
            }
        ),
        [
            "Scores depend entirely on supplied weights, values and hard constraints.",
            "No probability or expected-utility estimate.",
        ],
    ),
    "f25": _contract(
        "linear_counterfactual",
        "SUPPLIED_LINEAR_SCM_FIXED_NOISE_INTERVENTION",
        _object(
            {
                "variables": _array(
                    _object(
                        {
                            "name": IDENTIFIER,
                            "intercept": NUMBER,
                            "parents": {"type": "object", "additionalProperties": NUMBER, "maxProperties": 31},
                            "noise": NUMBER,
                        }
                    ),
                    1,
                    32,
                ),
                "interventions": {
                    "type": "object",
                    "additionalProperties": NUMBER,
                    "minProperties": 1,
                    "maxProperties": 32,
                },
            }
        ),
        _object(
            {
                "baseline": RESULT_MAP,
                "counterfactual": RESULT_MAP,
                "difference": RESULT_MAP,
                "causal_identification_performed": {"type": "boolean", "const": False},
                "assumptions": _array({"type": "string"}, 1, 8),
            }
        ),
        [
            "Caller must supply a correctly ordered acyclic model and fixed exogenous noise.",
            "No observational causal identification, coefficient estimation or causal truth claim.",
        ],
    ),
    "f26": _contract(
        "naive_forecast",
        "LAST_VALUE_FORECAST_WITH_ROLLING_ONE_STEP_BACKTEST",
        _object({"series": NUMBERS, "horizon": {"type": "integer", "minimum": 1, "maximum": 365}}),
        _object(
            {
                "forecast": _array(
                    _object({key: RESULT_NUMBER for key in ["step", "value", "lower", "upper"]}), 1, 365
                ),
                "backtest": _object(
                    {
                        "points": {"type": "integer"},
                        "mae": RESULT_NUMBER,
                        "rmse": RESULT_NUMBER,
                        "mean_error": RESULT_NUMBER,
                    }
                ),
                "drift": _object({"mean_increment_shift": RESULT_NUMBER, "method": {"type": "string"}}),
                "interval": _object(
                    {
                        "nominal_probability": RESULT_NUMBER,
                        "method": {"type": "string"},
                        "calibrated": {"type": "boolean", "const": False},
                    }
                ),
                "assumptions": _array({"type": "string"}, 1, 8),
            }
        ),
        [
            "Baseline method only; no seasonality or learned model.",
            "Normal random-walk error bands are assumptions, not validated coverage guarantees.",
        ],
    ),
    "f27": _contract(
        "knapsack_allocate",
        "EXACT_BOUNDED_ZERO_ONE_INTEGER_COST_ALLOCATION",
        _object(
            {
                "capacity": {"type": "integer", "minimum": 0, "maximum": 10000},
                "items": _array(
                    _object(
                        {
                            "id": IDENTIFIER,
                            "cost": {"type": "integer", "minimum": 1, "maximum": 10000},
                            "value": NONNEGATIVE,
                        }
                    ),
                    1,
                    64,
                ),
            }
        ),
        _object(
            {
                "selected": _array(IDENTIFIER, 0, 64),
                "total_cost": {"type": "integer"},
                "total_value": RESULT_NUMBER,
                "unused_capacity": {"type": "integer"},
                "optimal_for_supplied_model": {"type": "boolean", "const": True},
                "method": {"type": "string"},
            }
        ),
        [
            "One non-negative integer cost constraint; indivisible items.",
            "At most 640,000 dynamic-programming updates.",
        ],
    ),
    "f34": _contract(
        "financial_scenarios",
        "DETERMINISTIC_HYPOTHETICAL_MONTHLY_BUSINESS_SCENARIOS",
        _object(
            {
                "inputs": _object(
                    {
                        key: (
                            {"type": "number", "exclusiveMinimum": 0, "maximum": 1e12, "multipleOf": 0.01}
                            if key == "revenue"
                            else MONEY
                        )
                        for key in [
                            "revenue",
                            "rent",
                            "salaries",
                            "inventory",
                            "utilities",
                            "marketing",
                            "other_expenses",
                        ]
                    }
                ),
                "parameters": _object(
                    {
                        "inventory_reduction_percent": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 50,
                            "multipleOf": 0.01,
                        },
                        "marketing_increase_percent": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 100,
                            "multipleOf": 0.01,
                        },
                        "revenue_lift_percent": {"type": "number", "minimum": 0, "maximum": 100, "multipleOf": 0.01},
                    }
                ),
                "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            },
            ["inputs", "parameters"],
        ),
        _object(
            {
                "currency": {"type": "string"},
                "period": {"type": "string"},
                "baseline": FINANCIAL_BASELINE,
                "scenarios": _array(FINANCIAL_SCENARIO, 3, 3),
                "ranking": _array({"type": "string"}, 4, 4),
                "best_modelled_scenario": {"type": "string"},
                "limitations": _array({"type": "string"}, 1, 8),
            }
        ),
        [
            "Reuses the existing project_workflows financial calculation.",
            "Hypothetical pre-tax inputs, no investment advice or verified future revenue.",
        ],
    ),
    "f35": _contract(
        "summarize_statistics",
        "BOUNDED_UNIVARIATE_DESCRIPTIVE_SAMPLE_STATISTICS",
        _object({"values": NUMBERS}),
        _object(
            {
                "count": {"type": "integer"},
                **{
                    key: RESULT_NUMBER
                    for key in [
                        "mean",
                        "median",
                        "minimum",
                        "maximum",
                        "sample_variance",
                        "sample_standard_deviation",
                        "standard_error",
                    ]
                },
                "mean_interval": _object(
                    {
                        "lower": RESULT_NUMBER,
                        "upper": RESULT_NUMBER,
                        "nominal_probability": RESULT_NUMBER,
                        "method": {"type": "string"},
                    }
                ),
                "assumptions": _array({"type": "string"}, 1, 8),
            }
        ),
        [
            "Two to 4096 supplied finite observations.",
            "Mean interval is a normal approximation; small samples or dependent data need separate validation.",
        ],
    ),
}


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("Object fields do not match the operation contract")


def _number(value, *, nonnegative=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or abs(value) > 1e12
        or not math.isfinite(value)
        or (nonnegative and value < 0)
    ):
        raise ValueError("A bounded finite number is required")
    return float(value)


def _integer(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError("Integer is outside the operation bounds")
    return value


def _list(value, lower=1, upper=4096):
    if not isinstance(value, list) or not lower <= len(value) <= upper:
        raise ValueError("List length is outside the operation bounds")
    return value


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or value.strip() != value:
        raise ValueError("A nonempty identifier of at most 64 characters is required")
    return value


def _inventory(payload):
    _keys(payload, ["initial_stock", "arrivals", "demands"])
    initial = stock = _number(payload["initial_stock"], nonnegative=True)
    arrivals = [_number(value, nonnegative=True) for value in _list(payload["arrivals"], upper=512)]
    demands = [_number(value, nonnegative=True) for value in _list(payload["demands"], upper=512)]
    if len(arrivals) != len(demands):
        raise ValueError("Arrivals and demands must have equal lengths")
    steps = []
    for step, (arrival, demand) in enumerate(zip(arrivals, demands), 1):
        stock += arrival
        served = min(stock, demand)
        stock -= served
        steps.append(
            {
                "step": step,
                "arrival": arrival,
                "demand": demand,
                "served": served,
                "shortage": demand - served,
                "stock": stock,
            }
        )
    total_served = math.fsum(row["served"] for row in steps)
    return {
        "steps": steps,
        "ending_stock": stock,
        "total_served": total_served,
        "total_shortage": math.fsum(row["shortage"] for row in steps),
        "conservation_error": initial + math.fsum(arrivals) - total_served - stock,
        "assumptions": [
            "Arrivals precede demand in each step.",
            "Unserved demand is lost; stock is not negative.",
            "Caller-supplied hypothetical inputs; no physical action.",
        ],
    }


def _rank(payload):
    _keys(payload, ["criteria", "alternatives"])
    criteria, alternatives, names = [], [], set()
    for row in _list(payload["criteria"], upper=32):
        _keys(row, ["id", "weight", "direction"], ["minimum", "maximum"])
        identifier = _name(row["id"])
        if (
            identifier in names
            or not isinstance(row["direction"], str)
            or row["direction"] not in {"maximize", "minimize"}
        ):
            raise ValueError("Criterion identifiers must be unique and directions valid")
        names.add(identifier)
        criterion = {**row, "weight": _number(row["weight"], nonnegative=True)}
        for key in ["minimum", "maximum"]:
            if key in row:
                criterion[key] = _number(row[key])
        if criterion.get("minimum", -1e12) > criterion.get("maximum", 1e12):
            raise ValueError("Criterion minimum exceeds maximum")
        criteria.append(criterion)
    weight_sum = math.fsum(row["weight"] for row in criteria)
    if weight_sum <= 0:
        raise ValueError("At least one criterion weight must be positive")
    weights = {row["id"]: row["weight"] / weight_sum for row in criteria}
    identifiers = set()
    excluded = []
    for row in _list(payload["alternatives"], upper=64):
        _keys(row, ["id", "values"])
        identifier = _name(row["id"])
        if identifier in identifiers or not isinstance(row["values"], dict) or set(row["values"]) != names:
            raise ValueError("Alternatives require unique identifiers and every criterion value")
        identifiers.add(identifier)
        values = {key: _number(value) for key, value in row["values"].items()}
        violations = [
            criterion["id"]
            for criterion in criteria
            if not criterion.get("minimum", -1e12) <= values[criterion["id"]] <= criterion.get("maximum", 1e12)
        ]
        if violations:
            excluded.append({"id": identifier, "violations": violations})
        else:
            alternatives.append({"id": identifier, "values": values})
    ranking = []
    for row in alternatives:
        normalized = {}
        for criterion in criteria:
            key = criterion["id"]
            lower = min(item["values"][key] for item in alternatives)
            upper = max(item["values"][key] for item in alternatives)
            value = 0.5 if upper == lower else (row["values"][key] - lower) / (upper - lower)
            normalized[key] = value if criterion["direction"] == "maximize" else 1 - value
        ranking.append(
            {
                "id": row["id"],
                "score": math.fsum(weights[key] * value for key, value in normalized.items()),
                "normalized_values": normalized,
            }
        )
    ranking.sort(key=lambda row: (-row["score"], row["id"]))
    return {
        "ranking": ranking,
        "excluded": excluded,
        "normalized_weights": weights,
        "method": "weighted min-max normalization among feasible alternatives",
        "assumptions": [
            "Supplied weights and hard constraints express the caller's preferences.",
            "Equal criterion values receive 0.5; ties break by identifier.",
            "Scores are comparative and change when the feasible alternative set changes.",
        ],
    }


def _counterfactual(payload):
    _keys(payload, ["variables", "interventions"])
    variables, names = [], set()
    for row in _list(payload["variables"], upper=32):
        _keys(row, ["name", "intercept", "parents", "noise"])
        name = _name(row["name"])
        parents = row["parents"]
        if name in names or not isinstance(parents, dict) or not set(parents) <= names:
            raise ValueError("Variables must be unique and topologically ordered without cycles")
        variables.append(
            {
                "name": name,
                "intercept": _number(row["intercept"]),
                "noise": _number(row["noise"]),
                "parents": {key: _number(value) for key, value in parents.items()},
            }
        )
        names.add(name)
    intervention = payload["interventions"]
    if not isinstance(intervention, dict) or not intervention or not set(intervention) <= names:
        raise ValueError("Interventions must name existing variables")
    intervention = {key: _number(value) for key, value in intervention.items()}

    def propagate(overrides):
        values = {}
        for row in variables:
            name = row["name"]
            value = (
                overrides[name]
                if name in overrides
                else math.fsum(
                    [
                        row["intercept"],
                        row["noise"],
                        *(coefficient * values[parent] for parent, coefficient in row["parents"].items()),
                    ]
                )
            )
            values[name] = _number(value)
        return values

    baseline, counterfactual = propagate({}), propagate(intervention)
    return {
        "baseline": baseline,
        "counterfactual": counterfactual,
        "difference": {key: counterfactual[key] - baseline[key] for key in baseline},
        "causal_identification_performed": False,
        "assumptions": [
            "Caller-supplied linear structural equations and ordering are correct.",
            "Exogenous noise remains fixed across the intervention.",
            "This propagates an assumed model and does not establish causal truth from data.",
        ],
    }


def _forecast(payload):
    _keys(payload, ["series", "horizon"])
    series = [_number(value) for value in _list(payload["series"], 2)]
    horizon = _integer(payload["horizon"], 1, 365)
    errors = [current - previous for previous, current in zip(series, series[1:])]
    rmse = math.sqrt(math.fsum(value * value for value in errors) / len(errors))
    forecast = []
    for step in range(1, horizon + 1):
        radius = 1.959963984540054 * rmse * math.sqrt(step)
        forecast.append({"step": step, "value": series[-1], "lower": series[-1] - radius, "upper": series[-1] + radius})
    split = len(errors) // 2
    shift = statistics.fmean(errors[split:]) - statistics.fmean(errors[:split]) if split else 0.0
    return {
        "forecast": forecast,
        "backtest": {
            "points": len(errors),
            "mae": statistics.fmean(abs(value) for value in errors),
            "rmse": rmse,
            "mean_error": statistics.fmean(errors),
        },
        "drift": {
            "mean_increment_shift": shift,
            "method": "second-half minus first-half mean increment; descriptive only",
        },
        "interval": {
            "nominal_probability": 0.95,
            "method": "last value +/- 1.959963984540054 * one-step RMSE * sqrt(horizon)",
            "calibrated": False,
        },
        "assumptions": [
            "Random-walk baseline with independent zero-mean normal increments for the interval approximation.",
            "Historic rolling one-step errors use only the preceding observed value.",
            "No seasonal, causal or trained forecasting model; error-band coverage is unverified.",
        ],
    }


def _allocate(payload):
    _keys(payload, ["capacity", "items"])
    capacity = _integer(payload["capacity"], 0, 10000)
    items, identifiers = [], set()
    for row in _list(payload["items"], upper=64):
        _keys(row, ["id", "cost", "value"])
        name = _name(row["id"])
        if name in identifiers:
            raise ValueError("Item identifiers must be unique")
        identifiers.add(name)
        items.append(
            {
                "id": name,
                "cost": _integer(row["cost"], 1, 10000),
                "value": Decimal(str(_number(row["value"], nonnegative=True))),
            }
        )
    states = [None] * (capacity + 1)
    states[0] = (Decimal(0), 0)
    # Admitted floats have at most 324 decimal places and a sum has at most
    # 14 integer digits. Preserve tiny value increments during comparisons.
    with localcontext() as context:
        context.prec = 400
        for index, item in enumerate(items):
            for cost in range(capacity, item["cost"] - 1, -1):
                previous = states[cost - item["cost"]]
                if previous is None:
                    continue
                candidate = (previous[0] + item["value"], previous[1] | (1 << index))
                current = states[cost]
                if (
                    current is None
                    or candidate[0] > current[0]
                    or (candidate[0] == current[0] and candidate[1] < current[1])
                ):
                    states[cost] = candidate
    total_cost = max(
        (cost for cost, value in enumerate(states) if value is not None),
        key=lambda cost: (states[cost][0], -cost, -states[cost][1]),
    )
    total_value, selected = states[total_cost]
    return {
        "selected": [item["id"] for index, item in enumerate(items) if selected & (1 << index)],
        "total_cost": total_cost,
        "total_value": float(total_value),
        "unused_capacity": capacity - total_cost,
        "optimal_for_supplied_model": True,
        "method": "exact 0/1 integer-cost dynamic programming; equal value favors lower cost then input mask",
    }


def _financial(payload):
    from .project_workflows import FinancialInputs, ScenarioParameters, calculate_financials

    _keys(payload, ["inputs", "parameters"], ["currency"])
    inputs = ["revenue", "rent", "salaries", "inventory", "utilities", "marketing", "other_expenses"]
    parameters = ["inventory_reduction_percent", "marketing_increase_percent", "revenue_lift_percent"]
    _keys(payload["inputs"], inputs)
    _keys(payload["parameters"], parameters)
    for value in [*payload["inputs"].values(), *payload["parameters"].values()]:
        _number(value, nonnegative=True)
    currency = payload.get("currency", "SGD")
    if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("Currency must be a three-letter uppercase label")
    data = calculate_financials(
        FinancialInputs.model_validate(payload["inputs"]),
        ScenarioParameters.model_validate(payload["parameters"]),
        currency=currency,
    )
    ranked = [
        ("BASELINE", data["baseline"]["monthly_profit"]),
        *((row["scenario_id"], row["monthly_profit"]) for row in data["scenarios"]),
    ]
    ranked.sort(key=lambda row: (-row[1], row[0]))
    return {
        "currency": data["currency"],
        "period": data["period"],
        "baseline": data["baseline"],
        "scenarios": data["scenarios"],
        "ranking": [row[0] for row in ranked],
        "best_modelled_scenario": ranked[0][0],
        "limitations": [
            "Hypothetical pre-tax monthly inputs; actual future demand is not established.",
            "Scenarios omit one-off implementation costs, financing and tax.",
            "Ranking includes the unchanged baseline; no investment or execution recommendation.",
        ],
    }


def _statistics(payload):
    _keys(payload, ["values"])
    values = [_number(value) for value in _list(payload["values"], 2)]
    mean = statistics.fmean(values)
    variance = statistics.variance(values)
    deviation = math.sqrt(variance)
    error = deviation / math.sqrt(len(values))
    radius = 1.959963984540054 * error
    return {
        "count": len(values),
        "mean": mean,
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "sample_variance": variance,
        "sample_standard_deviation": deviation,
        "standard_error": error,
        "mean_interval": {
            "lower": mean - radius,
            "upper": mean + radius,
            "nominal_probability": 0.95,
            "method": "normal approximation using sample standard error; no small-sample coverage guarantee",
        },
        "assumptions": [
            "Observations are caller-supplied; measurement provenance is not established here.",
            "Normal-approximation interval assumes independent representative observations and adequate sample size.",
            "Variance uses the n-1 sample denominator.",
        ],
    }


_EXECUTORS = {
    "f21": _inventory,
    "f22": _rank,
    "f25": _counterfactual,
    "f26": _forecast,
    "f27": _allocate,
    "f34": _financial,
    "f35": _statistics,
}


def execute(fabric_id: str, operation: str, payload: dict) -> dict:
    """Execute exactly one declared operation; no retries or hidden side effects."""
    contract = CONTRACTS.get(fabric_id)
    if contract is None or operation != contract["operations"][0]["operation"]:
        raise ValueError("Unsupported analytical fabric operation")
    result = _EXECUTORS[fabric_id](deepcopy(payload))

    # A last serialization-equivalent check prevents non-finite derived output.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Calculation produced a non-finite result")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)

    finite(result)
    return result
