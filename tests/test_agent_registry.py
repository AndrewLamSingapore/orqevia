from app.agent_registry import (
    RegistryError,
    canonical_agent_id,
    load_agent_registry,
    may_consult,
    may_delegate,
    public_agent_registry,
    requires_owner_approval,
)


def test_registry_has_exactly_21_agents_and_one_root():
    data = load_agent_registry()
    assert len(data["agents"]) == 21
    assert data["orchestrator"]["id"] == "prime"


def test_delegation_is_direct_and_bounded():
    assert may_delegate("prime", "a01") is True
    assert may_delegate("prime", "a02") is False
    assert may_delegate("a01", "a02") is True
    assert may_delegate("a01", "a06") is False
    assert may_delegate("a02", "a03") is False
    assert may_delegate("a01", "a02", depth=3) is False


def test_consultation_is_bounded():
    assert may_consult("a02", "a01") is True
    assert may_consult("a01", "a06") is True
    assert may_consult("a02", "a07") is False


def test_unknown_agents_fail_closed_and_aliases_canonicalize():
    assert canonical_agent_id("engineering") == "a15"
    assert canonical_agent_id("critic") == "a26"
    try:
        canonical_agent_id("invented-agent")
    except RegistryError:
        pass
    else:
        raise AssertionError("unknown agent identity must fail closed")


def test_consequential_action_always_requires_owner_approval():
    assert requires_owner_approval(consequential=True) is True
    assert requires_owner_approval(consequential=False) is False


def test_public_projection_is_deny_by_default():
    public = public_agent_registry()
    assert public["relationship_policy"]["network_is_enforced"] is True
    assert public["relationship_policy"]["unknown_agent_policy"] == "deny"
    assert {"source": "prime", "target": "a01", "type": "may_delegate"} in public["relationships"]
    forbidden = {"system_prompt", "credentials", "endpoint", "filesystem_path", "tool_secrets", "internal_instructions"}
    for agent in public["agents"]:
        assert not forbidden.intersection(agent)


def test_legacy_migration_preserves_roles_and_denies_removed_identities():
    import pytest
    from app.agent_registry import agent_record, domain_lead
    assert canonical_agent_id('A17') == 'a16'
    assert agent_record('A17')['name'] == 'Architecture Agent'
    assert domain_lead('data') == 'a10'
    assert canonical_agent_id('lead_engineering') == 'a15'
    for retired in ['A10', 'A24', 'A29', 'gap', 'asset', 'policy']:
        with pytest.raises(RegistryError):
            canonical_agent_id(retired)
    assert may_delegate('prime', 'a01', depth=2) is False
    assert may_delegate('a01', 'a02', depth=2) is True
    assert may_delegate('a02', 'a03', depth=2) is False


def test_mutated_authority_and_hierarchy_fail_closed(tmp_path, monkeypatch):
    import json
    import pytest
    import app.agent_registry as registry
    original = json.loads(registry.REGISTRY_PATH.read_text())
    for mutation in ['duplicate', 'cycle', 'delegation', 'approval']:
        data = json.loads(json.dumps(original))
        if mutation == 'duplicate': data['agents'][1]['agent_id'] = 'a01'
        if mutation == 'cycle': data['agents'][1]['reports_to'] = 'a02'
        if mutation == 'delegation': data['agents'][1]['can_delegate'] = True
        if mutation == 'approval': next(a for a in data['agents'] if a['agent_id'] == 'a17')['human_approval'] = 'not_required'
        path = tmp_path / 'registry.json'
        path.write_text(json.dumps(data))
        with monkeypatch.context() as patch:
            patch.setattr(registry, 'REGISTRY_PATH', path)
            registry.load_agent_registry.cache_clear()
            with pytest.raises(RegistryError): registry.load_agent_registry()
        registry.load_agent_registry.cache_clear()
