"""Temporary SQLite/queue integration fixtures; no live provider or phone claims."""

from contextlib import closing
import copy
import hashlib
import json
import sqlite3
import time
import uuid

import pytest


CREATED = "2026-10-25T01:00:00+00:00"
UPDATED = "2026-10-25T01:00:02+00:00"
PRIVATE = "private prompt result credential and provider error never export"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PRIME_DATA_DIR", raising=False)
    monkeypatch.setenv("ORQEVIA_COMPUTE_QUEUE_DB", str(tmp_path / "compute-queue.db"))
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "fixture-workspace-owner-token")
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", "a" * 40)
    monkeypatch.setenv("ORQEVIA_RUNTIME_IMAGE_DIGEST", "sha256:" + "b" * 64)
    from app import interface_node as node, objective_api, workspace_observation as observer
    from app.job_queue import JobQueue

    queue = JobQueue(tmp_path / "compute-queue.db")
    monkeypatch.setattr(objective_api.compute_queue_api, "queue", queue)
    policies = {
        client: {"capabilities": ["health.read", "task.read"], "role": "OWNER", "owner_account_id": account}
        for client, account in (("desktop", "owner:one"), ("phone", "owner:one"), ("other", "owner:two"))
    }

    def configure():
        monkeypatch.setenv("ORQEVIA_INTERFACE_CLIENTS_JSON", json.dumps(policies))

    configure()
    with closing(node.db_connect()) as db, db:
        for client in policies:
            node.account_binding(db, client, current_required=True)
    objective_api.connect().close()

    def persist(client="desktop", status="completed", *, updated=UPDATED, recorded=True, task_id=None, steps=None):
        task_id = task_id or str(uuid.uuid4())
        if steps is None:
            job = queue.submit(agent="a17", prompt=PRIVATE, model="fixture-only")
            with queue.connect() as db:
                db.execute(
                    "UPDATE compute_jobs SET status=?,result=?,error=?,created_at=?,started_at=?,completed_at=? WHERE id=?",
                    (
                        status,
                        PRIVATE,
                        PRIVATE,
                        CREATED,
                        CREATED if status != "queued" else None,
                    updated if status in {"completed", "failed", "cancelled", "budget_blocked", "denied"} else None,
                        job["id"],
                    ),
                )
            steps = [{"capability": "responsibility.a17", "dispatch": {"job": {"id": job["id"]}}}]
        with closing(objective_api.connect()) as db, db:
            db.execute("INSERT INTO objectives VALUES(?,?,?,?)", (task_id, "c" * 64, "submitted", json.dumps(steps)))
            if recorded:
                db.execute("INSERT INTO objective_metadata VALUES(?,?,?,?)", (task_id, 0, CREATED, updated))
            objective_api.store_runtime(db, task_id, 0)
        with closing(node.db_connect()) as db, db:
            db.execute("INSERT INTO requests VALUES(?,?,?,?)", (client, task_id, "d" * 64, task_id))
        return task_id

    return {
        "root": tmp_path,
        "node": node,
        "api": objective_api,
        "observer": observer,
        "queue": queue,
        "policies": policies,
        "configure": configure,
        "persist": persist,
        "observe": lambda client="desktop", **kw: observer.owned_work_snapshot(
            client, node.client_policy(client), **kw
        ),
    }


def test_two_devices_share_canonical_owned_work_without_private_content(workspace, monkeypatch):
    w = workspace
    task = w["persist"]()
    phone_task = w["persist"]("phone", "failed")
    foreign_task = w["persist"]("other")
    monkeypatch.setattr(w["observer"], "_utcnow", lambda: UPDATED)
    desktop = w["observe"]()
    phone = w["observe"]("phone")
    assert desktop == phone
    assert desktop["status"] == "OBSERVED" and desktop["scope"] == "OWNER_ACCOUNT"
    assert {item["id"] for item in desktop["tasks"]} == {task, phone_task}
    assert foreign_task not in json.dumps(desktop)
    assert PRIVATE not in json.dumps(desktop)
    assert "owner:one" not in json.dumps(desktop) and "owner:two" not in json.dumps(desktop)
    assert {event["event"] for event in desktop["activity"]} == {"TASK_STATE_OBSERVATION"}
    assert all(event["timestamp"] == UPDATED for event in desktop["activity"])
    assert all(item["progress"] is None for item in desktop["tasks"])
    assert all(item["execution_evidence"]["verification"] == "UNVERIFIED" for item in desktop["tasks"])
    assert all(item["execution_evidence"]["model_content_is_evidence"] is False for item in desktop["tasks"])


@pytest.mark.parametrize(
    "status,canonical",
    [
        ("queued", "WAITING FOR RESOURCE"),
        ("running", "RUNNING"),
        ("completed", "COMPLETED"),
        ("failed", "COMPLETED_WITH_FAILURES"),
        ("cancelled", "COMPLETED_WITH_FAILURES"),
        ("budget_blocked", "COMPLETED_WITH_FAILURES"),
        ("held", "COMPLETED_WITH_FAILURES"),
        ("denied", "COMPLETED_WITH_FAILURES"),
    ],
)
def test_state_is_canonical_queue_derivation_never_stored_submitted(workspace, status, canonical):
    w = workspace
    task = w["persist"](status=status)
    result = w["observe"]()
    assert result["status"] == "OBSERVED"
    row = result["tasks"][0]
    assert row["id"] == task and row["state"] == canonical and row["revision"] == 0
    assert row["agents"] == ["a17"]
    assert row["execution_evidence"]["job_state_counts"] == {status: 1}
    assert row["execution_evidence"]["runtime"] == {"source_revision": "a" * 40, "image_digest": "sha256:" + "b" * 64}


def test_other_account_and_header_shaped_policy_cannot_broaden_scope(workspace):
    w = workspace
    own = w["persist"]("other")
    foreign = w["persist"]("desktop")
    policy = w["node"].client_policy("other")
    with_headers = {**policy, "X-Owner-Account-Id": "owner:one", "X-Role": "OWNER"}
    result = w["observer"].owned_work_snapshot("other", with_headers)
    assert {item["id"] for item in result["tasks"]} == {own}
    assert foreign not in json.dumps(result)
    forged = w["observer"].owned_work_snapshot("other", {**policy, "owner_account_id": "owner:one"})
    assert forged["status"] == "UNAUTHORIZED" and forged["tasks"] == []


def test_rebinding_an_original_task_owner_fails_closed(workspace):
    w = workspace
    w["persist"]()
    assert w["observe"]("phone")["tasks"]
    w["policies"]["desktop"]["owner_account_id"] = "owner:two"
    w["configure"]()
    result = w["observe"]("phone")
    assert result["status"] == "UNAUTHORIZED" and result["tasks"] == [] and result["activity"] == []


def test_stale_caller_policy_and_removed_task_scope_are_denied(workspace):
    w = workspace
    w["persist"]()
    old = copy.deepcopy(w["node"].client_policy("desktop"))
    w["policies"]["desktop"]["owner_account_id"] = "owner:two"
    w["configure"]()
    assert w["observer"].owned_work_snapshot("desktop", old)["status"] == "UNAUTHORIZED"
    w["policies"]["desktop"]["owner_account_id"] = "owner:one"
    w["policies"]["desktop"]["capabilities"] = ["health.read"]
    w["configure"]()
    assert w["observer"].owned_work_snapshot("desktop", old)["status"] == "UNAUTHORIZED"
    assert w["observe"]()["status"] == "UNAUTHORIZED"


def test_concurrent_related_owner_policy_change_does_not_publish_prior_scope(workspace, monkeypatch):
    w = workspace
    w["persist"]()
    original = w["api"]._get

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        w["policies"]["desktop"]["owner_account_id"] = "owner:two"
        w["configure"]()
        return value

    monkeypatch.setattr(w["api"], "_get", changed)
    result = w["observe"]("phone")
    assert result["status"] == "UNAUTHORIZED" and result["tasks"] == []


def test_unlinked_current_policy_retains_client_only_scope(workspace):
    w = workspace
    task = w["persist"]()
    w["persist"]("phone")
    w["policies"]["desktop"].pop("owner_account_id")
    w["configure"]()
    value = w["observe"]()
    assert value["scope"] == "CLIENT"
    assert [item["id"] for item in value["tasks"]] == [task]


@pytest.mark.parametrize("missing", ["interface.db", "objectives.db", "compute-queue.db"])
def test_missing_store_is_unavailable_and_never_recreated(workspace, monkeypatch, missing):
    w = workspace
    w["persist"]()
    path = w["root"] / missing
    if missing == "compute-queue.db":
        path = w["root"] / "absent-queue.db"
        monkeypatch.setattr(w["queue"], "db_path", str(path))
    else:
        path.rename(path.with_suffix(".preserved"))
    value = w["observe"]()
    assert value["status"] == "UNAVAILABLE" and value["tasks"] == []
    assert not path.exists()


def test_read_path_cannot_invoke_schema_migrators_or_change_existing_rows(workspace, monkeypatch):
    w = workspace
    w["persist"]()
    paths = [w["root"] / name for name in ("interface.db", "objectives.db", "compute-queue.db")]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    original = w["api"].connect

    def read_only(*, read_only=False):
        assert read_only is True
        return original(read_only=True)

    monkeypatch.setattr(w["api"], "connect", read_only)
    monkeypatch.setattr(w["node"], "db_connect", lambda: pytest.fail("Observer must not migrate Interface Node"))
    value = w["observe"]()
    assert value["status"] == "OBSERVED"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_upload_references_and_incomplete_dispatch_placeholders_are_excluded(workspace):
    w = workspace
    task = w["persist"]()
    with closing(w["node"].db_connect()) as db, db:
        db.execute("INSERT INTO requests VALUES(?,?,?,?)", ("desktop", "upload", "0" * 64, "upload:" + "1" * 32))
        db.execute("INSERT INTO requests VALUES(?,?,?,NULL)", ("desktop", "interrupted", "2" * 64))
    result = w["observe"]()
    assert result["status"] == "OBSERVED" and len(result["tasks"]) == 1
    assert result["tasks"][0]["id"] == task and result["has_more"] is False


def test_page_reads_only_selected_recent_objectives_and_reports_more(workspace, monkeypatch):
    w = workspace
    ids = []
    for second in range(8):
        ids.append(
            w["persist"](
                updated=f"2026-10-25T01:00:{second:02d}+00:00",
                steps=[
                    {
                        "dispatch": {"state": "COMPLETED", "model_backend": "none", "result": PRIVATE},
                    }
                ],
            )
        )
    original = w["api"]._get
    calls = []

    def observe(task, authorization, *, read_only=False):
        assert read_only is True
        calls.append(task)
        return original(task, authorization, read_only=read_only)

    monkeypatch.setattr(w["api"], "_get", observe)
    result = w["observe"](limit=3)
    assert result["status"] == "OBSERVED" and result["has_more"] is True
    assert set(calls) == set(ids[-3:]) and len(calls) == 3
    assert {item["id"] for item in result["tasks"]} == set(ids[-3:])
    assert PRIVATE not in json.dumps(result)


def test_missing_timestamp_remains_null_and_does_not_invent_activity(workspace):
    w = workspace
    w["persist"](
        recorded=False, steps=[{"dispatch": {"state": "COMPLETED", "model_backend": "none", "result": PRIVATE}}]
    )
    result = w["observe"]()
    assert result["status"] == "OBSERVED" and result["activity"] == []
    task = result["tasks"][0]
    assert task["created_at"] is None and task["updated_at"] is None and task["progress"] is None


def test_dispatch_interruption_is_observed_without_inventing_revision_or_progress(workspace):
    w = workspace
    task = w["persist"]()
    with closing(w["api"].connect()) as db, db:
        db.execute("UPDATE objectives SET state='dispatching' WHERE id=?", (task,))
    result = w["observe"]()
    assert result["status"] == "OBSERVED"
    assert result["tasks"][0]["state"] == "reconciliation_required"
    assert result["tasks"][0]["revision"] is None
    assert result["tasks"][0]["execution_evidence"]["job_count"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"id": "not-a-uuid"},
        {"state": "submitted"},
        {"state": "secret-private-error"},
        {"revision": -1},
        {"revision": "1"},
        {"execution_metadata": {"authoritative": True}},
    ],
)
def test_invalid_canonical_bindings_never_become_observed_work(workspace, monkeypatch, change):
    w = workspace
    w["persist"]()
    original = w["api"]._get
    monkeypatch.setattr(w["api"], "_get", lambda *args, **kw: {**original(*args, **kw), **change})
    result = w["observe"]()
    assert result["status"] == "UNAVAILABLE" and result["tasks"] == []
    assert "secret-private-error" not in json.dumps(result)


def test_empty_existing_stores_are_observed_without_owner_transport(workspace, monkeypatch):
    w = workspace
    monkeypatch.delenv("ORQEVIA_SPINE_TOKEN", raising=False)
    result = w["observe"]()
    assert result["status"] == "OBSERVED" and result["tasks"] == [] and result["activity"] == []


def test_pwa_policy_is_read_without_session_migration_and_preserves_expired_origin_ownership(workspace, monkeypatch):
    w = workspace
    from app import pwa_sessions

    client = "pwa:" + "e" * 32
    with closing(pwa_sessions.database()) as db, db:
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,0,?,?)", ("f" * 64, client, time.time() + 300, "owner:one", "OWNER")
        )
    w["persist"](client)
    with closing(w["node"].db_connect()) as db, db:
        w["node"].account_binding(db, client, current_required=True)
    with closing(pwa_sessions.database()) as db, db:
        db.execute("UPDATE sessions SET expires=? WHERE client_id=?", (time.time() - 1, client))
    monkeypatch.setattr(
        pwa_sessions, "database", lambda: pytest.fail("Read-only observer must not migrate PWA sessions")
    )
    value = w["observe"]("phone")
    assert value["status"] == "OBSERVED" and len(value["tasks"]) == 1


def test_active_pwa_caller_uses_session_binding_and_missing_session_store_stays_unavailable(workspace, monkeypatch):
    w = workspace
    from app import pwa_sessions

    client = "pwa:" + "e" * 32
    with closing(pwa_sessions.database()) as db, db:
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,0,?,?)", ("f" * 64, client, time.time() + 300, "owner:one", "OWNER")
        )
    policy = w["node"].client_policy(client)
    w["persist"]()
    monkeypatch.setattr(
        pwa_sessions, "database", lambda: pytest.fail("Read-only observer must not migrate PWA sessions")
    )
    value = w["observer"].owned_work_snapshot(client, policy)
    assert value["status"] == "OBSERVED" and value["scope"] == "OWNER_ACCOUNT" and len(value["tasks"]) == 1
    root = w["root"] / "missing-session-store"
    root.mkdir()
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(root))
    path = root / "pwa-sessions.db"
    value = w["observer"].owned_work_snapshot(client, policy)
    assert value["status"] == "UNAVAILABLE" and not path.exists()


def test_existing_open_access_policy_reuses_explicit_owner_account(workspace, monkeypatch):
    w = workspace
    from app import open_access

    # Separate fixture clients have no historical binding in this explicit mode.
    with closing(sqlite3.connect(w["root"] / "interface.db")) as db, db:
        db.execute("DELETE FROM client_accounts")
    task = w["persist"]("desktop")
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    value = w["observer"].owned_work_snapshot("phone", open_access.owner_policy())
    assert value["status"] == "OBSERVED" and value["scope"] == "OWNER_ACCOUNT"
    assert value["tasks"][0]["id"] == task


@pytest.mark.parametrize("limit", [0, -1, 51, True, "50"])
def test_invalid_display_page_never_reads_canonical_records(workspace, monkeypatch, limit):
    w = workspace
    monkeypatch.setattr(w["api"], "_get", lambda *a, **kw: pytest.fail("Invalid page must not load task JSON"))
    value = w["observe"](limit=limit)
    assert value["status"] == "UNAVAILABLE" and value["reason"] == "INVALID_DISPLAY_PAGE"
