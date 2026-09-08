"""Adversarial shared-store admission/recovery tests; all inference is mocked."""
import sqlite3
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from app.action_harness import HarnessUnavailable
from app.job_queue import JobQueue
from tests.test_harness_execution import rig, queued, run


def state(rig, job):
    with rig[1].connect() as db:
        return db.execute("SELECT state FROM harness_jobs WHERE job_id=?", (job["id"],)).fetchone()[0]


@pytest.mark.parametrize("store", ["queue", "spine"])
def test_writers_cannot_invalidate_claim_or_policy_during_admission(rig, monkeypatch, store):
    job, _ = queued(rig)
    harness = rig[1]
    original = harness.revalidate_for_execution
    attempts = []

    def racing_writer(*args, **kwargs):
        path = rig[3].db_path if store == "queue" else rig[2].store.path
        connection = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("BEGIN IMMEDIATE")
            attempts.append(store)
        finally:
            connection.close()
        return original(*args, **kwargs)

    monkeypatch.setattr(harness, "revalidate_for_execution", racing_writer)
    infer = Mock(return_value={"result": "done"})
    run(rig, job, infer)
    assert attempts == [store]
    infer.assert_called_once()


def test_existing_policy_writer_fails_admission_closed(rig):
    job, _ = queued(rig)
    infer = Mock()
    with rig[2].store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(HarnessUnavailable):
            run(rig, job, infer)
    infer.assert_not_called()
    assert state(rig, job) == "queued"


@pytest.mark.parametrize("claimed", [False, True])
def test_orphan_before_consumption_is_failed_revoked_and_never_replayed(rig, claimed):
    job, envelope = queued(rig)
    if claimed:
        rig[1].record_claim(job["id"], envelope)
    with rig[3].connect() as db:
        db.execute("DELETE FROM compute_jobs WHERE id=?", (job["id"],))
    assert rig[1].recover(rig[3]) == {"failed": 1, "uncertain": 0, "completion_pending": 0}
    assert state(rig, job) == "failed"
    assert not rig[1].revalidate_for_execution(envelope, job_id=job["id"]).authorized
    assert rig[1].recover(rig[3])["failed"] == 0


def test_lost_started_job_becomes_uncertain_without_releasing_slot(rig):
    job, envelope = queued(rig)
    rig[1].record_claim(job["id"], envelope)
    assert rig[1].revalidate_for_execution(envelope, job_id=job["id"]).authorized
    with rig[3].connect() as db:
        db.execute("UPDATE compute_jobs SET lease_until=0 WHERE id=?", (job["id"],))
    assert rig[1].recover(rig[3])["uncertain"] == 1
    assert state(rig, job) == "uncertain"
    assert rig[1].recover(rig[3])["uncertain"] == 0
    rig[3].recover_expired()
    second, _ = queued(rig, "a16")
    infer = Mock()
    with pytest.raises(PermissionError, match="slot unavailable"):
        run(rig, second, infer)
    infer.assert_not_called()
    with pytest.raises(PermissionError):
        rig[1].record_verification(job["id"], result_digest="unknown", evidence_ref="not-result-evidence")


def test_completion_repairs_queue_without_execution_or_verification(rig):
    job, _ = queued(rig)
    run(rig, job)
    assert rig[1].recover(rig[3]) == {"failed": 0, "uncertain": 0, "completion_pending": 0}
    assert state(rig, job) == "completed"
    assert rig[3].get(job["id"])["result"] == "done"
    assert rig[3].get(job["id"])["status"] == "completed"
    rig[1].recover(rig[3])
    with rig[3].connect() as db:
        assert db.execute("SELECT count(*) FROM compute_events WHERE event_type='completion_recovered'").fetchone()[0] == 1
    infer = Mock()
    with pytest.raises(PermissionError):
        run(rig, job, infer)
    infer.assert_not_called()


def test_legacy_digest_only_completion_stays_pending(rig):
    job, _ = queued(rig)
    run(rig, job)
    with rig[1].connect() as db:
        db.execute("DELETE FROM harness_results")
    assert rig[1].recover(rig[3])["completion_pending"] == 1
    assert rig[3].get(job["id"])["result"] is None
    assert state(rig, job) == "completed"


@pytest.mark.parametrize("tamper", ["result", "prompt", "completion_event"])
def test_recovery_rejects_changed_completion_provenance(rig, tamper):
    job, _ = queued(rig)
    run(rig, job)
    if tamper == "prompt":
        with rig[3].connect() as db:
            db.execute("UPDATE compute_jobs SET prompt='changed'")
    else:
        with rig[1].connect() as db:
            if tamper == "result":
                db.execute("UPDATE harness_results SET result_json='{}'")
            else:
                db.execute("DELETE FROM harness_events WHERE event_type='execution.completed'")
    with pytest.raises(HarnessUnavailable):
        rig[1].recover(rig[3])
    assert rig[3].get(job["id"])["status"] == "running"


def test_recovery_does_not_treat_another_queue_as_an_orphan(rig, tmp_path):
    job, _ = queued(rig)
    assert rig[1].recover(JobQueue(tmp_path / "unrelated.db")) == {
        "failed": 0, "uncertain": 0, "completion_pending": 0}
    assert state(rig, job) == "queued"


def test_recovery_refuses_missing_queue_provenance(rig):
    job, _ = queued(rig)
    with rig[1].connect() as db:
        db.execute("DELETE FROM harness_job_queues")
    with pytest.raises(HarnessUnavailable, match="provenance"):
        rig[1].recover(rig[3])
    assert state(rig, job) == "queued"


def test_recovery_does_not_silently_accept_a_conflicting_completed_result(rig):
    job, _ = queued(rig)
    run(rig, job)
    rig[3].finish(job["id"], result="different result")
    with pytest.raises(HarnessUnavailable, match="differs"):
        rig[1].recover(rig[3])
    assert state(rig, job) == "completed"
    assert rig[3].get(job["id"])["result"] == "different result"


def test_failed_queue_commit_can_reconcile_again_without_replay(rig, monkeypatch):
    job, _ = queued(rig)
    run(rig, job)
    original = rig[3].connect

    @contextmanager
    def failed_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError("synthetic queue commit loss")

    monkeypatch.setattr(rig[3], "connect", failed_commit)
    with pytest.raises(HarnessUnavailable):
        rig[1].recover(rig[3])
    monkeypatch.setattr(rig[3], "connect", original)
    assert rig[3].get(job["id"])["status"] == "running"
    rig[1].recover(rig[3])
    assert rig[3].get(job["id"])["result"] == "done"
    with rig[3].connect() as db:
        assert db.execute("SELECT count(*) FROM compute_events WHERE event_type='completion_recovered'").fetchone()[0] == 1
