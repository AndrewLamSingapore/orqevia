"""Transaction durability and deterministic handle release on every platform."""
import sqlite3

import pytest

from app.action_harness import ActionHarness
from app.job_queue import JobQueue
from app.spine import SpineStore
from app.compute_ledger import ComputeLedger


@pytest.fixture(params=["harness", "queue", "spine"])
def store(request, tmp_path):
    path = tmp_path / "store.db"
    if request.param == "harness":
        return ActionHarness(path, {"authority-v0": b"isolated-test-key" * 2})
    if request.param == "queue":
        return JobQueue(path)
    return SpineStore(str(path))


def assert_closed(db):
    # Keep a strong reference: passing must not depend on garbage collection.
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.execute("SELECT 1")


def test_success_commits_and_closes(store):
    with store.connect() as db:
        db.execute("CREATE TABLE lifecycle(value INTEGER)")
        db.execute("INSERT INTO lifecycle VALUES(1)")
    assert_closed(db)
    with store.connect() as reopened:
        assert reopened.execute("SELECT value FROM lifecycle").fetchall()[0][0] == 1
    assert_closed(reopened)


def test_exception_rolls_back_and_closes(store):
    with store.connect() as db:
        db.execute("CREATE TABLE lifecycle(value INTEGER)")
    with pytest.raises(PermissionError, match="denied"):
        with store.connect() as failed:
            failed.execute("INSERT INTO lifecycle VALUES(1)")
            raise PermissionError("denied")
    assert_closed(failed)
    with store.connect() as reopened:
        assert reopened.execute("SELECT count(*) FROM lifecycle").fetchone()[0] == 0


def test_failed_commit_rolls_back_closes_and_propagates(store):
    with store.connect() as db:
        db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id) "
                   "DEFERRABLE INITIALLY DEFERRED)")
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as failed:
            failed.execute("PRAGMA foreign_keys=ON")
            failed.execute("INSERT INTO child VALUES(1)")
    assert_closed(failed)
    with store.connect() as reopened:
        assert reopened.execute("SELECT count(*) FROM child").fetchone()[0] == 0


def test_compute_accounting_closes_every_connection(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    ledger = ComputeLedger(str(tmp_path / "compute.db"))
    ledger.record(task_id="test", stage="test", provider="fake", model="fake",
                  latency_ms=1, success=True)
    assert ledger.recent()[0]["task_id"] == "test"
    assert len(connections) == 3
    for db in connections:
        assert_closed(db)
