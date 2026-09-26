"""Governed competence-frontier and instruction-learning primitives.

The module records what a candidate can demonstrate.  It cannot grant runtime
authority, activate instructions, deploy code, or promote its own verifier.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from enum import Enum
from graphlib import CycleError, TopologicalSorter
import math
from typing import Iterable


class CompetenceState(str, Enum):
    MASTERED="MASTERED"; CAPABLE="CAPABLE"; LEARNING="LEARNING"
    UNKNOWN="UNKNOWN"; CONTRADICTED="CONTRADICTED"; NEEDS_REVALIDATION="NEEDS_REVALIDATION"


class KnowledgeStatus(str, Enum):
    ACTIVE="ACTIVE"; SUPERSEDED="SUPERSEDED"; STALE="STALE"; ARCHIVED="ARCHIVED"; CONTRADICTED="CONTRADICTED"


@dataclass(frozen=True)
class CapabilityEvidence:
    evidence_id: str
    independent: bool
    held_out: bool
    transfer_level: int
    retained: bool
    current: bool
    source_sha: str

    def __post_init__(self):
        if not 0 <= self.transfer_level <= 7: raise ValueError("transfer level must be T0-T7")
        if len(self.source_sha) != 40 or any(c not in "0123456789abcdef" for c in self.source_sha):
            raise ValueError("evidence requires lowercase full source SHA")


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    description: str
    state: CompetenceState
    scope: str
    dependencies: tuple[str,...]=()
    evidence: tuple[CapabilityEvidence,...]=()
    last_verified: int|None=None
    freshness_seconds: int|None=None
    limitations: tuple[str,...]=()
    failure_modes: tuple[str,...]=()


def classify_capability(record: CapabilityRecord, *, now: int) -> CompetenceState:
    if record.state == CompetenceState.CONTRADICTED: return CompetenceState.CONTRADICTED
    if record.last_verified is None or record.last_verified > now or (record.freshness_seconds is not None and now-record.last_verified > record.freshness_seconds):
        return CompetenceState.NEEDS_REVALIDATION if record.evidence else CompetenceState.UNKNOWN
    valid=[e for e in record.evidence if e.current]
    if not valid: return CompetenceState.UNKNOWN
    independent=any(e.independent for e in valid);held_out=any(e.held_out for e in valid)
    transfer=max((e.transfer_level for e in valid),default=0);retained=any(e.retained for e in valid)
    if independent and held_out and transfer>=5 and retained:return CompetenceState.MASTERED
    if independent and transfer>=1:return CompetenceState.CAPABLE
    return CompetenceState.LEARNING


@dataclass(frozen=True)
class CapabilityNode:
    node_id: str
    capability: str
    dependencies: tuple[str,...]=()
    success_condition: str=""
    atomic: bool=False


@dataclass(frozen=True)
class DecompositionResult:
    order: tuple[str,...]
    disposition: str
    defects: tuple[str,...]


def validate_decomposition(nodes: Iterable[CapabilityNode]) -> DecompositionResult:
    rows=list(nodes);ids=[n.node_id for n in rows];defects=[]
    if len(ids)!=len(set(ids)):defects.append("duplicate_or_overlapping_node")
    missing=sorted({d for n in rows for d in n.dependencies if d not in ids})
    defects += [f"missing_prerequisite:{x}" for x in missing]
    defects += [f"unverifiable:{n.node_id}" for n in rows if not n.success_condition.strip()]
    if defects:return DecompositionResult((),"REVISE",tuple(defects))
    try:order=tuple(TopologicalSorter({n.node_id:set(n.dependencies) for n in rows}).static_order())
    except CycleError:return DecompositionResult((),"REVISE",("circular_dependency",))
    return DecompositionResult(order,"ACCEPT",())


@dataclass(frozen=True)
class TransferResult:
    ceiling: int
    passed_levels: tuple[int,...]
    failed_level: int|None
    state: CompetenceState


def evaluate_transfer(results: Iterable[tuple[int,bool]]) -> TransferResult:
    rows=sorted(results);expected=0;passed=[];failed=None
    for level,ok in rows:
        if level!=expected or not ok:failed=expected;break
        passed.append(level);expected+=1
    ceiling=max(passed,default=-1)
    state=CompetenceState.CAPABLE if ceiling>=5 else CompetenceState.LEARNING if ceiling>=0 else CompetenceState.UNKNOWN
    return TransferResult(ceiling,tuple(passed),failed,state)


@dataclass(frozen=True)
class BeliefNode:
    belief_id: str
    dependencies: tuple[str,...]=()
    status: KnowledgeStatus=KnowledgeStatus.ACTIVE


def invalidate_dependents(beliefs: Iterable[BeliefNode], invalidated: set[str]) -> tuple[BeliefNode,...]:
    rows={b.belief_id:b for b in beliefs};affected=set(invalidated);changed=True
    while changed:
        changed=False
        for belief in rows.values():
            if belief.belief_id not in affected and set(belief.dependencies)&affected:
                affected.add(belief.belief_id);changed=True
    return tuple(replace(b,status=KnowledgeStatus.CONTRADICTED if b.belief_id in invalidated else KnowledgeStatus.STALE)
                 if b.belief_id in affected else b for b in rows.values())


def operational_knowledge(records: Iterable[tuple[str,KnowledgeStatus,int|None]], *, now:int, max_age:int) -> tuple[str,...]:
    if max_age < 0: raise ValueError("max_age must be nonnegative")
    active=[]
    for identity,status,observed in records:
        if status!=KnowledgeStatus.ACTIVE:continue
        if observed is None or observed>now or now-observed>max_age:continue
        active.append(identity)
    return tuple(active)


@dataclass(frozen=True)
class InstructionVersion:
    instruction_id: str
    version: str
    text: str
    objective: str
    evidence_ids: tuple[str,...]
    held_out_pass: bool
    adversarial_pass: bool
    transfer_level: int
    independent_verifier: str|None
    weakens_evidence: bool=False
    changes_objective: bool=False
    status: str="CANDIDATE"


@dataclass(frozen=True)
class RewriteDecision:
    disposition: str
    reasons: tuple[str,...]


def evaluate_instruction_rewrite(current: InstructionVersion, candidate: InstructionVersion) -> RewriteDecision:
    reasons=[]
    if current.instruction_id!=candidate.instruction_id:reasons.append("instruction_identity_changed")
    if current.objective!=candidate.objective or candidate.changes_objective:reasons.append("objective_drift")
    if candidate.weakens_evidence:reasons.append("evidence_weakened")
    if not candidate.evidence_ids:reasons.append("evidence_missing")
    if not candidate.held_out_pass:reasons.append("held_out_failed")
    if not candidate.adversarial_pass:reasons.append("adversarial_failed")
    if candidate.transfer_level<3:reasons.append("transfer_insufficient")
    if not candidate.independent_verifier:reasons.append("independent_verifier_missing")
    elif candidate.independent_verifier.casefold() in {"self","builder","candidate"}:reasons.append("verifier_not_independent")
    return RewriteDecision("ACCEPT_CANDIDATE" if not reasons else "REJECT",tuple(reasons))


def acquisition_priority(*, information_gain:float, capability_gain:float, transfer_value:float,
                         objective_value:float, time_cost:float, compute_cost:float,
                         risk:float, human_intervention:float) -> float:
    values=(information_gain,capability_gain,transfer_value,objective_value,time_cost,compute_cost,risk,human_intervention)
    if any(not math.isfinite(x) or x<0 for x in values):raise ValueError("priority inputs must be finite and nonnegative")
    cost=time_cost+compute_cost+risk+human_intervention
    if cost<=0:raise ValueError("cost must be positive")
    return round(information_gain*capability_gain*transfer_value*objective_value/cost,6)


ACQUISITION_SEQUENCE=("UNKNOWN","GAP_DETECTED","LEARNING_OBJECTIVE","EVIDENCE_ACQUIRED",
 "MODEL_CONSTRUCTED","ATTEMPTED","VERIFIED","ABSTRACTED","TRANSFER_TESTED","RETAINED")


@dataclass(frozen=True)
class AcquisitionEpisode:
    episode_id: str
    states: tuple[str,...]
    evidence_ids: tuple[str,...]
    human_interventions: int
    elapsed_seconds: float


def verify_acquisition(episode: AcquisitionEpisode) -> tuple[bool,tuple[str,...]]:
    reasons=[]
    positions=[]
    for state in ACQUISITION_SEQUENCE:
        if state not in episode.states:reasons.append(f"missing:{state}")
        else:positions.append(episode.states.index(state))
    if positions!=sorted(positions):reasons.append("lifecycle_out_of_order")
    if not episode.evidence_ids:reasons.append("evidence_missing")
    if episode.human_interventions<0 or not math.isfinite(episode.elapsed_seconds) or episode.elapsed_seconds<0:reasons.append("metrics_invalid")
    return not reasons,tuple(reasons)


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    invariant: str
    conditions: tuple[str,...]
    evidence_ids: tuple[str,...]


def compress_lessons(lessons: Iterable[Lesson]) -> tuple[tuple[str,tuple[str,...]],...]:
    """Compress only identical supported invariants under identical conditions."""
    groups={}
    for lesson in lessons:
        if not lesson.evidence_ids:continue
        groups.setdefault((lesson.invariant,lesson.conditions),[]).append(lesson.lesson_id)
    return tuple((invariant,tuple(ids)) for (invariant,_),ids in sorted(groups.items()) if len(ids)>=2)


@dataclass(frozen=True)
class LearningStrategyResult:
    strategy: str
    verified_gain: float
    cost: float
    transfer_level: int


def select_learning_strategy(results: Iterable[LearningStrategyResult]) -> str|None:
    valid=[r for r in results if r.cost>0 and math.isfinite(r.cost) and math.isfinite(r.verified_gain)
           and r.verified_gain>=0 and 0<=r.transfer_level<=7]
    return max(valid,key=lambda r:(r.verified_gain*(1+r.transfer_level)/r.cost,-r.cost),default=None).strategy if valid else None
