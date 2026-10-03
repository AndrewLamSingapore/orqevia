"""A deliberately bounded, reproducible discrete decision core.

All probabilities and utilities must be supplied by evidence or explicitly
labelled assumptions. This module never treats generated prose as authority and
never executes a recommended action.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from typing import Mapping


class InsufficientEvidence(ValueError):
    """A numerical answer is not defensible with the supplied inputs."""


class EvidenceKind(str, Enum):
    OBSERVED = "OBSERVED"
    ASSUMED = "ASSUMED"
    ESTIMATED = "ESTIMATED"
    MODEL_CONTENT = "MODEL_CONTENT"


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


@dataclass(frozen=True)
class Evidence:
    source: str
    retrieved_at: datetime
    kind: EvidenceKind
    digest: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("evidence source is required")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("evidence time must include a timezone")
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("evidence kind must be a validated EvidenceKind")
        if self.kind is EvidenceKind.MODEL_CONTENT:
            raise InsufficientEvidence("model-generated text is not authoritative evidence")


@dataclass(frozen=True)
class DecisionProblem:
    question: str
    probabilities: Mapping[str, object]
    utilities: Mapping[str, Mapping[str, object]]
    evidence: tuple[Evidence, ...]
    loss_threshold: object = 0
    risk_aversion: object = 0
    allowed_actions: tuple[str, ...] | None = None


def _validated_problem(problem: DecisionProblem) -> tuple[dict[str, Decimal], dict[str, dict[str, Decimal]], Decimal, Decimal]:
    if not problem.question.strip():
        raise ValueError("question is required")
    if not problem.evidence:
        raise InsufficientEvidence("INSUFFICIENT_EVIDENCE: no provenance for probabilities")
    if not problem.probabilities:
        raise InsufficientEvidence("INSUFFICIENT_EVIDENCE: no state probabilities")
    probabilities = {state: _decimal(value, f"probability {state}") for state, value in problem.probabilities.items()}
    if any(not isinstance(state, str) or not state or value < 0 or value > 1 for state, value in probabilities.items()):
        raise ValueError("state names must be nonempty and probabilities within [0, 1]")
    if sum(probabilities.values()) != Decimal(1):
        raise ValueError("state probabilities must sum exactly to 1")
    if not problem.utilities:
        raise InsufficientEvidence("INSUFFICIENT_EVIDENCE: no candidate actions or utilities")
    allowed = set(problem.allowed_actions) if problem.allowed_actions is not None else set(problem.utilities)
    if not allowed:
        raise ValueError("no constraint-compliant action")
    if not allowed <= set(problem.utilities):
        raise ValueError("allowed_actions contains an unknown action")
    utilities: dict[str, dict[str, Decimal]] = {}
    for action in sorted(allowed):
        payoff = problem.utilities[action]
        if set(payoff) != set(probabilities):
            raise ValueError(f"utility states for {action} do not match probability states")
        utilities[action] = {state: _decimal(value, f"utility {action}/{state}") for state, value in payoff.items()}
    threshold = _decimal(problem.loss_threshold, "loss_threshold")
    aversion = _decimal(problem.risk_aversion, "risk_aversion")
    if aversion < 0:
        raise ValueError("risk_aversion must be nonnegative")
    return probabilities, utilities, threshold, aversion


def _tail_loss(probabilities: Mapping[str, Decimal], payoff: Mapping[str, Decimal], confidence: Decimal) -> tuple[Decimal, Decimal]:
    """Discrete loss VaR and CVaR with exact fractional mass at the quantile."""
    tail = Decimal(1) - confidence
    losses = sorted(((-payoff[state], probability) for state, probability in probabilities.items()), reverse=True)
    remaining = tail
    weighted = Decimal(0)
    var = losses[0][0]
    for loss, probability in losses:
        taken = min(remaining, probability)
        if taken:
            weighted += loss * taken
            var = loss
            remaining -= taken
        if remaining == 0:
            break
    return var, weighted / tail


def evaluate_decision(problem: DecisionProblem, *, confidence: object = "0.95") -> dict[str, object]:
    """Evaluate actions; return data and a reproducibility receipt, not authority."""
    probabilities, utilities, threshold, aversion = _validated_problem(problem)
    level = _decimal(confidence, "confidence")
    if not 0 < level < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    actions: dict[str, dict[str, str]] = {}
    for action, payoff in utilities.items():
        expected = sum(probabilities[state] * payoff[state] for state in probabilities)
        variance = sum(probabilities[state] * (payoff[state] - expected) ** 2 for state in probabilities)
        downside = sum(probabilities[state] for state in probabilities if payoff[state] < threshold)
        var, cvar = _tail_loss(probabilities, payoff, level)
        actions[action] = {
            "expected_utility": str(expected),
            "variance": str(variance),
            "standard_deviation": str(variance.sqrt()),
            "downside_probability": str(downside),
            "loss_var": str(var),
            "loss_cvar": str(cvar),
            "risk_adjusted_utility": str(expected - aversion * variance),
        }
    best = max(actions, key=lambda action: (Decimal(actions[action]["risk_adjusted_utility"]), action))
    most_likely_state = max(probabilities, key=lambda state: (probabilities[state], state))
    clairvoyant = sum(probabilities[state] * max(utilities[action][state] for action in utilities) for state in probabilities)
    baseline = max(Decimal(row["expected_utility"]) for row in actions.values())
    inputs = {
        "question": problem.question,
        "probabilities": {key: str(value) for key, value in sorted(probabilities.items())},
        "utilities": {action: {state: str(value) for state, value in sorted(payoff.items())} for action, payoff in sorted(utilities.items())},
        "loss_threshold": str(threshold),
        "risk_aversion": str(aversion),
        "evidence": [
            {"source": item.source, "retrieved_at": item.retrieved_at.astimezone(timezone.utc).isoformat(), "kind": item.kind.value, "digest": item.digest, "version": item.version}
            for item in problem.evidence
        ],
    }
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "status": "CALCULATED_ASSUMPTION_DEPENDENT" if any(item.kind is EvidenceKind.ASSUMED for item in problem.evidence) else "CALCULATED",
        "recommended_action": best,
        "most_likely_state": most_likely_state,
        "actions": actions,
        "expected_value_of_perfect_information": str(clairvoyant - baseline),
        "receipt": {"engine": "pde.discrete.v1", "input_sha256": fingerprint, "inputs": inputs, "confidence": str(level)},
        "authority": "RECOMMEND_ONLY",
    }


def update_binary_belief(prior: object, likelihood_if_true: object, likelihood_if_false: object) -> Decimal:
    """Bayes update for an observed event with explicitly supplied likelihoods."""
    p = _decimal(prior, "prior")
    true_likelihood = _decimal(likelihood_if_true, "likelihood_if_true")
    false_likelihood = _decimal(likelihood_if_false, "likelihood_if_false")
    if any(value < 0 or value > 1 for value in (p, true_likelihood, false_likelihood)):
        raise ValueError("prior and likelihoods must be within [0, 1]")
    denominator = p * true_likelihood + (1 - p) * false_likelihood
    if denominator == 0:
        raise InsufficientEvidence("observed event has zero probability under the supplied model")
    return p * true_likelihood / denominator
