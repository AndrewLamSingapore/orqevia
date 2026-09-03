from app.agent_registry import (
    load_agent_registry,
    may_consult,
    may_delegate,
    public_agent_registry,
    requires_owner_approval,
)


def test_registry_has_exactly_29_agents_and_one_root():
    data = load_agent_registry()
    assert len(data["agents"]) == 29
    assert data["orchestrator"]["id"] == "prime"


def test_delegation_is_direct_lead_to_child_only():
    assert may_delegate("A01", "A02") is True
    assert may_delegate("A01", "A06") is False
    assert may_delegate("A02", "A03") is False
    assert may_delegate("A01", "A02", depth=2) is False


def test_consultation_is_bounded():
    assert may_consult("A02", "A01") is True
    assert may_consult("A01", "A06") is True
    assert may_consult("A02", "A07") is False


def test_consequential_action_always_requires_owner_approval():
    assert requires_owner_approval(consequential=True) is True
    assert requires_owner_approval(consequential=False) is False


def test_public_projection_is_deny_by_default():
    public = public_agent_registry()
    assert public["relationship_policy"]["network_is_enforced"] is True
    forbidden = {"system_prompt", "credentials", "endpoint", "filesystem_path", "tool_secrets", "internal_instructions"}
    for agent in public["agents"]:
        assert not forbidden.intersection(agent)
