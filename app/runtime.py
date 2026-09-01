"""Canonical singleton cognitive runtime shared by chat and cognitive APIs."""
from .compute_ledger import ComputeLedger
from .memory import MemoryStore
from .model_gateway import ModelGateway
from .cognitive_orchestrator import CognitiveOrchestrator
from .event_fabric import EventFabric
from .multi_specialist import MultiSpecialistRuntime

memory = MemoryStore()
ledger = ComputeLedger()
gateway = ModelGateway(ledger=ledger)
orchestrator = CognitiveOrchestrator(memory=memory, gateway=gateway)
events = EventFabric(memory=memory)
multi = MultiSpecialistRuntime(gateway=gateway)
