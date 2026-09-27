"""Independent deterministic verifier for the bounded GI candidate."""
from __future__ import annotations
import json
from app.general_intelligence import *


def verify():
    checks={
      "scope_isolation": not reconstruct_context("state","MEMBER",[Claim("o","state",ClaimKind.OBSERVATION,"owner",scope="OWNER")],now=1).selected,
      "stale_context_detected": "freshness" in reconstruct_context("state","ABEX",[Claim("s","state",ClaimKind.OBSERVATION,"log",timestamp=1,scope="ABEX",temporal=TemporalState.CURRENT)],now=100,max_age=10).missing,
      "false_deduction_rejected": not deduce(antecedent="a",consequent="b",consequent_true=True,requested_rule="affirming_consequent").valid,
      "correlation_not_cause": assess_causality(temporal_order=True,correlation=True).status=="CAUSAL_UNKNOWN",
      "simulation_not_observation": not current_world([WorldState("x","state",True,TemporalState.PREDICTED,1,("sim",))]),
      "stale_plan_blocked": plan_steps([PlanStep("x",assumptions=("fresh",))],set()).disposition=="VERIFY_REQUIRED",
      "one_shot_learning_blocked": evaluate_lesson("x",[True],provenance=("e",),counterexample_checked=True).disposition=="HYPOTHESIS_ONLY",
    }
    return {"verifier":"deterministic-independent-gi-v1","independent":True,"checks":checks,"passed":all(checks.values())}


if __name__=="__main__":
    result=verify();print(json.dumps(result,indent=2,sort_keys=True));raise SystemExit(0 if result["passed"] else 1)
