"""Isolated SQLite/fixture-vector checks; live embedding evidence is separate."""

from contextlib import closing
import hashlib
import json
import sqlite3
import sys
from types import SimpleNamespace
import uuid

import pytest

from app import collective_repair as repair
from app import collective_runtime as runtime
from app.agent_notebooks import AgentNotebookStore
from app.collective_intelligence import CollectiveConflict, CollectiveDenied, CollectivePrincipal, CollectiveStore


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for key, value in {
        "ORQEVIA_PWA_OWNER_ACCOUNT_ID": "repair-fixture-owner",
        "ORQEVIA_TENANT_ID": "repair-fixture-tenant",
        "ORQEVIA_NODE_ID": "ISOLATED_REPAIR_FIXTURE",
        "ORQEVIA_RUNTIME_REVISION": "a" * 40,
        "ORQEVIA_COLLECTIVE_ENABLED": "1",
        "ORQEVIA_COLLECTIVE_AUTO_REPAIR": "1",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def embedding(text):
        calls.append(text)
        return [0.25, 0.5, 0.75]

    notebooks = AgentNotebookStore(tmp_path / "notebooks.db", embedder=embedding)
    board = CollectiveStore(tmp_path / "collective.db")
    owner = CollectivePrincipal(
        "repair-fixture-tenant",
        hashlib.sha256(b"repair-fixture-owner").hexdigest(),
        "fixture-owner-session",
        roles=frozenset({"OWNER"}),
    )
    board.provision(owner)
    monkeypatch.setattr(repair, "get_notebook_store", lambda: notebooks)
    monkeypatch.setitem(sys.modules, "app.collective_runtime", SimpleNamespace(get_store=lambda: board))

    def command(operation, payload):
        return board.command(owner, operation, payload, "fixture-" + uuid.uuid4().hex)["record"]

    def plan(*, scope=None, node="ISOLATED_REPAIR_FIXTURE", restricted=False, adapter="reindex_notebooks"):
        pending = repair.inspect_pending_index()
        target = pending["oldest"]
        evidence = command(
            "evidence.record",
            {"kind": "OBSERVATION", "source": "ISOLATED_REPAIR_FIXTURE", "environment": node, "content": pending},
        )
        gap = command(
            "gap.detect",
            {
                "title": "Fixture missing notebook index " + uuid.uuid4().hex,
                "description": "One existing private notebook has no derived embedding",
                "severity": "LOW",
                "environment": node,
                "owner_agent_id": "a09",
                "evidence_ids": [evidence["id"]],
            },
        )
        gap = command(
            "gap.plan",
            {
                "gap_id": gap["id"],
                "expected_version": gap["version"],
                "objective": "Index one existing private record without changing source or permissions",
                "adapter": adapter,
                "scope": scope if scope is not None else {"memory_id": target["memory_id"]},
                "restricted": restricted,
                "evidence_ids": [evidence["id"]],
            },
        )
        return gap, target

    return SimpleNamespace(notebooks=notebooks, board=board, owner=owner, calls=calls, plan=plan, command=command)


def run(environment, gap):
    return repair.repair_notebook_index(environment.owner, gap["id"], gap["version"])


def test_exact_one_record_repaired_with_independent_bound_evidence(environment):
    before = repair.inspect_pending_index()
    gap, target = environment.plan()
    result = run(environment, gap)
    assert result["status"] == "VERIFIED_REPAIRED"
    assert result["gap"]["state"] == "CLOSED"
    assert result["checks"] == {"outcome": True, "regression": True, "security": True}
    assert len(environment.calls) == 1
    assert repair.inspect_pending_index()["pending"] == before["pending"] - 1
    execution = environment.board.query(environment.owner, "evidence", result["execution_evidence_id"])
    verification = environment.board.query(environment.owner, "evidence", result["verification_evidence_id"])
    assert execution["creator"] == "notebook-index-executor"
    assert verification["creator"] == "notebook-index-verifier"
    assert verification["data"]["content"]["execution_sha256"] == execution["data"]["sha256"]
    assert execution["data"]["content"]["scope"] == {"memory_id": target["memory_id"]}
    assert environment.board.integrity(environment.owner)["pass"]
    assert environment.board.query(environment.owner, "lessons_learned")["total"] == 1
    assert target["source_sha256"] in json.dumps(execution)


def test_runtime_detector_prepares_and_delegates_one_actual_pending_record(environment):
    result = runtime._bounded_notebook_repair(environment.board)
    assert result["status"] == "VERIFIED_REPAIRED"
    assert result["gap"]["state"] == "CLOSED"
    assert len(environment.calls) == 1
    assert environment.board.query(environment.owner, "gaps")["total"] == 1
    assert environment.board.query(environment.owner, "remediation_plans")["total"] == 1


def test_failed_embedding_retains_failed_execution_and_blocked_gap(environment):
    def unavailable(_):
        raise RuntimeError("private provider diagnostic must not be reflected")

    environment.notebooks._embedder = unavailable
    gap, _ = environment.plan()
    result = run(environment, gap)
    assert result["status"] == "NOT_VERIFIED_REPAIRED"
    assert result["gap"]["state"] == "BLOCKED"
    assert not result["checks"]["outcome"]
    execution = environment.board.query(environment.owner, "evidence", result["execution_evidence_id"])
    assert execution["data"]["content"]["outcome"] == "FAILED"
    assert "private provider diagnostic" not in json.dumps(execution)
    assert environment.board.query(environment.owner, "evidence", result["verification_evidence_id"])


@pytest.mark.parametrize("version", [True, 0, -1, 1.0, "4"])
def test_requires_exact_integer_version_before_any_embedding(environment, version):
    gap, _ = environment.plan()
    with pytest.raises(CollectiveConflict):
        repair.repair_notebook_index(environment.owner, gap["id"], version)
    assert not environment.calls


def test_stale_version_has_no_side_effect(environment):
    gap, _ = environment.plan()
    with pytest.raises(CollectiveConflict):
        repair.repair_notebook_index(environment.owner, gap["id"], gap["version"] - 1)
    assert not environment.calls


@pytest.mark.parametrize("roles", [{"SYSTEM"}, {"VERIFIER"}])
def test_service_role_cannot_request_owner_repair(environment, roles):
    gap, _ = environment.plan()
    principal = CollectivePrincipal(
        environment.owner.tenant_id, environment.owner.owner_id, "fixture-unprivileged", roles=frozenset(roles)
    )
    with pytest.raises(CollectiveDenied):
        repair.repair_notebook_index(principal, gap["id"], gap["version"])
    assert not environment.calls


def test_wrong_owner_scope_cannot_touch_global_notebooks(environment):
    gap, _ = environment.plan()
    principal = CollectivePrincipal(
        environment.owner.tenant_id, "different-owner", "fixture-other-owner", roles=frozenset({"OWNER"})
    )
    with pytest.raises(CollectiveDenied):
        repair.repair_notebook_index(principal, gap["id"], gap["version"])
    assert not environment.calls


def test_agent_execution_cannot_invoke_owner_only_repair(environment):
    gap, _ = environment.plan()
    principal = CollectivePrincipal(
        environment.owner.tenant_id,
        environment.owner.owner_id,
        "unused",
        agent_id="a01",
        execution_id="fixture-job",
        roles=frozenset({"AGENT"}),
    )
    with pytest.raises(CollectiveDenied):
        repair.repair_notebook_index(principal, gap["id"], gap["version"])
    assert not environment.calls


@pytest.mark.parametrize(
    "scope", [{"memory_id": "unrelated-record"}, {"memory_id": "unrelated-record", "path": "arbitrary"}]
)
def test_scope_must_be_exact_current_oldest_target(environment, scope):
    gap, _ = environment.plan(scope=scope)
    with pytest.raises((CollectiveDenied, CollectiveConflict)):
        run(environment, gap)
    assert not environment.calls


def test_wrong_environment_does_not_execute(environment):
    gap, _ = environment.plan(node="OTHER_ENVIRONMENT")
    with pytest.raises(CollectiveDenied):
        run(environment, gap)
    assert not environment.calls


@pytest.mark.parametrize("arguments", [{"restricted": True}, {"adapter": "arbitrary_shell"}])
def test_restricted_and_unknown_adapter_plans_do_not_execute(environment, arguments):
    gap, _ = environment.plan(**arguments)
    with pytest.raises(CollectiveConflict):
        run(environment, gap)
    assert not environment.calls


def test_completed_gap_cannot_repeat_the_embedding(environment):
    gap, _ = environment.plan()
    assert run(environment, gap)["status"] == "VERIFIED_REPAIRED"
    with pytest.raises(CollectiveConflict):
        run(environment, gap)
    assert len(environment.calls) == 1


def test_another_inflight_adapter_is_rejected(environment):
    gap, _ = environment.plan()
    with repair._REPAIR_LOCK:
        with pytest.raises(CollectiveConflict):
            run(environment, gap)
    assert not environment.calls


def test_content_mutation_during_embedding_prevents_closure(environment):
    gap, target = environment.plan()

    def mutate_source(_):
        with closing(sqlite3.connect(environment.notebooks.path)) as connection:
            connection.execute(
                "UPDATE agent_memory_records SET content_json=? WHERE memory_id=?",
                ('{"private":"changed while indexing"}', target["memory_id"]),
            )
            connection.commit()
        return [0.25, 0.5, 0.75]

    environment.notebooks._embedder = mutate_source
    result = run(environment, gap)
    assert result["gap"]["state"] == "VERIFYING"
    assert not result["checks"]["regression"] and not result["checks"]["security"]
    assert "changed while indexing" not in json.dumps(result)


def test_actual_cross_agent_read_denial_is_required(environment, monkeypatch):
    gap, _ = environment.plan()
    original = environment.notebooks.get_record

    def flawed_policy(principal, memory_id, **kwargs):
        owner = repair.NotebookPrincipal("fixture-owner", "OWNER")
        return original(owner, memory_id, **kwargs)

    monkeypatch.setattr(environment.notebooks, "get_record", flawed_policy)
    result = run(environment, gap)
    assert result["gap"]["state"] == "VERIFYING"
    assert not result["checks"]["security"]


def test_nonfinite_vector_never_certifies_repair(environment):
    environment.notebooks._embedder = lambda _: [float("nan")]
    gap, _ = environment.plan()
    result = run(environment, gap)
    assert result["gap"]["state"] == "BLOCKED"
    assert not result["checks"]["outcome"]


def test_inspection_exposes_digests_without_memory_content_or_path(environment):
    result = repair.inspect_pending_index()
    assert result["pending"] == 21 and result["supported_target"]
    text = json.dumps(result)
    assert "content_json" not in text and "source_ref" not in text
    assert str(environment.notebooks.path) not in text
    assert len(result["oldest"]["protected_fields_sha256"]) == 64
