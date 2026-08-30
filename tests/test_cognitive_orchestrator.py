from app.cognitive_orchestrator import CognitiveOrchestrator
from app.memory import MemoryStore


class FakePortal:
    def query(self, query: str, limit: int = 8):
        return [{"score": 2, "node": {"title": "Relevant external artifact", "type": "artifact"}}]


def seeded_memory(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    store.record_episode(event_type="decision", content={"summary": "Use Stable Spine for governed actions"}, source="test", salience=0.9, durable_kind="decision", durable_key="stable-spine")
    store.consolidate()
    return store


def test_memory_search_returns_grounded_durable_item(tmp_path):
    store = seeded_memory(tmp_path)
    results = store.search("stable spine governed actions")
    assert results
    assert results[0]["memory_kind"] == "decision"
    assert results[0]["memory_key"] == "stable-spine"
    assert results[0]["retrieval_score"] > 0


def test_plan_combines_memory_and_portal_without_execution(tmp_path):
    engine = CognitiveOrchestrator(memory=seeded_memory(tmp_path), portal=FakePortal())
    plan = engine.plan(intent="Review the Stable Spine architecture and research improvements", department="research")
    assert plan.specialist == "research"
    assert plan.memory_context
    assert plan.portal_context
    assert plan.needs_approval is False
    assert plan.proposed_action is None
    assert plan.confidence == "strong"


def test_consequential_intent_stops_at_proposal(tmp_path):
    engine = CognitiveOrchestrator(memory=seeded_memory(tmp_path), portal=FakePortal())
    plan = engine.plan(intent="Send email with the final decision", department="strategy")
    assert plan.needs_approval is True
    assert plan.proposed_action is not None
    assert plan.proposed_action["action"] == "external.action.proposal"
