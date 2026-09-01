from tempfile import NamedTemporaryFile

from app.memory import MemoryStore
from app.meta_review import MetaReviewer
from app.spine import SpineStore, StableSpine


def envelope(action: str, key: str):
    return {
        "tenant_id": "personal", "actor_id": "prime-core", "actor_type": "reasoner",
        "action": action, "parameters": {}, "context": {}, "correlation_id": f"c-{key}",
        "idempotency_key": key, "schema_version": "1.0.0", "timestamp": "2026-08-30T00:00:00Z",
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


def test_five_memory_classes_have_retention_and_authority_rules():
    policy = MemoryStore.policy_manifest()
    assert set(policy) == {"working", "episodic", "semantic", "procedural", "protected"}
    assert all(item["retention"] and item["authority"] for item in policy.values())


def test_protected_memory_requires_owner_and_cannot_auto_promote():
    with NamedTemporaryFile(suffix=".db") as temp:
        memory = MemoryStore(temp.name)
        try:
            memory.record_episode(event_type="secret", content={"value": "x"}, source="test", salience=1, durable_kind="protected", durable_key="secret")
            assert False, "protected episode must not auto-promote"
        except ValueError:
            pass
        try:
            memory.put_governed(memory_class="protected", key="secret", value={"value": "x"}, authority="prime")
            assert False, "protected write must require owner"
        except PermissionError:
            pass
        record = memory.put_governed(memory_class="protected", key="secret", value={"value": "x"}, authority="owner")
        assert record["value"]["governance"]["retention"] == "owner_controlled"


def test_meta_review_never_applies_changes():
    with NamedTemporaryFile(suffix=".db") as temp:
        store = SpineStore(temp.name)
        spine = StableSpine(store)
        spine.evaluate(envelope("trust.change", "f1"))
        spine.evaluate(envelope("trust.change", "f2"))
        review = MetaReviewer(store).review()
        assert review["applied_changes"] == 0
        assert any(item["type"] == "TRUST_DEMOTION_PROPOSAL" for item in review["proposals"])
