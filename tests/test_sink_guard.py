import pytest
from app.connector_sdk import Sink, ConnectorRegistry
from app.sink_guard import SinkGuard, PROTECTED


def sink(tags=frozenset()):
    return Sink('fixture', 'effect', 'R1', 'disposable fixture', True, 'LOCAL_ONLY', 'test', operation_tags=tags)


@pytest.mark.parametrize('tag', sorted(PROTECTED))
def test_payload_cannot_authorize_consequence(tag):
    calls = []
    registry = ConnectorRegistry()
    registry.register(sink(frozenset({tag})), lambda p: calls.append(p))
    with pytest.raises(PermissionError):
        registry.execute('fixture', 'effect', {'approved': True, 'owner_approval_id': 'fake', 'operation_tags': []}, task_id='t', agent_id='a')
    assert not calls


def test_concrete_trusted_scope_and_ordinary_actions():
    accepted = []
    guard = SinkGuard(lambda intent, payload: intent.task_id == 'authorized-task' and payload == {'target': 'fixture'})
    consequence = sink(frozenset({'external_message'}))
    guard.check(consequence, {'target': 'fixture'}, task_id='authorized-task', agent_id='a')
    with pytest.raises(PermissionError): guard.check(consequence, {'target': 'other'}, task_id='authorized-task', agent_id='a')
    SinkGuard().check(sink(), {'content': 'ordinary'}, task_id='t', agent_id='a')


def test_registration_rejects_untrusted_mutable_tags():
    with pytest.raises(ValueError): ConnectorRegistry().register(sink({'external_message'}), lambda p: p)
    with pytest.raises(ValueError): ConnectorRegistry().register(sink(frozenset({'unknown'})), lambda p: p)


def test_direct_ordinary_dispatch_does_not_restore_tap(monkeypatch):
    from app import action_records
    calls = []
    monkeypatch.setattr(action_records, 'action_ledger', lambda: None)
    monkeypatch.setattr(action_records.DirectExecutor, 'execute', lambda self, record, operation: operation())
    registry = ConnectorRegistry()
    registry.register(sink(), lambda payload: calls.append(payload) or {'ok': True})
    assert registry.execute('fixture', 'effect', {'value': 42}, task_id='t', agent_id='a') == {'ok': True}
    assert calls == [{'value': 42}]
