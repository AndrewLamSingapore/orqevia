import pytest
from app.general_intelligence import *


def claim(i, text="PRIME healthy", kind=ClaimKind.OBSERVATION, scope="ABEX", temporal=TemporalState.CURRENT, **kw):
    return Claim(i,text,kind,"fixture",scope=scope,temporal=temporal,**kw)


def test_fact_requires_evidence_and_reasoning_cannot_grant_authority():
    with pytest.raises(ValueError): claim("x",kind=ClaimKind.FACT)
    with pytest.raises(ValueError): claim("x",grants_authority=True)


def test_context_separates_machine_and_candidate_from_production():
    rows=[claim("a",scope="ABEX"),claim("d",scope="DELL"),claim("c","candidate passed",scope="CANDIDATE")]
    context=reconstruct_context("PRIME healthy","ABEX",rows,now=10)
    assert [x.claim_id for x in context.selected]==["a"]


def test_context_prefers_current_relevant_and_bounds_overload():
    rows=[claim(str(i),f"irrelevant {i}",timestamp=i) for i in range(30)]
    rows.append(claim("relevant","objective state",timestamp=40))
    context=reconstruct_context("objective state","ABEX",rows,now=50,max_items=5)
    assert len(context.selected)==5 and context.selected[0].claim_id=="relevant"


def test_context_preserves_contradiction_and_unknown_freshness():
    rows=[claim("old",timestamp=1),claim("new",kind=ClaimKind.COUNTEREVIDENCE,timestamp=2,temporal=TemporalState.UNKNOWN_TIME)]
    context=reconstruct_context("PRIME healthy","ABEX",rows,now=3)
    assert context.contradictions and set(context.missing)=={"freshness","contradiction_resolution"}


def test_context_marks_old_or_future_current_claim_stale():
    old=claim("old",timestamp=1)
    future=claim("future",timestamp=200)
    assert "freshness" in reconstruct_context("PRIME healthy","ABEX",[old],now=100,max_age=10).missing
    assert "freshness" in reconstruct_context("PRIME healthy","ABEX",[future],now=100,max_age=10).missing


def test_historical_does_not_replace_current_world_state():
    states=[WorldState("PRIME","health","bad",TemporalState.HISTORICAL,1,("old",)),WorldState("PRIME","health","good",TemporalState.CURRENT,2,("new",))]
    assert current_world(states)[("PRIME","health")].value=="good"


def test_prediction_and_simulation_are_not_current_observation():
    states=[WorldState("disk","health","good",TemporalState.PREDICTED,2,("sim",))]
    assert current_world(states)=={}


def test_induction_stays_hypothesis_and_tracks_counterexamples_distribution():
    r=induce("all bloom",[(True,"a"),(True,"b"),(False,"b")])
    assert r.kind==ClaimKind.HYPOTHESIS and r.counterexamples==1
    assert "counterexamples_present" in r.uncertainty and r.distribution_count==2


def test_induction_knows_insufficient_sample():
    assert "insufficient_sample" in induce("x",[(True,"a")]).uncertainty
    assert induce("x",[]).kind==ClaimKind.UNKNOWN


def test_valid_deduction_separates_validity_from_premise_truth():
    r=deduce(antecedent="rain",consequent="wet",antecedent_true=True,premise_evidence=False)
    assert r.valid and r.conclusion=="wet" and not r.factual_premises_verified


def test_modus_tollens():
    assert deduce(antecedent="rain",consequent="wet",consequent_true=False,requested_rule="modus_tollens").conclusion=="not rain"


@pytest.mark.parametrize("rule",["affirming_consequent","denying_antecedent"])
def test_invalid_deduction_traps(rule):
    assert not deduce(antecedent="a",consequent="b",requested_rule=rule).valid


def test_correlation_is_not_causation():
    r=assess_causality(temporal_order=True,correlation=True)
    assert r.status=="CAUSAL_UNKNOWN" and "intervention" in r.gaps


def test_causal_support_requires_mechanism_intervention_and_confounders():
    r=assess_causality(temporal_order=True,correlation=True,mechanism=True,intervention=True,confounders_addressed=True)
    assert r.status=="SUPPORTED_CAUSAL"


def test_plan_orders_dependencies_and_flags_authority_boundary():
    r=plan_steps([PlanStep("inspect"),PlanStep("publish",("inspect",),consequential=True)],set())
    assert r.order==("inspect","publish") and r.requires_human_authority


def test_plan_rejects_stale_assumption_missing_dependency_and_cycle():
    assert plan_steps([PlanStep("x",assumptions=("fresh",))],set()).disposition=="VERIFY_REQUIRED"
    assert plan_steps([PlanStep("x",("missing",))],set()).disposition=="VERIFY_REQUIRED"
    assert plan_steps([PlanStep("a",("b",)),PlanStep("b",("a",))],set()).disposition=="BLOCKED"


def test_learning_requires_repetition_provenance_and_counterexamples():
    assert evaluate_lesson("x",[True],provenance=("e",),counterexample_checked=True).disposition=="HYPOTHESIS_ONLY"
    assert evaluate_lesson("x",[True]*3,provenance=("e",),counterexample_checked=True).disposition=="STORE"
    assert evaluate_lesson("x",[True,False,True],provenance=("e",),counterexample_checked=True).disposition=="HYPOTHESIS_ONLY"


def test_wrong_user_and_physical_scope_do_not_transfer():
    rows=[claim("owner","accepted",scope="OWNER"),claim("sim","accepted",scope="SIMULATION")]
    assert reconstruct_context("accepted","MEMBER",rows,now=1).selected==()
    assert reconstruct_context("accepted","PHYSICAL",rows,now=1).selected==()
