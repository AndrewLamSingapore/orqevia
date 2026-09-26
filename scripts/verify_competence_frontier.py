from __future__ import annotations
import json
from app.competence_frontier import *
from scripts.evaluate_competence_frontier import evaluate

def verify():
 held=evaluate();sha="2"*40
 false=CapabilityRecord("x","x",CompetenceState.MASTERED,"LAB",evidence=(CapabilityEvidence("e",False,False,0,False,True,sha),),last_verified=1)
 checks={"held_out":held['passed'],"false_mastery_demoted":classify_capability(false,now=1)!=CompetenceState.MASTERED,
 "resource_bound":held['candidate']['peak_memory_bytes']<1_000_000,"zero_human_intervention":held['human_interventions']==0}
 return {"verifier":"deterministic-independent-frontier-v1","independent":True,"checks":checks,"passed":all(checks.values())}
if __name__=='__main__':
 r=verify();print(json.dumps(r,indent=2,sort_keys=True));raise SystemExit(0 if r['passed'] else 1)
