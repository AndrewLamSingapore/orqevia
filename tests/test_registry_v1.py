import hashlib
import json

import pytest

from app import agent_registry as registry
from app.agent_runtime import AgentAuthorityError, AgentAuthorityRuntime


def test_every_historical_responsibility_is_preserved_verbatim_once():
    path = registry.REGISTRY_PATH.parent.parent/'tests'/'fixtures'/'historical-agent-registry-29.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == registry.MIGRATION['historical_sha256']
    old = json.loads(path.read_text())
    records = {r['id']: (a['id'], r) for a in registry.load_agent_registry()['agents'] for r in a['responsibilities']}
    assert len(records) == len(old['agents']) == 29
    for agent in old['agents']:
        capability = 'responsibility.' + agent['agent_id']
        owner, responsibility = records[capability]
        assert responsibility['description'] == agent['role']
        assert responsibility['input'] == agent['receives']
        assert responsibility['output'] == agent['produces']
        assert registry.responsibility_owner(capability) == owner
        assert registry.canonical_agent_id(agent['agent_id']) == owner


@pytest.mark.parametrize('domain,intent,expected', [
    ('economic','commercial market business',['a20']),
    ('quality','critic critique challenge',['a26']),
    ('quality','verification audit complete',['a15','a18']),
    ('economic','resource capacity allocation',['a01','a05']),
    ('research','compare comparison versus',['a01','a04']),
])
def test_consolidated_responsibility_reaches_its_owner(tmp_path, domain, intent, expected):
    runtime = AgentAuthorityRuntime(tmp_path/'authority.db')
    path = runtime.resolve_path(domain,intent)
    assert path == expected
    runtime.begin_path(path)
    events = list(reversed(runtime.recent()))
    assert [event['target_agent'] for event in events] == expected


def test_all_canonical_paths_are_valid_and_unrelated_delegation_is_denied(tmp_path):
    runtime = AgentAuthorityRuntime(tmp_path/'authority.db')
    for agent in registry.load_agent_registry()['agents']:
        path = [agent['id']] if agent['can_delegate'] else [agent['reports_to'],agent['id']]
        runtime.begin_path(path)
        assert agent['tap_relationship']['delegation_transfers_authority'] is False
        assert agent['compute_requirements']['dedicated_model'] is False
    with pytest.raises(AgentAuthorityError):
        runtime.begin_path(['a26','a18'])
    with pytest.raises(AgentAuthorityError):
        runtime.begin_path(['a17'])
    with pytest.raises(registry.RegistryError):
        registry.responsibility_owner('invented.capability')
