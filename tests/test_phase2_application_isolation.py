"""Actual application context writes must not contaminate another application."""

import sqlite3

import pytest

from app.phase2_intelligence import AuthorityEnvelope, Phase2Kernel

NOW = 2_000_000_000.0


def authority(actor, role="APPLICATION"):
    return AuthorityEnvelope(actor, role, frozenset({"context.write", "objective.create", "objective.read"}), NOW + 60)


def write(store, actor, scope_id, *, value="verified local example", supersedes_id=None):
    return store.ingest_context(
        authority=actor,
        context_key="storage observation",
        scope="APPLICATION",
        scope_id=scope_id,
        epistemic_class="INFERRED",
        temporal_state="CURRENT",
        value=value,
        source="synthetic local test",
        source_version="1",
        source_authority="APPLICATION",
        observed_at=NOW,
        supersedes_id=supersedes_id,
    )


def mission(store, actor):
    return store.create_objective(
        authority=actor,
        objective="Review storage observation",
        success_criteria=["bounded assessment"],
        constraints=["no external action"],
    )


@pytest.mark.parametrize(
    "actor,role",
    [("app-attacker", "APPLICATION"), ("app-victim", "OWNER"), ("app-victim", "MEMBER"), ("app-victim", "SYSTEM")],
)
def test_other_actor_or_role_cannot_insert_application_context(tmp_path, actor, role):
    store = Phase2Kernel(tmp_path / "phase2.db", clock=lambda: NOW)
    with pytest.raises(PermissionError, match="application context scope denied"):
        write(store, authority(actor, role), "app-victim", value="poisoned context")
    with sqlite3.connect(store.path) as db:
        assert db.execute("select count(*) from phase2_context").fetchone()[0] == 0


def test_same_application_write_visible_after_reopen_and_hidden_from_peer(tmp_path):
    path = tmp_path / "phase2.db"
    store = Phase2Kernel(path, clock=lambda: NOW)
    own, peer = authority("app-owner"), authority("app-peer")
    own_mission, peer_mission = mission(store, own), mission(store, peer)
    item = write(store, own, own.actor_id)
    reopened = Phase2Kernel(path, clock=lambda: NOW)
    result = reopened.compile_context(own_mission["objective_id"], authority=own)
    assert [row["context_id"] for row in result.records] == [item["context_id"]]
    assert all(row["grants_authority"] is False for row in result.records)
    assert not reopened.compile_context(peer_mission["objective_id"], authority=peer).records


def test_denied_cross_application_supersession_preserves_original_after_reopen(tmp_path):
    path = tmp_path / "phase2.db"
    store = Phase2Kernel(path, clock=lambda: NOW)
    victim = authority("app-victim")
    target = mission(store, victim)
    original = write(store, victim, victim.actor_id)
    with sqlite3.connect(path) as db:
        before = db.execute("select * from phase2_context").fetchall()
    with pytest.raises(PermissionError, match="application context scope denied"):
        write(
            store,
            authority("app-attacker"),
            victim.actor_id,
            value="attacker substitution",
            supersedes_id=original["context_id"],
        )
    reopened = Phase2Kernel(path, clock=lambda: NOW)
    with sqlite3.connect(path) as db:
        assert db.execute("select * from phase2_context").fetchall() == before
    result = reopened.compile_context(target["objective_id"], authority=victim)
    assert [row["context_id"] for row in result.records] == [original["context_id"]]
    assert result.records[0]["value"] == "verified local example"
