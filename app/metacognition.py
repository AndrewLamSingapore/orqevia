"""Deterministic, authority-neutral metacognitive control primitives.

This module governs *claims about reasoning*.  It deliberately does not expose
an executor: conclusions, retrieved text, memory and model output cannot grant
authority or trigger consequential tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Iterable


class EpistemicState(str, Enum):
    VERIFIED_FACT = "VERIFIED_FACT"
    SUPPORTED_FACT = "SUPPORTED_FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    CONTRADICTED = "CONTRADICTED"
    SUPERSEDED = "SUPERSEDED"


SOURCE_WEIGHT = {
    "direct_observation": 1.0,
    "deterministic_tool": .98,
    "primary_record": .92,
    "independent_reproduction": .9,
    "secondary_summary": .65,
    "model_inference": .35,
    "unsupported_assertion": 0.0,
}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    proposition: str
    supports: bool
    source_kind: str
    observed_at: int
    independently_verified: bool = False
    authoritative: bool = False

    @property
    def quality(self) -> float:
        base = SOURCE_WEIGHT.get(self.source_kind, 0.0)
        return min(1.0, base + (.02 if self.independently_verified else 0.0))


@dataclass
class Belief:
    proposition: str
    state: EpistemicState = EpistemicState.UNKNOWN
    confidence: float = 0.0
    evidence_ids: tuple[str, ...] = ()
    counterevidence_ids: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    grants_authority: bool = False
    may_trigger_consequential_tool: bool = False


@dataclass(frozen=True)
class Strategy:
    name: str
    requires: frozenset[str]
    expected_information_gain: float
    cost: float
    available: bool = True


@dataclass
class ControlState:
    objective: str
    beliefs: list[Belief] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    failed_strategies: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    iterations: int = 0
    disposition: str = "IN_PROGRESS"


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    proposition: str
    prior: float
    evidence_ids: tuple[str, ...] = ()
    counterevidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HypothesisAssessment:
    hypothesis_id: str
    score: float
    status: str
    discriminating_evidence_required: bool


def decompose_uncertainty(*, missing_information=False, conflicting_evidence=False,
                          model_disagreement=False, source_unreliable=False,
                          tool_unavailable=False, temporal_ambiguity=False,
                          causal_ambiguity=False) -> tuple[str, ...]:
    dimensions = {
        "missing_information": missing_information,
        "conflicting_evidence": conflicting_evidence,
        "model_disagreement": model_disagreement,
        "source_unreliable": source_unreliable,
        "tool_unavailable": tool_unavailable,
        "temporal_ambiguity": temporal_ambiguity,
        "causal_ambiguity": causal_ambiguity,
    }
    return tuple(name for name, present in dimensions.items() if present)


def compete_hypotheses(hypotheses: Iterable[Hypothesis], evidence: Iterable[Evidence]) -> tuple[HypothesisAssessment, ...]:
    """Score alternatives without converting the highest score into truth."""
    evidence_by_id = {e.evidence_id: e for e in evidence}
    output = []
    for hypothesis in hypotheses:
        if not math.isfinite(hypothesis.prior) or not 0 <= hypothesis.prior <= 1:
            raise ValueError("hypothesis prior must be finite and within [0,1]")
        support = sum(evidence_by_id[x].quality for x in hypothesis.evidence_ids if x in evidence_by_id)
        oppose = sum(evidence_by_id[x].quality for x in hypothesis.counterevidence_ids if x in evidence_by_id)
        score = max(0.0, min(1.0, hypothesis.prior + .2 * support - .25 * oppose))
        contradictory = bool(support and oppose)
        status = "CONTRADICTED" if contradictory else "SUPPORTED" if support else "HYPOTHESIS"
        output.append(HypothesisAssessment(hypothesis.hypothesis_id, round(score, 4), status,
                                           contradictory or not support))
    return tuple(sorted(output, key=lambda item: (-item.score, item.hypothesis_id)))


def assess(proposition: str, evidence: Iterable[Evidence]) -> Belief:
    """Assess one proposition while preserving contradiction and provenance."""
    relevant = [e for e in evidence if e.proposition == proposition]
    positive = [e for e in relevant if e.supports]
    negative = [e for e in relevant if not e.supports]
    pos = max((e.quality for e in positive), default=0.0)
    neg = max((e.quality for e in negative), default=0.0)
    if positive and negative:
        state = EpistemicState.CONTRADICTED
        confidence = max(pos, neg) * .5
        unknowns = ("contradiction_requires_discriminating_evidence",)
    elif any(e.authoritative and e.independently_verified and e.quality >= .9 for e in positive):
        state, confidence, unknowns = EpistemicState.VERIFIED_FACT, pos, ()
    elif pos >= .65:
        state, confidence, unknowns = EpistemicState.SUPPORTED_FACT, pos * .85, ()
    elif pos > 0:
        state, confidence = EpistemicState.INFERENCE, pos * .7
        unknowns = ("independent_primary_evidence_missing",)
    elif neg > 0:
        state, confidence = EpistemicState.CONTRADICTED, neg
        unknowns = ()
    else:
        state, confidence = EpistemicState.UNKNOWN, 0.0
        unknowns = ("no_attributable_evidence",)
    return Belief(proposition, state, round(confidence, 4),
                  tuple(e.evidence_id for e in positive),
                  tuple(e.evidence_id for e in negative), unknowns,
                  grants_authority=False, may_trigger_consequential_tool=False)


def select_strategy(strategies: Iterable[Strategy], capabilities: set[str], budget: float,
                    failed: set[str] | None = None) -> Strategy | None:
    """Choose highest bounded information gain per cost, excluding failed paths."""
    failed = failed or set()
    eligible = [s for s in strategies if s.available and s.name not in failed
                and s.requires <= capabilities and 0 < s.cost <= budget]
    return max(eligible, key=lambda s: (s.expected_information_gain / s.cost,
                                        s.expected_information_gain, -s.cost), default=None)


def should_stop(state: ControlState, *, max_iterations: int = 8) -> tuple[bool, str]:
    if state.iterations >= max_iterations:
        return True, "BOUNDED_REASONING_LIMIT"
    recent = state.observations[-3:]
    if len(recent) == 3 and len(set(recent)) == 1:
        return True, "NO_NEW_INFORMATION"
    if state.disposition in {"VERIFIED", "ABSTAIN", "VERIFY_REQUIRED", "DEFERRED"}:
        return True, state.disposition
    return False, "CONTINUE"


def brier_score(predictions: Iterable[tuple[float, bool]]) -> float:
    rows = list(predictions)
    if not rows:
        raise ValueError("at least one scored prediction is required")
    if any(not math.isfinite(p) or p < 0 or p > 1 for p, _ in rows):
        raise ValueError("probabilities must be finite and within [0,1]")
    return round(sum((p - float(outcome)) ** 2 for p, outcome in rows) / len(rows), 6)


def expected_calibration_error(predictions: Iterable[tuple[float, bool]], bins: int = 10) -> float:
    rows = list(predictions)
    if not rows or bins < 1:
        raise ValueError("predictions and positive bins are required")
    if any(not math.isfinite(p) or p < 0 or p > 1 for p, _ in rows):
        raise ValueError("probabilities must be finite and within [0,1]")
    total = len(rows); error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        group = [(p, y) for p, y in rows if low <= p <= high and (index == bins-1 or p < high)]
        if group:
            confidence = sum(p for p, _ in group) / len(group)
            accuracy = sum(bool(y) for _, y in group) / len(group)
            error += len(group) / total * abs(confidence - accuracy)
    return round(error, 6)


def revise(previous: Belief, evidence: Iterable[Evidence]) -> Belief:
    """Reassess rather than anchoring; retain prior evidence only via caller input."""
    revised = assess(previous.proposition, evidence)
    if revised.state == EpistemicState.UNKNOWN and previous.state != EpistemicState.UNKNOWN:
        revised.unknowns += ("prior_conclusion_not_carried_without_current_evidence",)
    return revised
