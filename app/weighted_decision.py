"""Exact weighted sums from explicit caller-supplied criteria and option scores.

This calculator does not infer missing facts, run a model or certify a role.
The independent fixed-case role oracle remains in agent_cert_weighted.py.
"""

from __future__ import annotations

from decimal import Decimal, DecimalException
from fractions import Fraction
import hashlib
import json
import math
import re


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate weighted-decision field")
        result[key] = value
    return result


def _name(value):
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 100
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("Nonempty criterion and option identifiers required")
    return value


def _number(value, *, weight=False):
    if type(value) is int:
        if value.bit_length() > 128:
            raise ValueError("Weighted-decision number exceeds supported precision")
        result = Fraction(value)
    elif type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("Finite weighted-decision number required")
        # Reject excessive exponents before Fraction allocates huge integers.
        if len(value.as_tuple().digits) > 80 or abs(value.as_tuple().exponent) > 80:
            raise ValueError("Weighted-decision number exceeds supported precision")
        result = Fraction(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Finite weighted-decision number required")
        result = Fraction(str(value))
    elif type(value) is str and len(value) <= 80 and re.fullmatch(r"-?\d+(?:/\d+|\.\d+)?", value):
        try:
            result = Fraction(value)
        except (ValueError, ZeroDivisionError):
            raise ValueError("Valid exact weighted-decision number required") from None
    else:
        raise ValueError("Weighted-decision numbers must be explicit finite numeric values")
    if abs(result) > 10**12 or result.numerator.bit_length() > 256 or result.denominator.bit_length() > 256:
        raise ValueError("Weighted-decision number exceeds supported precision")
    if weight and result < 0:
        raise ValueError("Weights must be nonnegative")
    return result


def _wire(value):
    return value.numerator if value.denominator == 1 else str(value)


def solve_from_context(content: bytes) -> dict:
    """Evaluate a closed, bounded structured request; higher scores are preferred."""
    if type(content) is not bytes or len(content) > 80_000:
        raise ValueError("Bounded weighted-decision JSON required")
    try:
        data = json.loads(
            content,
            object_pairs_hook=_unique,
            parse_float=Decimal,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON number")),
        )
    except (ValueError, UnicodeError, RecursionError, DecimalException):
        raise ValueError("Invalid weighted-decision JSON") from None
    if type(data) is not dict or set(data) != {"criterion_weights", "option_criterion_scores"}:
        raise ValueError("Explicit criterion weights and option scores required")
    supplied_weights, options = data["criterion_weights"], data["option_criterion_scores"]
    if type(supplied_weights) is not dict or not 1 <= len(supplied_weights) <= 32:
        raise ValueError("At least one criterion is required")
    weights = {_name(key): _number(value, weight=True) for key, value in supplied_weights.items()}
    if not any(weights.values()):
        raise ValueError("At least one positive criterion weight required")
    if type(options) is not list or not 2 <= len(options) <= 128:
        raise ValueError("At least two explicitly scored options required")
    scores, terms = {}, {}
    fields = set(weights) | {"option"}
    if "option" in weights:
        raise ValueError("Criterion identifier option is reserved")
    for row in options:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("Every option must supply each criterion exactly once")
        name = _name(row["option"])
        if name in scores or name == "TIE":
            raise ValueError("Distinct, nonreserved option identifiers required")
        weighted = {key: weight * _number(row[key]) for key, weight in weights.items()}
        scores[name] = sum(weighted.values(), Fraction())
        terms[name] = {key: _wire(value) for key, value in weighted.items()}
    best = max(scores.values())
    winners = sorted(name for name, score in scores.items() if score == best)
    return {
        "schema_version": "orqevia.weighted-decision.v1",
        "method": "EXACT_RATIONAL_WEIGHTED_SUM_HIGHER_IS_PREFERRED",
        "input_sha256": hashlib.sha256(content).hexdigest(),
        "criterion_weights": {key: _wire(value) for key, value in weights.items()},
        "weighted_terms": terms,
        "scores": {key: _wire(value) for key, value in scores.items()},
        "winners": winners,
        "decision": winners[0] if len(winners) == 1 else "TIE",
        "missing_tie_breaker": len(winners) > 1,
    }
