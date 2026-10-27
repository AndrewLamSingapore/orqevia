"""Original Academy lessons and independent, seeded probability assessments.

The existing PIF supplies Markov/HMM mathematics. All inputs here are labelled
educational fixtures; this module neither qualifies production forecasts nor
grants tool permissions. References are links, not redistributed source text.
"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
import re

from .agent_registry import agent_record, registered_agent_ids
from .pif.core import MarkovModel, absorbing_analysis, hidden_filter, stationary_distribution

PROGRAM_ID = "probability-foundations"
VERSION = "probability-foundations.v1"
REFERENCES = (
    "https://www.wzchen.com/probability-cheatsheet",
    "https://www.wzchen.com/s/probability_cheatsheet.pdf",
    "https://stat110.hsites.harvard.edu/",
    "https://www.statslab.cam.ac.uk/~rrw1/markov/M.pdf",
    "https://scikit-learn.org/stable/modules/calibration.html",
)
LESSONS = (
    (
        "counting",
        "Counting and combinatorics",
        "An unordered selection without replacement has n!/(k!(n-k)!) possibilities. Establish whether order and replacement matter before counting.",
    ),
    (
        "axioms",
        "Sample spaces and probability axioms",
        "Probabilities are nonnegative and total one over the sample space. For overlapping events, add their probabilities and subtract their intersection once.",
    ),
    (
        "conditional",
        "Conditional probability",
        "Conditioning changes the denominator to the conditioning event. Divide the intersection count by that event count, which must be positive.",
    ),
    (
        "independence",
        "Independence and dependence",
        "Compare the joint probability with the product of the marginals. Equality establishes independence for the stated events; disjointness alone does not.",
    ),
    (
        "bayes",
        "Bayesian updating",
        "Multiply the prior by the observation likelihood, then divide by the sum of prior-times-likelihood over every competing state. Include false positives.",
    ),
    (
        "joint",
        "Joint, marginal and conditional distributions",
        "Sum the joint table over the unused variable for a marginal. Divide the selected cell by the corresponding row or column total for a conditional.",
    ),
    (
        "random_variables",
        "Random variables and probability mass functions",
        "A random variable maps outcomes to numbers. Sum the masses of exactly those values satisfying the requested event; check that all masses total one.",
    ),
    (
        "moments",
        "Expectation, variance and uncertainty",
        "Compute E[X] as sum(x*p(x)); variance is E[X^2]-E[X]^2. These calculations do not establish empirical calibration or a causal explanation.",
    ),
    (
        "markov",
        "Markov transitions",
        "For a row-vector distribution, multiply by the transition matrix once per transition. A two-step probability sums products through every intermediate state.",
    ),
    (
        "long_run",
        "Absorbing states and stationary distributions",
        "For absorption solve t=1+Qt, with zero time in absorbing states. A stationary distribution satisfies pi*P=pi and sums to one; stationarity alone does not imply convergence.",
    ),
    (
        "hidden_state",
        "Offline hidden-state inference",
        "For the first observation, multiply each initial state mass by its emission likelihood and normalize. This is offline educational filtering, not validated operational state inference.",
    ),
    (
        "scoring",
        "Calibration, Brier score and log loss",
        "Binary Brier loss is (p-y)^2. Binary log loss uses the natural logarithm: -log(p) for y=1 and -log(1-p) for y=0. A single score does not establish calibration.",
    ),
    (
        "decision",
        "Decisions under uncertainty",
        "Multiply each utility by the stated state probability and sum. Select the greater expected utility, explicitly preserving a tie. Utility estimates do not create execution permission.",
    ),
    (
        "provenance",
        "Assumptions and evidence provenance",
        "Keep fixture calculations, historical observations and current production evidence distinct. An unvalidated forecast proves neither production accuracy nor authorization to act.",
    ),
)


def catalog():
    return {
        "program_id": PROGRAM_ID,
        "version": VERSION,
        "evidence_kind": "fixture",
        "references": list(REFERENCES),
        "certification_awarded": False,
        "production_prediction_authority": False,
        "lessons": [{"topic_id": k, "title": t, "method": m} for k, t, m in LESSONS],
    }


def learning_path(agent):
    record = agent_record(agent)
    return {
        "agent_id": agent,
        "role": record["name"],
        "program_id": PROGRAM_ID,
        "version": VERSION,
        "topic_ids": [k for k, _, _ in LESSONS],
        "room_id": "autonomy-safety",
        "training_separate_from_assessment": True,
        "assessment_scope": "PROBABILITY_FOUNDATIONS_ONLY",
        "certification_awarded": False,
    }


def _fraction(value):
    return str(Fraction(value).limit_denominator(1000000))


def _model(matrix, absorbing=()):
    matrix = tuple(tuple(float(v) for v in row) for row in matrix)
    evidence = hashlib.sha256(json.dumps(matrix).encode()).hexdigest()
    states = ("first", "second")
    return MarkovModel(
        states,
        matrix,
        ((0, 0), (0, 0)),
        tuple(absorbing),
        0,
        None,
        None,
        evidence,
        ("fixture",),
        0,
        tuple((a, b) for a in states for b in states),
    )


def exercise(agent, seed, phase):
    """Return question data and an oracle separately; never send the oracle."""
    if agent not in registered_agent_ids(include_orchestrator=False):
        raise ValueError("registered specialist required")
    if type(seed) is not int or not 1 <= seed <= 100000:
        raise ValueError("valid exercise seed required")
    if phase not in {"baseline", "practice", "acceptance"}:
        raise ValueError("unknown learning phase")
    variant = {"baseline": 0, "practice": 1, "acceptance": 2}[phase]
    n = 5 + (seed % 4) + variant
    a = 2 + (seed + variant) % 3
    facts, answers = {}, {}
    facts["counting"] = {"n": n, "k": 2, "order_matters": False, "replacement": False}
    answers["counting"] = math.comb(n, 2)
    facts["axioms"] = {"p_a": f"{a}/10", "p_b": "4/10", "p_a_and_b": "1/10", "ask": "P(A union B)"}
    answers["axioms"] = _fraction(Fraction(a + 3, 10))
    facts["conditional"] = {"both_count": a, "conditioning_event_count": a + 5, "ask": "P(A given B)"}
    answers["conditional"] = _fraction(Fraction(a, a + 5))
    px, py = Fraction(1, 2 + variant), Fraction(1, 3 + variant)
    joint = px * py * (1 if (seed + variant) % 2 else 2)
    facts["independence"] = {"p_a": str(px), "p_b": str(py), "p_a_and_b": str(joint)}
    answers["independence"] = joint == px * py
    prior, sensitivity, false_positive = Fraction(a, 10), Fraction(4 + variant, 8), Fraction(1, 8)
    facts["bayes"] = {
        "prior_first": str(prior),
        "p_signal_given_first": str(sensitivity),
        "p_signal_given_other": str(false_positive),
        "ask": "P(first given signal)",
    }
    answers["bayes"] = _fraction(prior * sensitivity / (prior * sensitivity + (1 - prior) * false_positive))
    counts = [[1 + variant, 2 + variant], [3 + variant, 4 + variant]]
    facts["joint"] = {"counts_rows_x_columns_y": counts, "ask": ["P(X=1)", "P(Y=1 given X=1)"]}
    answers["joint"] = [
        _fraction(Fraction(sum(counts[1]), sum(map(sum, counts)))),
        _fraction(Fraction(counts[1][1], sum(counts[1]))),
    ]
    masses = [1 + a, 2 + a, 1]
    facts["random_variables"] = {"values": [0, 1, 2], "mass_counts": masses, "ask": "P(X>=1)"}
    answers["random_variables"] = _fraction(Fraction(sum(masses[1:]), sum(masses)))
    upper = 2 * (1 + seed % 2 + variant)
    facts["moments"] = {"values": [0, upper], "probabilities": ["1/2", "1/2"], "ask": ["E[X]", "Var(X)"]}
    answers["moments"] = [_fraction(Fraction(upper, 2)), _fraction(Fraction(upper * upper, 4))]
    p, q = Fraction(1 + variant, 8), Fraction(1 + seed % 2, 3)
    matrix = [[1 - p, p], [q, 1 - q]]
    markov = _model(matrix)
    facts["markov"] = {
        "transition_matrix": [[str(v) for v in row] for row in matrix],
        "state_order": ["first", "second"],
        "initial_state": "first",
        "transition_count": 2,
        "ask": "P(second after two transitions)",
    }
    answers["markov"] = _fraction(markov.forecast("first", 2)["second"])
    absorption = _model([[1 - Fraction(1, 2 + variant), Fraction(1, 2 + variant)], [0, 1]], ("second",))
    facts["long_run"] = {
        "absorption_transition": [[str(Fraction(v).limit_denominator()) for v in row] for row in absorption.matrix],
        "stationary_transition": facts["markov"]["transition_matrix"],
        "ask": ["expected transitions to absorption from first", "stationary probability of second"],
    }
    steps = absorbing_analysis(absorption)["states"]["first"]["expected_state_changes_to_absorption"]
    stationary = stationary_distribution(markov)["probabilities"]["second"]
    answers["long_run"] = [_fraction(steps), _fraction(stationary)]
    emission = Fraction(2 + variant, 3 + variant)
    facts["hidden_state"] = {
        "initial": ["1/2", "1/2"],
        "p_signal_given_state": [str(emission), str(1 - emission)],
        "observation": "signal",
        "ask": "posterior P(first)",
        "scope": "OFFLINE_EDUCATION",
    }
    filtered = hidden_filter(
        states=["first", "second"],
        transitions=[[1, 0], [0, 1]],
        initial=[0.5, 0.5],
        emissions={"signal": [float(emission), float(1 - emission)], "other": [float(1 - emission), float(emission)]},
        observations=["signal"],
    )
    answers["hidden_state"] = _fraction(filtered["posterior"]["first"])
    predicted, actual = Fraction(3 + variant, 6), seed % 2
    facts["scoring"] = {
        "probability": str(predicted),
        "outcome": actual,
        "independent_representative_validation": False,
        "ask": ["binary Brier loss", "natural-log loss", "calibration established?"],
    }
    answers["scoring"] = {
        "brier": _fraction((predicted - actual) ** 2),
        "log_loss": -math.log(float(predicted if actual else 1 - predicted)),
        "calibration_established": False,
    }
    good, fixed = 4 + seed % 7 + variant, 3
    facts["decision"] = {
        "state_probabilities": ["1/2", "1/2"],
        "A_utilities": [good, -2],
        "B_utilities": [fixed, fixed],
        "ask": "A, B, or TIE for greatest expected utility",
    }
    value = Fraction(good - 2, 2)
    answers["decision"] = "A" if value > fixed else ("B" if value < fixed else "TIE")
    facts["provenance"] = {
        "evidence_kind": "fixture",
        "observations": n,
        "production_validation": False,
        "action_permission": False,
        "ask": ["production accuracy proven?", "execution authorized?"],
    }
    answers["provenance"] = {"production_accuracy_proven": False, "execution_authorized": False}
    return facts, answers


def _schema(value):
    if type(value) is dict:
        return {
            "type": "object",
            "properties": {key: _schema(item) for key, item in value.items()},
            "required": list(value),
            "additionalProperties": False,
        }
    if type(value) is list:
        # These answers have homogeneous fraction-string entries.
        return {"type": "array", "items": {"type": "string"}, "minItems": len(value), "maxItems": len(value)}
    return {"type": {bool: "boolean", int: "integer", float: "number", str: "string"}[type(value)]}


def assessment_request(agent, seed, phase):
    facts, answers = exercise(agent, seed, phase)
    context = {
        "evidence_kind": "fixture",
        "program": VERSION,
        "phase": phase,
        "role": agent_record(agent)["name"],
        "questions": facts,
        "answer_format": "Return one JSON object with the fourteen topic IDs as keys. Fractions are strings such as 2/3 or 1. Keep exact integers and booleans. Use the listed order for answer arrays. Log loss is numeric within 0.000001.",
    }
    if phase != "baseline":
        context["lesson_methods"] = {key: method for key, _, method in LESSONS}
    return {
        "objective": "Solve each stated educational probability question independently; make no operational or certification claim.",
        "context": json.dumps(context, separators=(",", ":")),
        "response_schema": _schema(answers),
        "response_format": "strict_json",
    }


def _equal(answer, expected):
    if type(expected) is dict:
        return (
            type(answer) is dict
            and answer.keys() == expected.keys()
            and all(_equal(answer[k], v) for k, v in expected.items())
        )
    if type(expected) is list:
        return (
            type(answer) is list
            and len(answer) == len(expected)
            and all(_equal(a, b) for a, b in zip(answer, expected))
        )
    if type(expected) is bool or type(expected) is int:
        return type(answer) is type(expected) and answer == expected
    if type(expected) is float:
        return (
            type(answer) in (int, float)
            and math.isfinite(answer)
            and math.isclose(answer, expected, rel_tol=0, abs_tol=1e-6)
        )
    if type(answer) is not str:
        return False
    if re.fullmatch(r"-?\d+(?:/[1-9]\d*)?", expected):
        return bool(re.fullmatch(r"-?\d+(?:/[1-9]\d*)?", answer)) and Fraction(answer) == Fraction(expected)
    return answer == expected


def review_assessment(agent, seed, phase, response):
    if isinstance(response, dict):
        response = response.get("text")
    if not isinstance(response, str) or len(response.encode("utf-8")) > 16000:
        return False, ["invalid_response"]

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(
            response, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite"))
        )
        _, expected = exercise(agent, seed, phase)
        if type(value) is not dict or value.keys() != expected.keys():
            return False, ["field_contract_mismatch"]
        errors = [key for key, answer in expected.items() if not _equal(value[key], answer)]
        return not errors, errors
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        return False, ["invalid_response"]
