"""Bounded seeded Monte Carlo as a cross-check for discrete decisions."""

from decimal import Decimal
from math import isfinite, sqrt
import random

from .core import DecisionProblem, _validated_problem


def simulate_decision(problem: DecisionProblem, *, samples: int = 10_000, seed: int = 0) -> dict[str, object]:
    if isinstance(samples, bool) or not isinstance(samples, int) or not 100 <= samples <= 1_000_000:
        raise ValueError("samples must be an integer in [100, 1000000]")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    probabilities, utilities, _, _ = _validated_problem(problem)
    states = list(probabilities)
    weights = [float(probabilities[state]) for state in states]
    if not all(isfinite(weight) for weight in weights):
        raise ValueError("simulation probabilities exceed finite floating-point range")
    rng = random.Random(seed)
    chosen = rng.choices(states, weights=weights, k=samples)
    results: dict[str, dict[str, float]] = {}
    for action, payoff in utilities.items():
        try:
            values = [float(payoff[state]) for state in chosen]
        except (OverflowError, ValueError) as exc:
            raise ValueError("simulation utility exceeds finite floating-point range") from exc
        if not all(isfinite(value) for value in values):
            raise ValueError("simulation utility exceeds finite floating-point range")
        average = sum(values) / samples
        variance = sum((value - average) ** 2 for value in values) / (samples - 1)
        if not isfinite(variance):
            raise ValueError("simulation variance exceeds finite floating-point range")
        standard_error = sqrt(variance / samples)
        results[action] = {
            "mean": average,
            "standard_error": standard_error,
            "ci95_lower": average - 1.96 * standard_error,
            "ci95_upper": average + 1.96 * standard_error,
        }
    return {"status": "SIMULATED", "seed": seed, "samples": samples, "actions": results}


def verify_analytic_with_simulation(problem: DecisionProblem, *, samples: int = 10_000, seed: int = 0) -> dict[str, object]:
    """Preserve disagreement; never average contradictory answers."""
    probabilities, utilities, _, _ = _validated_problem(problem)
    simulated = simulate_decision(problem, samples=samples, seed=seed)
    comparisons = {}
    for action, payoff in utilities.items():
        exact = float(sum(probabilities[state] * payoff[state] for state in probabilities))
        row = simulated["actions"][action]
        tolerance = max(4 * row["standard_error"], 1e-9 * max(abs(exact), 1))
        difference = abs(exact - row["mean"])
        comparisons[action] = {
            "analytic": exact,
            "simulated": row["mean"],
            "difference": difference,
            "tolerance": tolerance,
            "status": "AGREE" if difference <= tolerance else "DISAGREE",
        }
    return {
        "status": "AGREE" if all(row["status"] == "AGREE" for row in comparisons.values()) else "DISAGREE",
        "comparisons": comparisons,
        "simulation": simulated,
    }
