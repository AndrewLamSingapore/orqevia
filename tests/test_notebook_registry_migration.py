"""Migrate an actual old-provisioned SQLite notebook without losing its history."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from app import agent_notebooks as notebooks


def test_legacy_identity_is_superseded_without_inheriting_it_or_deleting_records(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    fixture = (root / "tests/fixtures/notebook_registry_v1_provision.py.txt").read_bytes()
    assert hashlib.sha256(fixture).hexdigest() == "3bd49d216c2f26df62c4e156ec49a5a8cd97297a602473b827330b4981e79dfa"
    registry = json.loads(
        (root / "docs/history/registry-retirement-20261106/config/agent_registry.json").read_text(encoding="utf8")
    )
    aliases = {lead["id"]: lead["agent_id"] for lead in registry["leads"]}
    for agent in registry["agents"]:
        agent["id"] = agent["agent_id"]
        agent["reports_to"] = aliases.get(agent["reports_to"], agent["reports_to"])
    namespace = {
        "load_agent_registry": lambda: deepcopy(registry),
        "utcnow": notebooks.utcnow,
        "NotebookPrincipal": notebooks.NotebookPrincipal,
        "Any": Any,
    }
    # Execute the hash-pinned historical provisioner only against the new test DB.
    exec(compile(fixture, "historical-notebook-provisioner", "exec"), namespace)
    with monkeypatch.context() as patch:
        patch.setattr(notebooks.AgentNotebookStore, "provision_all", namespace["provision_all"])
        store = notebooks.AgentNotebookStore(tmp_path / "memory.db", embedder=lambda _: [1.0, 0.0])
    owner = notebooks.NotebookPrincipal("owner", "OWNER")
    lesson = store.add_record(
        owner,
        agent_id="a01",
        section="lessons_learned",
        content={"lesson": "Preserve original project evidence."},
        source="owner",
        verification_status="unverified",
        confidence=0.5,
    )
    with store.connect() as db:
        original = {
            row["memory_id"]: (row["content_json"], row["content_hash"])
            for row in db.execute("SELECT * FROM agent_memory_records")
        }
        identities = {
            row["memory_id"] for row in db.execute("SELECT * FROM agent_memory_records WHERE section='identity'")
        }
    assert len(identities) == 21
    assert any('"reports_to":"prime"' in body for body, _ in original.values())
    migrated = store.provision_all()
    assert migrated["notebooks_created"] == 0 and migrated["identity_records_seeded"] == 21
    assert store.provision_all()["identity_records_seeded"] == 0
    with store.connect() as db:
        rows = {row["memory_id"]: dict(row) for row in db.execute("SELECT * FROM agent_memory_records")}
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert len(rows) == len(original) + 21
    for identity, value in original.items():
        assert (rows[identity]["content_json"], rows[identity]["content_hash"]) == value
        assert rows[identity]["deleted_at"] is None
    assert rows[lesson["memory_id"]]["superseded_by"] is None
    assert all(rows[identity]["superseded_by"] in rows for identity in identities)
    current = [
        json.loads(row["content_json"])
        for row in rows.values()
        if row["section"] == "identity" and row["superseded_by"] is None
    ]
    assert len(current) == 21 and all("reports_to" not in item for item in current)
    assert all(item["coordination"] == "DIRECT_CAPABILITY_HANDOFF" for item in current)
    found = store.search(owner, "prime", agent_id="a01")["results"]
    assert not identities.intersection(item["memory_id"] for item in found)
