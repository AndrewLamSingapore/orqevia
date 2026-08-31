from app.routing_policy import ROUTING_SEQUENCE, RoutingPolicy, policy_manifest


def test_sequence_is_frozen_and_manifest_is_non_executing():
    manifest = policy_manifest()
    assert ROUTING_SEQUENCE == ("deterministic", "local_ai", "confidence_gate", "frontier_ai")
    assert manifest["sequence"] == list(ROUTING_SEQUENCE)
    assert manifest["executes_models"] is False
    assert manifest["executes_actions"] is False


def test_deterministic_result_short_circuits_all_models():
    decision = RoutingPolicy().decide(
        deterministic_satisfied=True,
        local_confidence="limited",
        frontier_allowed=True,
        frontier_available=True,
    )
    assert decision.selected_stage == "deterministic"
    assert decision.confidence_gate == "not_required"


def test_strong_local_result_does_not_escalate():
    decision = RoutingPolicy().decide(
        local_confidence="strong",
        frontier_allowed=True,
        frontier_available=True,
    )
    assert decision.selected_stage == "local_ai"
    assert decision.confidence_gate == "pass"


def test_low_confidence_escalates_only_when_allowed_and_available():
    policy = RoutingPolicy()
    escalated = policy.decide(
        local_confidence="partial",
        frontier_allowed=True,
        frontier_available=True,
    )
    held_without_authority = policy.decide(
        local_confidence="partial",
        frontier_allowed=False,
        frontier_available=True,
    )
    held_without_resource = policy.decide(
        local_confidence="limited",
        frontier_allowed=True,
        frontier_available=False,
    )
    assert escalated.selected_stage == "frontier_ai"
    assert held_without_authority.selected_stage == "confidence_hold"
    assert held_without_resource.selected_stage == "confidence_hold"


def test_consequential_work_always_keeps_approval_gate():
    decision = RoutingPolicy().decide(local_confidence="strong", consequential=True)
    assert decision.selected_stage == "local_ai"
    assert decision.approval_required is True
