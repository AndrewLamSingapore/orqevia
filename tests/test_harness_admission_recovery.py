"""Adversarial shared-store admission/recovery tests; all inference is mocked."""
import sqlite3
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


def test_completion_without_queue_result_is_reported_not_invented(rig):
    job, _ = queued(rig)
    run(rig, job)
    assert rig[1].recover(rig[3]) == {"failed": 0, "uncertain": 0, "completion_pending": 1}
    assert state(rig, job) == "completed"
    assert rig[3].get(job["id"])["result"] is None
    infer = Mock()
    with pytest.raises(PermissionError):
        run(rig, job, infer)
    infer.assert_not_called()


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
