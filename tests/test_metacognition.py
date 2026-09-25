import pytest

from app.metacognition import (Belief, ControlState, EpistemicState, Evidence, Hypothesis,
                               Strategy, assess, brier_score,
                               compete_hypotheses, decompose_uncertainty,
                               expected_calibration_error, revise,
                               select_strategy, should_stop)


def ev(i, supports=True, kind="deterministic_tool", **kw):
    return Evidence(i, "p", supports, kind, 1, **kw)


def test_unknown_without_evidence_and_no_authority():
    result = assess("p", [])
    assert result.state == EpistemicState.UNKNOWN
    assert result.confidence == 0
    assert not result.grants_authority and not result.may_trigger_consequential_tool


def test_model_assertion_is_only_inference():
    result = assess("p", [ev("m", kind="model_inference")])
    assert result.state == EpistemicState.INFERENCE
    assert result.confidence < .5


def test_verified_requires_authoritative_independent_high_quality_evidence():
    result = assess("p", [ev("x", authoritative=True, independently_verified=True)])
    assert result.state == EpistemicState.VERIFIED_FACT
    assert result.evidence_ids == ("x",)


def test_primary_record_alone_is_supported_not_verified():
    assert assess("p", [ev("r", kind="primary_record")]).state == EpistemicState.SUPPORTED_FACT


def test_contradiction_is_preserved_not_arbitrarily_resolved():
    result = assess("p", [ev("yes"), ev("no", False)])
    assert result.state == EpistemicState.CONTRADICTED
    assert result.evidence_ids == ("yes",) and result.counterevidence_ids == ("no",)
    assert "contradiction_requires_discriminating_evidence" in result.unknowns


def test_verbose_unsupported_assertion_has_zero_weight():
    result = assess("p", [ev("verbose", kind="unsupported_assertion")])
    assert result.state == EpistemicState.UNKNOWN and result.confidence == 0


def test_strategy_uses_expected_information_gain_per_cost():
    strategies = [Strategy("cheap", frozenset(), .5, .2), Strategy("big", frozenset(), .9, .8)]
    assert select_strategy(strategies, set(), 1).name == "cheap"


def test_strategy_respects_capability_budget_availability_and_failure():
    strategies = [Strategy("retrieval", frozenset({"net"}), .9, .2),
                  Strategy("compute", frozenset({"cpu"}), .7, .3),
                  Strategy("blocked", frozenset(), 1, .1, False)]
    assert select_strategy(strategies, {"cpu"}, .5, {"retrieval"}).name == "compute"
    assert select_strategy(strategies, set(), .05) is None


def test_reasoning_loop_stops_after_repeated_no_information():
    state = ControlState("x", observations=["same"] * 3)
    assert should_stop(state) == (True, "NO_NEW_INFORMATION")


def test_reasoning_budget_is_bounded():
    state = ControlState("x", iterations=8)
    assert should_stop(state) == (True, "BOUNDED_REASONING_LIMIT")


@pytest.mark.parametrize("disposition", ["VERIFIED", "ABSTAIN", "VERIFY_REQUIRED", "DEFERRED"])
def test_terminal_dispositions_stop(disposition):
    assert should_stop(ControlState("x", disposition=disposition))[0]


def test_revision_drops_stale_conclusion_without_current_evidence():
    previous = Belief("p", EpistemicState.VERIFIED_FACT, 1)
    revised = revise(previous, [])
    assert revised.state == EpistemicState.UNKNOWN
    assert "prior_conclusion_not_carried_without_current_evidence" in revised.unknowns


def test_revision_admits_prior_conclusion_wrong():
    previous = Belief("p", EpistemicState.SUPPORTED_FACT, .8)
    revised = revise(previous, [ev("counter", False)])
    assert revised.state == EpistemicState.CONTRADICTED
    assert revised.counterevidence_ids == ("counter",)


def test_brier_and_ece_are_measured():
    rows = [(1, True), (.8, True), (.2, False), (0, False)]
    assert brier_score(rows) == .02
    assert expected_calibration_error(rows, 5) == .1


@pytest.mark.parametrize("rows", [[], [(float("nan"), True)], [(1.1, True)]])
def test_calibration_rejects_invalid_input(rows):
    with pytest.raises(ValueError):
        brier_score(rows)


def test_conclusion_never_creates_authority_even_when_verified():
    result = assess("p", [ev("x", authoritative=True, independently_verified=True)])
    assert result.state == EpistemicState.VERIFIED_FACT
    assert result.grants_authority is False
    assert result.may_trigger_consequential_tool is False


def test_uncertainty_decomposition_is_explicit_and_sparse():
    assert decompose_uncertainty(conflicting_evidence=True, causal_ambiguity=True) == (
        "conflicting_evidence", "causal_ambiguity")


def test_hypotheses_compete_without_winner_becoming_fact():
    evidence = [ev("supports-a"), ev("against-a", False), ev("supports-b", kind="primary_record")]
    ranked = compete_hypotheses([
        Hypothesis("a", "cause a", .7, ("supports-a",), ("against-a",)),
        Hypothesis("b", "cause b", .4, ("supports-b",)),
        Hypothesis("c", "cause c", .3),
    ], evidence)
    assert {x.status for x in ranked} == {"CONTRADICTED", "SUPPORTED", "HYPOTHESIS"}
    assert all(x.status != "VERIFIED" for x in ranked)
    assert next(x for x in ranked if x.hypothesis_id == "a").discriminating_evidence_required


def test_hypothesis_prior_rejects_false_precision():
    with pytest.raises(ValueError):
        compete_hypotheses([Hypothesis("x", "x", float("nan"))], [])
