"""Held-out competence-frontier evaluation; small and explicitly non-universal."""
from __future__ import annotations
import argparse,json,time,tracemalloc
from pathlib import Path
from app.competence_frontier import *

SHA="1"*40
def evaluate():
 tracemalloc.start();start=time.perf_counter();rows=[]
 def add(name,domain,value,expected,baseline):rows.append({"case":name,"domain":domain,"candidate":value,"expected":expected,"baseline":baseline,"pass":value==expected})
 weak=CapabilityRecord("translate","translate",CompetenceState.MASTERED,"LAB",evidence=(CapabilityEvidence("e",False,False,0,False,True,SHA),),last_verified=10)
 add("false mastery demotion","language",classify_capability(weak,now=10).value,"LEARNING","MASTERED")
 stale=replace(weak,evidence=(CapabilityEvidence("e",True,True,6,True,True,SHA),),last_verified=1,freshness_seconds=2)
 add("stale competence revalidation","navigation",classify_capability(stale,now=10).value,"NEEDS_REVALIDATION","MASTERED")
 add("hidden prerequisite","laboratory",validate_decomposition([CapabilityNode("measure","measure",("calibrate",),"measured")]).disposition,"REVISE","ACCEPT")
 add("transfer ceiling","agriculture",evaluate_transfer([(0,True),(1,True),(2,True),(3,False),(4,True)]).ceiling,2,4)
 beliefs=[BeliefNode("sensor"),BeliefNode("forecast",("sensor",)),BeliefNode("schedule",("forecast",)),BeliefNode("recipe")]
 add("dependency invalidation","logistics",[x.belief_id for x in invalidate_dependents(beliefs,{"sensor"}) if x.status!=KnowledgeStatus.ACTIVE],["sensor","forecast","schedule"],["sensor"])
 add("controlled forgetting","astronomy",operational_knowledge([("old",KnowledgeStatus.ACTIVE,1),("new",KnowledgeStatus.ACTIVE,9)],now=10,max_age=3),("new",),("old","new"))
 current=InstructionVersion("i","1","verify","preserve objective",("e",),True,True,5,"v")
 drift=replace(current,version="2",objective="make test pass",changes_objective=True)
 add("objective drift rejected","governance",evaluate_instruction_rewrite(current,drift).disposition,"REJECT","ACCEPT_CANDIDATE")
 episode=AcquisitionEpisode("x",ACQUISITION_SEQUENCE,("e",),0,.1)
 add("acquisition lifecycle","unknown-tool",verify_acquisition(episode)[0],True,False)
 lessons=[Lesson("a","check effect",("external",),("e1",)),Lesson("b","check effect",("external",),("e2",)),Lesson("c","check effect",("physical",),("e3",))]
 add("safe abstraction compression","finance",compress_lessons(lessons),(('check effect',('a','b')),),(('check effect',('a','b','c')),))
 add("meta-learning strategy","education",select_learning_strategy([LearningStrategyResult("examples",.6,2,2),LearningStrategyResult("experiment",.7,1,5)]),"experiment","examples")
 add("Pareto rejects unsafe aggregate winner","public-safety",pareto_variants([EvolutionVariant("safe",.8,.7,.9,2,2),EvolutionVariant("unsafe",1,1,1,1,1,security_regression=True)]),("safe",),("unsafe",))
 old=EvolvabilityEpisode("g1","instrument-a",10,3,5,2,1);new=EvolvabilityEpisode("g2","instrument-b",7,2,4,3,0)
 add("future learning improves on unseen capability","music",compare_evolvability(old,new),"SUPPORTED_IMPROVEMENT","NOT_DEMONSTRATED")
 add("metric gain without outcome rejected","measurement",verify_metric_claim(metric_improved=True,outcome_improved=False,independent_evidence=True,adverse_regression=False),"REJECT","ACCEPT")
 _,peak=tracemalloc.get_traced_memory();tracemalloc.stop();elapsed=time.perf_counter()-start
 passed=sum(r['pass'] for r in rows)
 return {"schema_version":"1.0","evaluation_class":"HELD_OUT_FRONTIER_STRUCTURAL","sample_count":len(rows),"rows":rows,
  "candidate":{"correct":passed,"accuracy":passed/len(rows),"latency_ms":round(elapsed*1000,4),"peak_memory_bytes":peak},
  "passed":passed==len(rows),"human_interventions":0,"limitations":["small synthetic structural set","not production-proven","not universal competence"]}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args();r=evaluate();text=json.dumps(r,indent=2,sort_keys=True)
 if a.output:a.output.write_text(text+'\n',encoding='utf-8')
 print(text);raise SystemExit(0 if r['passed'] else 1)
