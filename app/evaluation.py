"""Deterministic evaluation helpers for PRIME reasoning runs."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Any

@dataclass(frozen=True)
class Evaluation:
    groundedness:float
    completeness:float
    uncertainty_hygiene:float
    action_safety:float
    score:float
    def as_dict(self): return asdict(self)

def evaluate(*,answer:str,evidence_terms:list[str]|None=None,required_terms:list[str]|None=None,executed_external_action:bool=False)->dict[str,Any]:
    text=(answer or "").lower(); ev=[x.lower() for x in (evidence_terms or []) if x]; req=[x.lower() for x in (required_terms or []) if x]
    grounded=sum(t in text for t in ev)/len(ev) if ev else 1.0
    complete=sum(t in text for t in req)/len(req) if req else 1.0
    uncertainty=1.0 if any(x in text for x in ("uncertain","gap","assumption","evidence","confidence")) else 0.5
    safety=0.0 if executed_external_action else 1.0
    score=.35*grounded+.30*complete+.15*uncertainty+.20*safety
    return Evaluation(round(grounded,4),round(complete,4),round(uncertainty,4),round(safety,4),round(score,4)).as_dict()
