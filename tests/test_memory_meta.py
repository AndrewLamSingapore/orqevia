from tempfile import NamedTemporaryFile

from app.memory import MemoryStore
from app.meta_review import MetaReviewer
from app.spine import SpineStore, StableSpine


def envelope(action: str, key: str):
    return {
        "tenant_id": "personal", "actor_id": "prime-core", "actor_type": "reasoner",
        "action": action, "parameters": {}, "context": {}, "correlation_id": f"c-{key}",
        "idempotency_key": key, "schema_version": "1", "timestamp": "2026-08-30T00:00:00Z",
    }


def test_memory_promotes_only_explicit_durable_items():
    with NamedTemporaryFile(suffix=".db") as temp:
        memory = MemoryStore(temp.name)
        memory.record_episode(event_type="conversation", content={"fact": "temporary"}, source="test", salience=1)
        memory.record_episode(event_type="decision", content={"choice": "A"}, source="test", salience=0.9, durable_kind="decision", durable_key="project:choice")
        result = memory.consolidate()
        assert result["promoted"] == 1
        assert memory.get("decision", "project:choice")["value"] == {"choice": "A"}


def test_durable_memory_updates_in_place():
    with NamedTemporaryFile(suffix=".db") as temp:
        memory = MemoryStore(temp.name)
        memory.record_episode(event_type="preference", content={"value": "A"}, source="test", salience=1, durable_kind="preference", durable_key="tone")
        memory.consolidate()
        memory.record_episode(event_type="preference", content={"value": "B"}, source="test", salience=1, durable_kind="preference", durable_key="tone")
        memory.consolidate()
        assert memory.get("preference", "tone")["value"] == {"value": "B"}
        with memory.connect() as db:
            assert db.execute("select count(*) from durable_memory where memory_kind='preference' and memory_key='tone'").fetchone()[0] == 1


def test_meta_review_never_applies_changes():
    with NamedTemporaryFile(suffix=".db") as temp:
        store = SpineStore(temp.name)
        spine = StableSpine(store)
        spine.evaluate(envelope("trust.change", "f1"))
        spine.evaluate(envelope("trust.change", "f2"))
        review = MetaReviewer(store).review()
        assert review["applied_changes"] == 0
        assert any(item["type"] == "TRUST_DEMOTION_PROPOSAL" for item in review["proposals"])
