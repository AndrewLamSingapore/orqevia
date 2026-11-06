"""Lazy shared capability services; observing events cannot create a control plane."""
from threading import RLock

_lock = RLock()
_services = {}


def __getattr__(name):
    if name not in {'memory', 'ledger', 'authority', 'gateway', 'orchestrator', 'events', 'multi'}:
        raise AttributeError(name)
    with _lock:
        if name in _services:
            return _services[name]
        if name == 'memory':
            from .memory import MemoryStore
            value = MemoryStore()
        elif name == 'ledger':
            from .compute_ledger import ComputeLedger
            value = ComputeLedger()
        elif name == 'authority':
            from .agent_runtime import AgentAuthorityRuntime
            value = AgentAuthorityRuntime()
        elif name == 'gateway':
            from .model_gateway import ModelGateway
            value = ModelGateway(ledger=__getattr__('ledger'))
        elif name == 'events':
            from .event_fabric import EventFabric
            value = EventFabric(memory=__getattr__('memory'))
        elif name == 'multi':
            from .multi_specialist import MultiSpecialistRuntime
            value = MultiSpecialistRuntime(gateway=__getattr__('gateway'), authority_runtime=__getattr__('authority'))
        else:
            from .cognitive_orchestrator import CognitiveOrchestrator
            value = CognitiveOrchestrator(memory=__getattr__('memory'), gateway=__getattr__('gateway'),
                                          authority_runtime=__getattr__('authority'))
        _services[name] = value
        return value
