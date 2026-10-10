"""Actual isolated file reads through existing SDK; never production certification."""
import hashlib
import json

import pytest

from app.agent_registry import registered_agent_ids, RegistryError
from app.connector_sdk import ConnectorRegistry, Sink
from app.deterministic_ops import DeterministicOps
from app.action_records import ActionLedger


@pytest.fixture
def library(tmp_path, monkeypatch):
    import app.action_records as records
    ledger = ActionLedger(tmp_path / 'actual-actions.jsonl')
    monkeypatch.setattr(records, 'action_ledger', lambda: ledger)
    context = tmp_path / 'context'
    context.mkdir()
    content = b'{"observation":"isolated test data; no live status"}'
    (context / 'input.json').write_bytes(content)
    ops = DeterministicOps(source_version='isolated-tool-library-test')
    def read(payload):
        raw, digest = ops.retrieve_file(context, payload['relative'])
        return {'sha256': digest, 'length': len(raw)}
    catalog = ConnectorRegistry()
    catalog.register_tool('provided_context.read', '1.0.0',
        Sink('provided-context', 'provided_context.read', 'R0', 'bounded local read',
             True, 'LOCAL_ONLY', 'provided_context.read'), read)
    yield catalog, ledger, content
    assert ledger.close()


def rows(ledger):
    assert ledger.flush()
    return [json.loads(line) for line in ledger.path.read_text(encoding='utf-8').splitlines()]


def test_all_21_canonical_actors_use_real_read_handler_and_original_audit(library):
    catalog, ledger, content = library
    actors = sorted(registered_agent_ids(include_orchestrator=False))
    assert len(actors) == 21
    for actor in actors:
        discovery = catalog.discover_for_agent(actor)
        assert [x['tool_id'] for x in discovery['tools']] == ['provided_context.read']
        result = catalog.execute_for_agent('provided_context.read', '1.0.0',
            {'relative': 'input.json'}, task_id=f'isolated-{actor}', agent_id=actor)
        assert result == {'sha256': hashlib.sha256(content).hexdigest(), 'length': len(content)}
    original = rows(ledger)
    assert len(original) == 42
    assert {r['agent_id'] for r in original} == set(actors)
    assert len({r['action_id'] for r in original}) == 21
    assert all(r['success'] for r in original if r['phase'] == 'completed')
    for row in original:
        assert row['parameters_summary']['tool_id'] == 'provided_context.read'
        assert row['parameters_summary']['tool_version'] == '1.0.0'
        assert row['parameters_summary']['catalog_sha256'] == catalog.discover_for_agent(row['agent_id'])['catalog_sha256']
    previous = '0' * 64
    for sequence, row in enumerate(original, 1):
        body = dict(row)
        digest = body.pop('sha256')
        assert body['sequence'] == sequence and body['previous_sha256'] == previous
        raw = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        assert hashlib.sha256(raw).hexdigest() == digest
        previous = digest


def test_unowned_tool_never_invokes_handler_and_denial_is_audited(library):
    catalog, ledger, _ = library
    calls = []
    catalog.register_tool('artifact.create', '1.0.0',
        Sink('artifact-factory', 'artifact.create', 'R1', 'task artifact', True,
             'LOCAL_ONLY', 'artifact.create'), lambda payload: calls.append(payload))
    assert 'artifact.create' not in [x['tool_id'] for x in catalog.discover_for_agent('a01')['tools']]
    with pytest.raises(PermissionError):
        catalog.execute_for_agent('artifact.create', '1.0.0', {}, task_id='denied', agent_id='a01')
    assert calls == []
    original = rows(ledger)
    assert original[-1]['success'] is False
    assert original[-1]['action_type'] == 'tool.access.denied'


@pytest.mark.parametrize('tool,version', [('invented', '1.0.0'), ('provided_context.read', '9.0.0')])
def test_unknown_or_stale_binding_fails_closed(library, tool, version):
    catalog, ledger, _ = library
    with pytest.raises(PermissionError):
        catalog.execute_for_agent(tool, version, {}, task_id='stale', agent_id='a01')
    assert rows(ledger)[-1]['success'] is False


@pytest.mark.parametrize('actor', ['invented-agent', 'coding', 'A12', 'prime'])
def test_alias_and_orchestrator_cannot_impersonate_registered_actor(library, actor):
    catalog, _, _ = library
    with pytest.raises(RegistryError):
        catalog.discover_for_agent(actor)
    with pytest.raises(RegistryError):
        catalog.execute_for_agent('provided_context.read', '1.0.0', {}, task_id='invalid', agent_id=actor)


@pytest.mark.parametrize('relative,error', [('../outside.json', ValueError), ('missing.json', FileNotFoundError)])
def test_real_handler_errors_preserve_observation_and_do_not_fabricate_result(library, relative, error):
    catalog, ledger, _ = library
    with pytest.raises(error):
        catalog.execute_for_agent('provided_context.read', '1.0.0', {'relative': relative},
                                  task_id='handler-failure', agent_id='a01')
    assert rows(ledger)[-1]['success'] is False


def test_registration_cannot_replace_handler_or_grant_new_eligibility(library):
    catalog, _, _ = library
    sink = Sink('test', 'read', 'R0', 'read', True, 'LOCAL_ONLY', 'provided_context.read')
    before = catalog.discover_for_agent('a01')
    with pytest.raises(ValueError):
        catalog.register_tool('provided_context.read', '2.0.0', sink, lambda p: None)
    with pytest.raises(ValueError):
        catalog.register_tool('security.override', '1.0.0', sink, lambda p: None)
    assert catalog.discover_for_agent('a01') == before


def test_protected_sink_controls_still_apply_to_eligible_actor(library):
    catalog, ledger, _ = library
    calls = []
    catalog.register_tool('artifact.create', '1.0.0',
        Sink('protected-test', 'publish', 'consequential', 'external publication', False,
             'PUBLIC', 'artifact.create', operation_tags=frozenset({'public_publication'})),
        lambda payload: calls.append(payload))
    assert 'artifact.create' in [x['tool_id'] for x in catalog.discover_for_agent('a09')['tools']]
    with pytest.raises(PermissionError):
        catalog.execute_for_agent('artifact.create', '1.0.0', {}, task_id='no-publication-authority', agent_id='a09')
    assert calls == []
    denied = rows(ledger)[-1]
    assert denied['success'] is False
    assert denied['parameters_summary']['tool_id'] == 'artifact.create'
    assert denied['parameters_summary']['tool_version'] == '1.0.0'
