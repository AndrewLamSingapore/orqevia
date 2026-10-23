from app.objective_api import select_capabilities
from app.agent_dispatch_api import user_facing_contract
from app.compute_catalog import Tier, task_tier


def test_automatic_objective_routing_defaults_to_one_agent():
    objective = (
        "Create a project plan, analyze cost metrics, design the architecture, "
        "test the implementation, and assess release risk."
    )
    assert len(select_capabilities(objective)) == 1


def test_automatic_objective_routing_has_a_bounded_default():
    assert select_capabilities("A simple request with no routing keyword") == ["responsibility.a02"]


def test_explicit_bounded_reply_uses_fast_local_tier():
    assert task_tier("Reply with exactly READY. Add no other text.") == Tier.NANO
    assert task_tier("Return only the word OK.") == Tier.NANO


def test_default_prompt_limits_unrequested_verbosity():
    contract = user_facing_contract("Create a concise three-step workshop plan.")
    assert "Default to at most 250 words" in contract
