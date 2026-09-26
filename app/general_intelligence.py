"""Authority-neutral general reasoning primitives for the isolated candidate.

These deterministic structures preserve context, provenance and uncertainty.
They never execute tools, mutate production, or grant authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from graphlib import TopologicalSorter, CycleError
import math
from typing import Iterable


class ClaimKind(str, Enum):
    OBSERVATION="OBSERVATION"; FACT="FACT"; ASSUMPTION="ASSUMPTION"
    PATTERN="PATTERN"; HYPOTHESIS="HYPOTHESIS"; INFERENCE="INFERENCE"
    DEDUCTION="DEDUCTION"; PREDICTION="PREDICTION"; COUNTEREVIDENCE="COUNTEREVIDENCE"
    CONTRADICTION="CONTRADICTION"; UNKNOWN="UNKNOWN"; CONCLUSION="CONCLUSION"


class TemporalState(str, Enum):
    CURRENT="CURRENT"; HISTORICAL="HISTORICAL"; SUPERSEDED="SUPERSEDED"
    PLANNED="PLANNED"; PREDICTED="PREDICTED"; UNKNOWN_TIME="UNKNOWN_TIME"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    proposition: str
    kind: ClaimKind
    source: str
    evidence_ids: tuple[str, ...] = ()
    counterevidence_ids: tuple[str, ...] = ()
    timestamp: int | None = None
    scope: str = "UNKNOWN"
    temporal: TemporalState = TemporalState.UNKNOWN_TIME
    confidence: float | None = None
    assumptions: tuple[str, ...] = ()
    falsification: tuple[str, ...] = ()
    grants_authority: bool = False

    def __post_init__(self):
        if self.confidence is not None and (not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ValueError("confidence must be finite and within [0,1]")
        if self.kind == ClaimKind.FACT and not self.evidence_ids:
            raise ValueError("fact requires attributable evidence")
        if self.grants_authority:
            raise ValueError("reasoning claims cannot grant authority")


@dataclass(frozen=True)
class ContextContradiction:
    proposition: str
    scope: str
    old_claim_id: str
    new_claim_id: str
    explanation: str = "unresolved"


@dataclass(frozen=True)
class ContextModel:
    objective: str
    scope: str
    selected: tuple[Claim, ...]
    contradictions: tuple[ContextContradiction, ...]
    missing: tuple[str, ...]


def reconstruct_context(objective: str, scope: str, claims: Iterable[Claim], *, now: int,
                        max_items: int = 24, max_age: int = 3600) -> ContextModel:
    """Select smallest relevant current context and preserve scoped conflicts."""
    if not objective.strip() or not scope.strip() or max_items < 1 or max_age < 0:
        raise ValueError("objective and scope are required")
    words = {w.casefold() for w in objective.split() if len(w) > 2}
    eligible = [c for c in claims if c.scope in {scope, "GLOBAL"}]
    def rank(c: Claim):
        relevance = len(words & {w.casefold() for w in c.proposition.split()})
        temporal = 3 if c.temporal == TemporalState.CURRENT else 2 if c.temporal == TemporalState.UNKNOWN_TIME else 1
        freshness = c.timestamp if c.timestamp is not None else -1
        return relevance, temporal, freshness
    selected = sorted(eligible, key=rank, reverse=True)[:max_items]
    by_prop: dict[str, list[Claim]] = {}
    for claim in selected:
        by_prop.setdefault(claim.proposition.casefold(), []).append(claim)
    conflicts=[]
    for rows in by_prop.values():
        positive=[c for c in rows if c.kind not in {ClaimKind.COUNTEREVIDENCE, ClaimKind.CONTRADICTION}]
        negative=[c for c in rows if c.kind in {ClaimKind.COUNTEREVIDENCE, ClaimKind.CONTRADICTION}]
        if positive and negative:
            conflicts.append(ContextContradiction(rows[0].proposition, scope, positive[0].claim_id, negative[0].claim_id))
    missing=[]
    if not selected: missing.append("relevant_context")
    if any(c.temporal == TemporalState.UNKNOWN_TIME or
           (c.temporal == TemporalState.CURRENT and
            (c.timestamp is None or c.timestamp > now or now-c.timestamp > max_age))
           for c in selected): missing.append("freshness")
    if conflicts: missing.append("contradiction_resolution")
    return ContextModel(objective, scope, tuple(selected), tuple(conflicts), tuple(missing))


@dataclass(frozen=True)
class InductionResult:
    kind: ClaimKind
    proposition: str
    sample_count: int
    support: int
    counterexamples: int
    distribution_count: int
    uncertainty: tuple[str, ...]


def induce(proposition: str, observations: Iterable[tuple[bool, str]], *, minimum=3) -> InductionResult:
    rows=list(observations)
    if minimum < 2: raise ValueError("minimum must be at least two")
    support=sum(value for value, _ in rows); counter=len(rows)-support
    distributions=len({group for _, group in rows})
    uncertainty=[]
    if len(rows)<minimum: uncertainty.append("insufficient_sample")
    if distributions<2: uncertainty.append("distribution_coverage")
    if counter: uncertainty.append("counterexamples_present")
    kind=ClaimKind.UNKNOWN if not rows else ClaimKind.HYPOTHESIS
    return InductionResult(kind, proposition, len(rows), support, counter, distributions, tuple(uncertainty))


@dataclass(frozen=True)
class DeductionResult:
    conclusion: str | None
    valid: bool
    factual_premises_verified: bool
    rule: str
    violations: tuple[str, ...] = ()


def deduce(*, antecedent: str, consequent: str, antecedent_true: bool | None = None,
           consequent_true: bool | None = None, premise_evidence: bool = False,
           requested_rule: str = "modus_ponens") -> DeductionResult:
    if requested_rule == "modus_ponens" and antecedent_true is True:
        return DeductionResult(consequent, True, premise_evidence, requested_rule)
    if requested_rule == "modus_tollens" and consequent_true is False:
        return DeductionResult(f"not {antecedent}", True, premise_evidence, requested_rule)
    invalid={"affirming_consequent":"affirming_the_consequent", "denying_antecedent":"denying_the_antecedent"}
    if requested_rule in invalid:
        return DeductionResult(None, False, premise_evidence, requested_rule, (invalid[requested_rule],))
    return DeductionResult(None, False, premise_evidence, requested_rule, ("premise_not_satisfied",))


@dataclass(frozen=True)
class CausalAssessment:
    status: str
    evidence: tuple[str, ...]
    gaps: tuple[str, ...]


def assess_causality(*, temporal_order=False, correlation=False, mechanism=False,
                     intervention=False, confounders_addressed=False) -> CausalAssessment:
    evidence=tuple(name for name, present in (("temporal_order",temporal_order),("correlation",correlation),
        ("mechanism",mechanism),("intervention",intervention),("confounders_addressed",confounders_addressed)) if present)
    required={"temporal_order","mechanism","intervention","confounders_addressed"}
    gaps=tuple(sorted(required-set(evidence)))
    return CausalAssessment("SUPPORTED_CAUSAL" if not gaps else "CAUSAL_UNKNOWN", evidence, gaps)


@dataclass(frozen=True)
class WorldState:
    entity: str
    attribute: str
    value: object
    temporal: TemporalState
    observed_at: int | None
    evidence_ids: tuple[str, ...]


def current_world(states: Iterable[WorldState]) -> dict[tuple[str,str], WorldState]:
    result={}
    for state in states:
        if state.temporal != TemporalState.CURRENT or not state.evidence_ids: continue
        key=(state.entity,state.attribute)
        if key not in result or (state.observed_at or -1) > (result[key].observed_at or -1): result[key]=state
    return result


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    consequential: bool = False


@dataclass(frozen=True)
class PlanResult:
    order: tuple[str, ...]
    disposition: str
    blockers: tuple[str, ...]
    requires_human_authority: bool


def plan_steps(steps: Iterable[PlanStep], valid_assumptions: set[str]) -> PlanResult:
    rows=list(steps); ids={s.step_id for s in rows}
    if len(ids)!=len(rows): return PlanResult((),"BLOCKED",("duplicate_step",),False)
    missing=sorted({d for s in rows for d in s.dependencies if d not in ids})
    stale=sorted({a for s in rows for a in s.assumptions if a not in valid_assumptions})
    if missing or stale: return PlanResult((),"VERIFY_REQUIRED",tuple([f"missing:{x}" for x in missing]+[f"stale:{x}" for x in stale]),False)
    try: order=tuple(TopologicalSorter({s.step_id:set(s.dependencies) for s in rows}).static_order())
    except CycleError: return PlanResult((),"BLOCKED",("dependency_cycle",),False)
    return PlanResult(order,"PLANNED",(),any(s.consequential for s in rows))


@dataclass(frozen=True)
class LearningDecision:
    disposition: str
    lesson: str
    reasons: tuple[str, ...]


def evaluate_lesson(lesson: str, outcomes: Iterable[bool], *, provenance: tuple[str,...],
                    counterexample_checked: bool) -> LearningDecision:
    rows=list(outcomes); reasons=[]
    if len(rows)<3: reasons.append("insufficient_repetition")
    if not provenance: reasons.append("missing_provenance")
    if not counterexample_checked: reasons.append("counterexamples_not_checked")
    if rows and not all(rows): reasons.append("mixed_outcomes")
    return LearningDecision("STORE" if not reasons else "HYPOTHESIS_ONLY",lesson,tuple(reasons))
