import pytest
from app.competence_frontier import *

SHA="0"*40
def ev(i="e",**kw):return CapabilityEvidence(i,True,True,5,True,True,SHA,**kw)

def test_mastered_requires_independent_heldout_transfer_and_retention():
    r=CapabilityRecord("c","c",CompetenceState.LEARNING,"LAB",evidence=(ev(),),last_verified=10)
    assert classify_capability(r,now=11)==CompetenceState.MASTERED

def test_false_mastered_demotes_for_stale_or_weak_evidence():
    stale=CapabilityRecord("c","c",CompetenceState.MASTERED,"LAB",evidence=(ev(),),last_verified=1,freshness_seconds=5)
    weak=CapabilityRecord("c","c",CompetenceState.MASTERED,"LAB",evidence=(CapabilityEvidence("e",False,False,0,False,True,SHA),),last_verified=10)
    assert classify_capability(stale,now=10)==CompetenceState.NEEDS_REVALIDATION
    assert classify_capability(weak,now=10)==CompetenceState.LEARNING
    assert classify_capability(replace(stale,last_verified=20),now=10)==CompetenceState.NEEDS_REVALIDATION

def test_contradiction_demotes_mastered():
    r=CapabilityRecord("c","c",CompetenceState.CONTRADICTED,"LAB",evidence=(ev(),),last_verified=10)
    assert classify_capability(r,now=10)==CompetenceState.CONTRADICTED

def test_decomposition_detects_hidden_missing_cycle_overlap_and_unverifiable():
    assert validate_decomposition([CapabilityNode("a","a",("hidden",),"ok")]).disposition=="REVISE"
    assert "circular_dependency" in validate_decomposition([CapabilityNode("a","a",("b",),"ok"),CapabilityNode("b","b",("a",),"ok")]).defects
    assert "duplicate_or_overlapping_node" in validate_decomposition([CapabilityNode("a","a",(),"ok"),CapabilityNode("a","b",(),"ok")]).defects
    assert "unverifiable:a" in validate_decomposition([CapabilityNode("a","a")]).defects

def test_minimum_valid_graph_orders_dependencies():
    r=validate_decomposition([CapabilityNode("observe","observation",(),"evidence exists"),CapabilityNode("verify","verification",("observe",),"independent check passes")])
    assert r.disposition=="ACCEPT" and r.order==("observe","verify")

def test_transfer_ladder_stops_at_first_failure_and_no_skipping():
    r=evaluate_transfer([(0,True),(1,True),(2,False),(3,True)])
    assert r.ceiling==1 and r.failed_level==2 and r.state==CompetenceState.LEARNING
    assert evaluate_transfer([(1,True)]).ceiling==-1

def test_dependency_invalidation_is_transitive_but_bounded():
    rows=[BeliefNode("premise"),BeliefNode("child",("premise",)),BeliefNode("grand",("child",)),BeliefNode("unrelated")]
    out={x.belief_id:x.status for x in invalidate_dependents(rows,{"premise"})}
    assert out=={"premise":KnowledgeStatus.CONTRADICTED,"child":KnowledgeStatus.STALE,"grand":KnowledgeStatus.STALE,"unrelated":KnowledgeStatus.ACTIVE}

def test_controlled_forgetting_preserves_only_fresh_active_control():
    rows=[("fresh",KnowledgeStatus.ACTIVE,9),("old",KnowledgeStatus.ACTIVE,1),("history",KnowledgeStatus.ARCHIVED,9)]
    assert operational_knowledge(rows,now=10,max_age=5)==("fresh",)

def version(**kw):
    base=dict(instruction_id="verify-effect",version="1",text="issued is not verified",objective="verify effects",evidence_ids=("e",),held_out_pass=True,adversarial_pass=True,transfer_level=4,independent_verifier="v")
    base.update(kw);return InstructionVersion(**base)

def test_instruction_rewrite_accepts_evidenced_transfer_without_objective_drift():
    assert evaluate_instruction_rewrite(version(),version(version="2",text="verify observed effect")).disposition=="ACCEPT_CANDIDATE"

@pytest.mark.parametrize("change,reason",[
 ({"objective":"pass tests"},"objective_drift"),({"weakens_evidence":True},"evidence_weakened"),
 ({"evidence_ids":()},"evidence_missing"),({"held_out_pass":False},"held_out_failed"),
 ({"adversarial_pass":False},"adversarial_failed"),({"transfer_level":1},"transfer_insufficient"),
 ({"independent_verifier":None},"independent_verifier_missing")])
def test_bad_instruction_rewrites_rejected(change,reason):
    r=evaluate_instruction_rewrite(version(),version(version="2",**change))
    assert r.disposition=="REJECT" and reason in r.reasons

def test_self_named_verifier_is_not_independent():
    r=evaluate_instruction_rewrite(version(),version(version="2",independent_verifier="self"))
    assert r.disposition=="REJECT" and "verifier_not_independent" in r.reasons

def test_priority_requires_bounded_real_cost():
    assert acquisition_priority(information_gain=1,capability_gain=1,transfer_value=1,objective_value=1,time_cost=1,compute_cost=0,risk=0,human_intervention=0)==1
    with pytest.raises(ValueError):acquisition_priority(information_gain=1,capability_gain=1,transfer_value=1,objective_value=1,time_cost=0,compute_cost=0,risk=0,human_intervention=0)
    with pytest.raises(ValueError):operational_knowledge([],now=1,max_age=-1)

def test_full_capability_acquisition_lifecycle_verified():
    e=AcquisitionEpisode("x",ACQUISITION_SEQUENCE,("e",),0,.1)
    assert verify_acquisition(e)==(True,())
    assert not verify_acquisition(AcquisitionEpisode("x",("UNKNOWN","VERIFIED"),(),0,.1))[0]

def test_abstraction_compression_preserves_material_conditions():
    rows=[Lesson("a","issued action is not verified effect",("external",),("e1",)),
          Lesson("b","issued action is not verified effect",("external",),("e2",)),
          Lesson("c","issued action is not verified effect",("simulation",),("e3",)),
          Lesson("d","unsupported",("external",),())]
    compressed=compress_lessons(rows)
    assert compressed==(("issued action is not verified effect",("a","b")),)

def test_meta_learning_selects_verified_transfer_efficiency():
    rows=[LearningStrategyResult("docs",.8,2,5),LearningStrategyResult("guess",.9,10,0),LearningStrategyResult("experiment",.7,1,4)]
    assert select_learning_strategy(rows)=="experiment"

def test_pareto_selection_rejects_regressions_and_dominated_complexity():
    rows=[EvolutionVariant("baseline",.8,.5,.9,2,2),EvolutionVariant("better",.9,.7,.95,1,2),
          EvolutionVariant("bloated",.9,.7,.95,1,5),EvolutionVariant("unsafe",1,1,1,.5,1,security_regression=True)]
    assert pareto_variants(rows)==("better",)

def test_evolvability_requires_different_future_task_and_all_round_improvement():
    old=EvolvabilityEpisode("g1","tool-a",10,3,5,3,1)
    new=EvolvabilityEpisode("g2","tool-b",7,2,4,4,0)
    assert compare_evolvability(old,new)=="SUPPORTED_IMPROVEMENT"
    assert compare_evolvability(old,replace(new,capability="tool-a"))=="INCONCLUSIVE_SAME_TASK"
    assert compare_evolvability(old,replace(new,attempts=4))=="NOT_DEMONSTRATED"

def test_anti_goodhart_requires_real_independent_outcome_without_regression():
    assert verify_metric_claim(metric_improved=True,outcome_improved=True,independent_evidence=True,adverse_regression=False)=="ACCEPT"
    assert verify_metric_claim(metric_improved=True,outcome_improved=False,independent_evidence=True,adverse_regression=False)=="REJECT"
    assert verify_metric_claim(metric_improved=True,outcome_improved=True,independent_evidence=False,adverse_regression=False)=="REJECT"
