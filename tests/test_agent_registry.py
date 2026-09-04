import pytest

from app.agent_registry import (
    RegistryError,
    canonical_agent_id,
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


def test_delegation_is_direct_and_bounded():
    assert may_delegate("prime", "A01") is True
    assert may_delegate("prime", "A02") is False
    assert may_delegate("A01", "A02") is True
    assert may_delegate("A01", "A06") is False
    assert may_delegate("A02", "A03") is False
    assert may_delegate("A01", "A02", depth=2) is False


def test_consultation_is_bounded():
    assert may_consult("A02", "A01") is True
    assert may_consult("A01", "A06") is True
    assert may_consult("A02", "A07") is False


def test_unknown_agents_fail_closed_and_aliases_canonicalize():
    assert canonical_agent_id("engineering") == "A16"
    assert canonical_agent_id("critic") == "A27"
    with pytest.raises(RegistryError):
        canonical_agent_id("invented-agent")


def test_consequential_action_always_requires_owner_approval():
    assert requires_owner_approval(consequential=True) is True
    assert requires_owner_approval(consequential=False) is False


def test_public_projection_is_deny_by_default():
    public = public_agent_registry()
    assert public["relationship_policy"]["network_is_enforced"] is True
    assert public["relationship_policy"]["unknown_agent_policy"] == "deny"
    assert {"source": "prime", "target": "A01", "type": "may_delegate"} in public["relationships"]
    forbidden = {"system_prompt", "credentials", "endpoint", "filesystem_path", "tool_secrets", "internal_instructions"}
    for agent in public["agents"]:
        assert not forbidden.intersection(agent)
