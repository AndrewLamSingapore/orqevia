"""Exercise the explicit mirror migration against the real old SQLite provisioner."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app import collective_intelligence as collective

PREVIOUS = "5c41c170f3e9e993ccccfa1e095fed5e7a054d8904f8e0f410cafad9a3015833"


@pytest.fixture
def legacy_scope(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    raw_path = root / "docs/history/registry-retirement-20261106/config/agent_registry.json"
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == PREVIOUS
    registry = json.loads(raw_path.read_bytes())
    aliases = {lead["id"]: lead["agent_id"] for lead in registry["leads"]}
    for agent in registry["agents"]:
        agent["id"] = agent["agent_id"]
        agent["reports_to"] = aliases.get(agent["reports_to"], agent["reports_to"])
    fixture = (root / "tests/fixtures/collective_registry_v1_provision.py.txt").read_bytes()
    assert hashlib.sha256(fixture).hexdigest() == "cd20b159787a27a07d45605199c687af209ce7a48b06f28e2e79d5f31566cdd9"
    namespace = dict(vars(collective), REGISTRY_PATH=raw_path, load_agent_registry=lambda: deepcopy(registry))
    exec(compile(fixture, "historical-collective-provisioner", "exec"), namespace)
    store = collective.CollectiveStore(tmp_path / "collective.db")
    owner = collective.CollectivePrincipal("tenant", "owner", "owner-session", roles=frozenset({"OWNER"}))
    with monkeypatch.context() as patch:
        patch.setattr(collective.CollectiveStore, "provision", namespace["provision"])
        store.provision(owner)
    return store, owner


def snapshot(store):
    with store.connect() as db:
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("registry_records", "registry_relations", "audit_events", "command_receipts")
        }


def test_known_mirror_migrates_without_losing_user_data_relations_or_audit(legacy_scope):
    store, owner = legacy_scope
    user_record = store.command(
        owner,
        "evidence.record",
        {
            "content": {"observation": "Original Owner research"},
            "source": "test:original-evidence",
            "kind": "SOURCE",
            "environment": "TEST",
        },
        "original-owner-evidence",
    )["record"]
    before = snapshot(store)
    old_root = store.query(owner, "orchestrators", "orchestrator:prime")
    old_dependencies = store.query(owner, "dependencies")["items"]
    assert len(old_dependencies) == 21
    assert store.integrity(owner)["pass"]
    with pytest.raises(collective.CollectiveConflict):
        store.provision(owner)

    migrated = store.migrate_canonical_registry(owner, expected_source_sha256=PREVIOUS)
    assert migrated["migrated"] and migrated["agents"] == 21
    assert migrated["historical_source_records"] == 22
    after = snapshot(store)
    assert len(after["registry_records"]) == len(before["registry_records"]) + 1
    assert after["registry_relations"] == before["registry_relations"]
    assert after["audit_events"][: len(before["audit_events"])] == before["audit_events"]
    assert after["command_receipts"] == before["command_receipts"]
    assert store.query(owner, "evidence", user_record["id"]) == user_record
    assert store.query(owner, "orchestrators")["items"][0]["data"]["canonical_id"] == "orqevia"
    archived = store.query(owner, "orchestrators", filters={"state": "HISTORICAL_SOURCE_MIRROR"})["items"]
    assert len(archived) == 1 and archived[0]["data"] == old_root["data"]
    assert store.query(owner, "dependencies")["total"] == 0
    historical = store.query(owner, "dependencies", filters={"state": "HISTORICAL_SOURCE_MIRROR"})["items"]
    assert {item["id"]: item["data"] for item in historical} == {item["id"]: item["data"] for item in old_dependencies}
    assert store.lookup_dependencies(owner, "agent:a02")["dependencies"] == []
    assert store.query(owner, "agents")["total"] == 21
    assert store.query(owner, "capabilities")["total"] == 29
    assert store.integrity(owner)["pass"]
    assert store.provision(owner)["replayed"]
    assert store.migrate_canonical_registry(owner, expected_source_sha256=PREVIOUS)["replayed"]
    assert snapshot(store) == after


@pytest.mark.parametrize("change", ["prior-source", "ownership", "coordinator-collision", "unexpected-source"])
def test_unqualified_migration_fails_atomically(legacy_scope, change):
    store, owner = legacy_scope
    expected = PREVIOUS
    if change == "prior-source":
        expected = "0" * 64
    else:
        with store._transaction() as db:
            if change == "coordinator-collision":
                store._create(db, owner, "orchestrators", {"unrelated": "preserve"}, object_id="orchestrator:orqevia")
            else:
                identity = "agent:a29" if change == "ownership" else "canonical-registry"
                record = store._get(db, owner, identity)
                body = dict(record["data"])
                body["authority" if change == "ownership" else "source_sha256"] = "unexpected"
                store._update(db, owner, record, body, expected_version=record["version"])
    before = snapshot(store)
    with pytest.raises(collective.CollectiveConflict):
        store.migrate_canonical_registry(owner, expected_source_sha256=expected)
    assert snapshot(store) == before
    assert store.integrity(owner)["pass"]


def test_migration_requires_privileged_scoped_identity(legacy_scope):
    store, owner = legacy_scope
    verifier = collective.CollectivePrincipal("tenant", "owner", "checker", roles=frozenset({"VERIFIER"}))
    other = collective.CollectivePrincipal("tenant", "other-owner", "other", roles=frozenset({"OWNER"}))
    before = snapshot(store)
    with pytest.raises(collective.CollectiveDenied):
        store.migrate_canonical_registry(verifier, expected_source_sha256=PREVIOUS)
    with pytest.raises(collective.CollectiveNotFound):
        store.migrate_canonical_registry(other, expected_source_sha256=PREVIOUS)
    assert snapshot(store) == before
