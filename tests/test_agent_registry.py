from copy import deepcopy
import json

import pytest

from app import agent_registry as registry


def test_all_existing_capabilities_and_one_native_coordinator_are_retained():
    data = registry.load_agent_registry()
    assert len(data['agents']) == 21
    assert data['orchestrator']['id'] == 'orqevia'
    assert len([r for a in data['agents'] for r in a['responsibilities']]) == 29
    assert 'leads' not in data
    assert all(not {'reports_to', 'can_delegate', 'allowed_delegation_targets', 'escalation_relationships'} & a.keys() for a in data['agents'])


def test_all_distinct_owned_capabilities_can_coordinate_without_hierarchy():
    ids = registry.registered_agent_ids(include_orchestrator=False)
    for source in ids | {'orqevia'}:
        for target in ids:
            assert registry.may_delegate(source, target) is (source != target)
            assert registry.may_consult(source, target) is (source != target)
    assert registry.may_delegate('a02', 'a17', depth=3)
    assert not registry.may_delegate('invented', 'a17')
    assert not registry.may_delegate('a17', 'invented')
    assert not registry.may_delegate('a17', 'a17')
    assert not registry.may_delegate('a17', 'orqevia')
    assert not registry.may_delegate('a17', 'a18', depth=0)
    assert not registry.may_consult('a17', 'invented')


def test_unknown_agents_fail_closed_and_historical_aliases_only_resolve_identity():
    assert registry.canonical_agent_id('engineering') == 'a15'
    assert registry.canonical_agent_id('critic') == 'a26'
    assert registry.canonical_agent_id('A17') == 'a16'
    assert registry.agent_record('A17')['name'] == 'Architecture Agent'
    assert registry.domain_lead('data') == 'a10'
    assert registry.canonical_agent_id('lead_engineering') == 'a15'
    assert registry.canonical_agent_id('prime') == 'orqevia'
    for retired in ['A10', 'A24', 'A29', 'gap', 'asset', 'policy', 'invented-agent']:
        with pytest.raises(registry.RegistryError):
            registry.canonical_agent_id(retired)


def test_consequential_action_always_requires_owner_approval():
    assert registry.requires_owner_approval(consequential=True) is True
    assert registry.requires_owner_approval(consequential=False) is False
    for agent in registry.load_agent_registry()['agents']:
        assert agent['tap_relationship']['delegation_transfers_authority'] is False
        if agent['authority'] == 'restricted':
            assert agent['human_approval'] == 'required_for_execution'


def test_public_projection_remains_deny_by_default_without_invented_reporting_edges():
    public = registry.public_agent_registry()
    assert public['relationship_policy']['unknown_agent_policy'] == 'deny'
    assert public['relationship_policy']['delegation_transfers_authority'] is False
    assert public['relationship_policy']['runtime_activation_verified'] is False
    assert public['relationships'] == []
    forbidden = {'system_prompt', 'credentials', 'endpoint', 'filesystem_path', 'tool_secrets', 'internal_instructions', 'reports_to'}
    assert all(not forbidden.intersection(agent) for agent in public['agents'])


@pytest.mark.parametrize('mutation', ['duplicate', 'hierarchy', 'approval', 'identity', 'ownership', 'authority'])
def test_mutated_identity_and_permission_declarations_fail_closed(mutation):
    data = json.loads(registry.REGISTRY_PATH.read_text())
    if mutation == 'duplicate':
        data['agents'][1]['agent_id'] = data['agents'][0]['agent_id']
    elif mutation == 'hierarchy':
        data['agents'][1]['can_delegate'] = True
    elif mutation == 'approval':
        next(a for a in data['agents'] if a['authority'] == 'restricted')['human_approval'] = 'not_required'
    elif mutation == 'identity':
        data['agents'][0]['immutable_id'] = 'invented'
    elif mutation == 'ownership':
        data['responsibility_coverage'][0]['owner'] = 'a17'
    else:
        data['agents'][0]['authority'] = 'unrestricted'
    with pytest.raises(registry.RegistryError):
        registry.normalize_registry(data)


def test_capability_record_callers_cannot_mutate_cached_permissions():
    before = deepcopy(registry.agent_record('a17'))
    exposed = registry.agent_record('a17')
    exposed['tool_eligibility'].append('wallet.transfer')
    exposed['authority'] = 'unrestricted'
    assert registry.agent_record('a17') == before


def test_duplicate_json_fields_fail_closed(tmp_path, monkeypatch):
    raw = registry.REGISTRY_PATH.read_text().replace('"schema_version": "3.0"', '"schema_version": "2.0", "schema_version": "3.0"', 1)
    path = tmp_path/'duplicate.json'
    path.write_text(raw)
    with monkeypatch.context() as patch:
        patch.setattr(registry, 'REGISTRY_PATH', path)
        registry.load_agent_registry.cache_clear()
        with pytest.raises(registry.RegistryError, match='duplicate'):
            registry.load_agent_registry()
    registry.load_agent_registry.cache_clear()
