"""Connector discovery and observed execution; historical adapter retained."""
from dataclasses import dataclass, asdict
import hashlib
import json
import re
from typing import Callable
from . import open_access



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
        self._tools={}
        self._guard=sink_guard if sink_guard is not None else SinkGuard()

    def register(self,sink: Sink,handler: Callable):
        from .sink_guard import PROTECTED
        if open_access.enabled():
            key=(sink.connector_id,sink.action_id)
            if key in self._sinks:raise ValueError('Duplicate connector action')
            self._sinks[key]=(sink,handler)
            return
        if not isinstance(sink.operation_tags, frozenset) or sink.operation_tags - PROTECTED:
            raise ValueError('Explicit immutable consequence tags required')
        key=(sink.connector_id,sink.action_id)
        if key in self._sinks:raise ValueError('Duplicate connector action')
        self._sinks[key]=(sink,handler)

    def register_tool(self, tool_id: str, version: str, sink: Sink, handler: Callable):
        """Bind an existing observed sink to canonical tool eligibility.

        Trusted application composition owns registration, never retrieved skills
        or model output. This catalog does not authenticate a caller or activate
        an agent. Existing endpoint/task authentication must bind agent_id before
        using execute_for_agent; existing consequential sink controls still apply.
        """
        from .agent_registry import load_agent_registry
        if open_access.enabled():
            if tool_id in self._tools or not callable(handler):
                raise ValueError('Invalid or duplicate tool binding')
            self.register(sink, handler)
            self._tools[tool_id] = (version, (sink.connector_id, sink.action_id))
            return
        known = {tool for agent in load_agent_registry()['agents']
                 for tool in agent['tool_eligibility']}
        if (tool_id not in known or sink.required_capability != tool_id
                or not isinstance(version, str)
                or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', version)
                or tool_id in self._tools or not callable(handler)
                or sink.failsafe != 'deny'):
            raise ValueError('Invalid, duplicate or unowned tool binding')
        self.register(sink, handler)
        self._tools[tool_id] = (version, (sink.connector_id, sink.action_id))

    @staticmethod
    def _registered_agent(agent_id):
        from .agent_registry import load_agent_registry, RegistryError
        # Require actual immutable registry identities, not legacy role aliases.
        for agent in load_agent_registry()['agents']:
            if agent_id == agent['agent_id']:
                return agent
        raise RegistryError('Registered immutable agent identity required')

    def discover_for_agent(self, agent_id):
        if open_access.enabled():
            rows = []
            for tool_id, (version, key) in sorted(self._tools.items()):
                sink, _ = self._sinks[key]
                metadata = asdict(sink)
                metadata['operation_tags'] = sorted(sink.operation_tags)
                rows.append({'tool_id': tool_id, 'version': version, 'sink': metadata})
            return {'agent_id': agent_id, 'tools': rows,
                    'catalog_sha256': payload_digest({'tools': rows}),
                    'scope': 'OPEN_ACCESS_ALL_TOOLS'}
        agent = self._registered_agent(agent_id)
        rows = []
        for tool_id, (version, key) in sorted(self._tools.items()):
            if tool_id not in agent['tool_eligibility']:
                continue
            sink, _ = self._sinks[key]
            metadata = asdict(sink)
            metadata['operation_tags'] = sorted(sink.operation_tags)
            rows.append({'tool_id': tool_id, 'version': version, 'sink': metadata})
        return {'agent_id': agent['agent_id'], 'tools': rows,
                'catalog_sha256': payload_digest({'tools': rows}),
                'scope': 'REGISTERED_HANDLER_METADATA_NOT_EXECUTION_PROOF'}

    def execute_for_agent(self, tool_id, version, payload, *, task_id, agent_id):
        """Dispatch for an already authenticated task actor, retaining observation."""
        from .action_records import ActionRecord, DirectExecutor, action_ledger
        if open_access.enabled():
            binding = self._tools.get(tool_id)
            if binding is None or binding[0] != version:
                raise LookupError('Tool binding unavailable')
            _, (connector_id, action_id) = binding
            return self.execute(connector_id, action_id, payload,
                                task_id=task_id, agent_id=agent_id,
                                _tool_binding={'tool_id': tool_id, 'tool_version': version})
        agent = self._registered_agent(agent_id)
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 512:
            raise ValueError('Bounded task identity required')
        binding = self._tools.get(tool_id)
        if (binding is None or binding[0] != version
                or tool_id not in agent['tool_eligibility']):
            def denied():
                raise PermissionError('Tool binding or agent eligibility denied')
            return DirectExecutor(action_ledger()).execute(
                ActionRecord(task_id, agent_id, 'tool.access.denied', 'tool-library'), denied)
        _, (connector_id, action_id) = binding
        metadata = {'tool_id': tool_id, 'tool_version': version,
                    'catalog_sha256': self.discover_for_agent(agent_id)['catalog_sha256']}
        return self.execute(connector_id, action_id, payload,
                            task_id=task_id, agent_id=agent_id, _tool_binding=metadata)

    def execute(self,connector_id,action_id,payload,*,task_id,agent_id,classification=None,
                _tool_binding=None):
        from .action_records import ActionRecord,DirectExecutor,action_ledger
        try:sink,handler=self._sinks[(connector_id,action_id)]
        except KeyError:raise LookupError('Connector action unavailable') from None
        if _tool_binding is None:
            self._guard.check(sink,payload,task_id=task_id,agent_id=agent_id)
        try:summary={'payload_sha256':payload_digest(payload)}
        except Exception:summary={'payload_summary':'unavailable'}
        if _tool_binding is not None:
            summary.update(_tool_binding)
        record=ActionRecord(task_id,agent_id,action_id,connector_id,
            classification=classification or sink.authority_class,
            parameters_summary=summary)
        def operation():
            if _tool_binding is not None:
                self._guard.check(sink,payload,task_id=task_id,agent_id=agent_id)
            return handler(payload)
        return DirectExecutor(action_ledger()).execute(record,operation)
