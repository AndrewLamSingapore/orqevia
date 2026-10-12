"""Actual objective routing with synthetic insufficient-tier local inventory."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from tests.test_agent_cert_authority_chain import configured, runtime, TOKEN
from app import agent_dispatch_api as dispatch
from app.agent_cert_role_review import canonical_case_spec
from app.tier_router import Backend, Tier


@pytest.mark.parametrize('case', ['role:difficult', 'role:edge', 'role:invalid_input', 'role:failure'])
def test_insufficient_local_tiers_never_enqueue_flagship_role_cases(runtime, monkeypatch, case):
    from app import compute_queue_api, compute_catalog
    local = (Backend('ollama-fast', 'gemma3:1b', Tier.NANO, 'local'),
             Backend('ollama-deep', 'gemma3:4b', Tier.MINI, 'local'))
    monkeypatch.setattr(compute_catalog, 'load_catalog', lambda: [])
    monkeypatch.setattr(dispatch, 'local_model_backends', lambda: local)
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: [
        SimpleNamespace(name='ollama-fast'), SimpleNamespace(name='ollama-deep'),
        SimpleNamespace(name='ollama-embedding')])
    monkeypatch.setattr(compute_queue_api.queue, 'submit',
                        lambda **kw: pytest.fail('Insufficient tier must not enqueue inference'),
                        raising=False)
    spec = canonical_case_spec('a19', 'responsibility.a19', case)
    assert spec['request']['task_class'] == 'complex_reasoning'
    reply = runtime.client.post('/api/agents/objectives', json=spec['request'],
                                headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 202
    assert reply.json()['steps'] == [{'capability': 'responsibility.a19',
                                     'state': 'blocked', 'reason': 'STEP_DISPATCH_FAILED'}]
    db = sqlite3.connect((runtime.root / 'objectives.db').as_uri() + '?mode=ro', uri=True)
    try:
        row = db.execute('SELECT steps_json FROM objectives WHERE id=?', (reply.json()['id'],)).fetchone()
    finally:
        db.close()
    assert json.loads(row[0])[0]['reason'] == {
        'state': 'UNAVAILABLE', 'reason': 'No available backend satisfies tier and data residency'}
