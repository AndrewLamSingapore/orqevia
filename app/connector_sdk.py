"""Connector discovery and observed execution; historical adapter retained."""
from dataclasses import dataclass
import hashlib
import json
from typing import Callable



@dataclass(frozen=True)
class Sink:
    connector_id: str
    action_id: str
    authority_class: str
    side_effects: str
    reversible: bool
    data_classification: str
    required_capability: str
    credentials_required: bool = False
    failsafe: str = 'deny'
    evidence: str = 'asynchronous actual execution record'
    revocation: str = 'classification is metadata; operational cancellation where supported'
    operation_tags: frozenset[str] = frozenset()


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class LegacyConnectorRegistry:
    def __init__(self):
        self._sinks = {}

    def register(self, sink: Sink, handler: Callable[[dict],dict]):
        key=(sink.connector_id,sink.action_id)
        if key in self._sinks or sink.authority_class not in {'R0','R1','consequential'} or sink.failsafe!='deny':
            raise ValueError('Invalid or duplicate sink registration')
        self._sinks[key]=(sink,handler)

    def execute(self, harness, envelope: dict, payload: dict) -> dict:
        from .action_harness import HarnessedExecutor
        parameters=envelope.get('parameters',{})
        key=(parameters.get('connector_id'),envelope.get('action'))
        if key not in self._sinks:
            raise PermissionError('Unknown connector sink')
        sink,handler=self._sinks[key]
        if parameters.get('payload_sha256')!=payload_digest(payload):
            raise PermissionError('Connector payload does not match signed authority')
        if parameters.get('capability')!=sink.required_capability:
            raise PermissionError('Wrong connector capability')
        if sink.authority_class=='consequential' and not envelope.get('authorization',{}).get('owner_approval_id'):
            raise PermissionError('Consequential sink requires owner authority')
        return HarnessedExecutor(harness,lambda signed:handler(payload)).execute(envelope)


class ConnectorRegistry:
    """Discovery and dispatch, with classification as descriptive metadata only."""
    def __init__(self, *, sink_guard=None):
        from .sink_guard import SinkGuard
        self._sinks={}
        self._guard=sink_guard if sink_guard is not None else SinkGuard()

    def register(self,sink: Sink,handler: Callable):
        from .sink_guard import PROTECTED
        if not isinstance(sink.operation_tags, frozenset) or sink.operation_tags - PROTECTED:
            raise ValueError('Explicit immutable consequence tags required')
        key=(sink.connector_id,sink.action_id)
        if key in self._sinks:raise ValueError('Duplicate connector action')
        self._sinks[key]=(sink,handler)

    def execute(self,connector_id,action_id,payload,*,task_id,agent_id,classification=None):
        from .action_records import ActionRecord,DirectExecutor,action_ledger
        try:sink,handler=self._sinks[(connector_id,action_id)]
        except KeyError:raise LookupError('Connector action unavailable') from None
        self._guard.check(sink,payload,task_id=task_id,agent_id=agent_id)
        try:summary={'payload_sha256':payload_digest(payload)}
        except Exception:summary={'payload_summary':'unavailable'}
        record=ActionRecord(task_id,agent_id,action_id,connector_id,
            classification=classification or sink.authority_class,
            parameters_summary=summary)
        return DirectExecutor(action_ledger()).execute(record,lambda:handler(payload))
