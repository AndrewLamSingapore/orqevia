"""Held-out, cross-domain structural evaluation for the isolated GI candidate."""
from __future__ import annotations
import argparse, json, time, tracemalloc
from pathlib import Path
from app.general_intelligence import *


def evaluate():
    start=time.perf_counter();tracemalloc.start();rows=[]
    def case(name,domain,actual,expected,baseline):
        rows.append({"case":name,"domain":domain,"candidate":actual,"expected":expected,
                     "baseline":baseline,"candidate_pass":actual==expected,"baseline_pass":baseline==expected})
    case("few samples do not prove universal bloom","botany",induce("all bloom",[(True,"plot-a")]).kind.value,"HYPOTHESIS","FACT")
    case("counterexample retained under changed clinic","medicine","counterexamples_present" in induce("treatment works",[(True,"clinic-a"),(False,"clinic-b"),(True,"clinic-c")]).uncertainty,True,False)
    case("affirming consequent rejected","logic",deduce(antecedent="virus",consequent="fever",consequent_true=True,requested_rule="affirming_consequent").valid,False,True)
    case("modus tollens transfers terminology","ecology",deduce(antecedent="invasive",consequent="decline",consequent_true=False,requested_rule="modus_tollens").conclusion,"not invasive",None)
    case("correlation is not cause","economics",assess_causality(temporal_order=True,correlation=True).status,"CAUSAL_UNKNOWN","SUPPORTED_CAUSAL")
    case("intervention evidence supports cause","manufacturing",assess_causality(temporal_order=True,mechanism=True,intervention=True,confounders_addressed=True).status,"SUPPORTED_CAUSAL","CAUSAL_UNKNOWN")
    states=[WorldState("航班","状态","延误",TemporalState.HISTORICAL,1,("旧",)),WorldState("航班","状态","准时",TemporalState.CURRENT,2,("新",))]
    case("Chinese current state outranks history","multilingual",current_world(states)[("航班","状态")].value,"准时","延误")
    claims=[Claim("lab","candidate healthy",ClaimKind.OBSERVATION,"test",("e",),scope="LAB",temporal=TemporalState.CURRENT),Claim("prod","production healthy",ClaimKind.OBSERVATION,"runtime",("r",),scope="PRODUCTION",temporal=TemporalState.CURRENT)]
    case("candidate evidence not production","operations",[x.claim_id for x in reconstruct_context("production healthy","PRODUCTION",claims,now=3).selected],["prod"],["lab","prod"])
    case("simulation not physical","robotics",current_world([WorldState("arm","moved",True,TemporalState.PREDICTED,1,("sim",))]),{}, {"arm.moved":True})
    case("stale plan assumption blocks","planning",plan_steps([PlanStep("launch",assumptions=("weather-current",))],set()).disposition,"VERIFY_REQUIRED","PLANNED")
    case("dependency cycle detected","project",plan_steps([PlanStep("a",("b",)),PlanStep("b",("a",))],set()).blockers,("dependency_cycle",),())
    case("one success not durable lesson","education",evaluate_lesson("method works",[True],provenance=("trial",),counterexample_checked=True).disposition,"HYPOTHESIS_ONLY","STORE")
    case("mixed outcomes not durable lesson","sports",evaluate_lesson("drill works",[True,False,True],provenance=("games",),counterexample_checked=True).disposition,"HYPOTHESIS_ONLY","STORE")
    case("member cannot inherit owner context","authorization",reconstruct_context("accepted","MEMBER",[Claim("o","accepted",ClaimKind.OBSERVATION,"owner",("e",),scope="OWNER")],now=1).selected,(),("owner",))
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop();elapsed=time.perf_counter()-start
    candidate=sum(r["candidate_pass"] for r in rows);baseline=sum(r["baseline_pass"] for r in rows)
    return {"schema_version":"1.0","evaluation_class":"HELD_OUT_CROSS_DOMAIN_STRUCTURAL",
            "sample_count":len(rows),"domains":sorted({r["domain"] for r in rows}),"rows":rows,
            "candidate":{"correct":candidate,"accuracy":candidate/len(rows),"latency_ms":round(elapsed*1000,4),"peak_memory_bytes":peak},
            "baseline":{"correct":baseline,"accuracy":baseline/len(rows)},
            "passed":candidate==len(rows) and candidate>baseline,
            "limitations":["deterministic structural cases","small sample","does not establish AGI","not production-proven"]}


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path);a=p.parse_args();r=evaluate();text=json.dumps(r,indent=2,ensure_ascii=True,sort_keys=True)
    if a.output:a.output.write_text(text+"\n",encoding="utf-8")
    print(text);raise SystemExit(0 if r["passed"] else 1)
