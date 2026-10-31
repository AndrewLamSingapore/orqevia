"""Real SQLite legacy-claim tests, without production services or inference."""

from dataclasses import replace
import sqlite3

import pytest

from app.background_admission import BackgroundAdmission
from app.job_queue import JobQueue, Provider, QueuePolicy


MODEL = Provider("ollama-deep", "local", "fixture-model", 32768, 0, 1)


def setup(tmp_path):
    path = tmp_path / "compute.db"
    policy = replace(QueuePolicy(), global_concurrency=8, per_agent_concurrency=2)
    queue = JobQueue(path, policy)
    control = BackgroundAdmission(path)
    return path, queue, control, policy


def submit(queue, agent="a17", priority="background"):
    return queue.submit(
        agent=agent, prompt="Synthetic fixture", model="fixture-model", priority=priority, max_retries=0
    )


def test_live_legacy_dispatch_pause_completion_successor_restart_and_explicit_resume(tmp_path):
    path, queue, control, policy = setup(tmp_path)
    active = submit(queue)
    assert queue.claim_direct(active["id"], [MODEL])["status"] == "running"
    control.install_paused(actor="owner", reason="Explicit pause of new background admissions")
    successor = submit(queue, "a18")
    assert queue.claim_direct(successor["id"], [MODEL]) is None
    queue.finish(active["id"], result="Original completed result preserved")
    assert queue.get(active["id"])["result"] == "Original completed result preserved"
    # A new service/connection runs the unchanged legacy claim code. A
    # queued successor remains accepted and cannot start after reconstruction.
    restarted = JobQueue(path, policy)
    assert restarted.claim_direct(successor["id"], [MODEL]) is None
    assert restarted.get(successor["id"])["status"] == "queued"
    assert restarted.get(successor["id"])["attempts"] == 0
    interactive = submit(restarted, "a19", priority="normal")
    assert restarted.claim_direct(interactive["id"], [MODEL])["status"] == "running"
    restarted.finish(interactive["id"], result="Interactive preserved")
    state = control.state()
    assert state["paused"] and state["database_trigger_installed"]
    assert state["holds"][0]["job_id"] == successor["id"]
    with pytest.raises(ValueError, match="generation changed"):
        control.set_paused(False, expected_generation=-1, actor="owner", reason="Stale resume")
    control.set_paused(False, expected_generation=state["generation"], actor="owner", reason="Explicit resume")
    assert restarted.claim_direct(successor["id"], [MODEL])["status"] == "running"


def test_uninitialized_control_is_unknown_and_fail_closed(tmp_path):
    _, _, control, _ = setup(tmp_path)
    assert control.state()["status"] == "UNKNOWN_FAIL_CLOSED"


def test_missing_state_cannot_silently_open_background_admission(tmp_path):
    _, queue, control, _ = setup(tmp_path)
    control.install_paused(actor="owner", reason="Explicit pause")
    job = submit(queue)
    with queue.connect() as db:
        db.execute("DELETE FROM compute_background_admission")
    assert queue.claim_direct(job["id"], [MODEL]) is None
    assert control.state()["status"] == "UNKNOWN_FAIL_CLOSED"
    assert queue.get(job["id"])["status"] == "queued"


def test_independent_connection_cannot_bypass_pause_with_raw_status_transition(tmp_path):
    path, queue, control, _ = setup(tmp_path)
    control.install_paused(actor="owner", reason="Explicit pause")
    job = submit(queue)
    with sqlite3.connect(path) as db:
        changed = db.execute("UPDATE compute_jobs SET status='running',attempts=attempts+1 WHERE id=?", (job["id"],))
        assert changed.rowcount == 0
    assert queue.get(job["id"])["attempts"] == 0
    assert queue.get(job["id"])["status"] == "queued"


def test_verification_probe_preserves_every_existing_row(tmp_path):
    _, queue, control, _ = setup(tmp_path)
    job = submit(queue)
    before = queue.get(job["id"])
    control.install_paused(actor="owner", reason="Explicit pause")
    assert all(
        control.verify_transaction()[key]
        for key in (
            "background_transition_blocked",
            "background_remains_queued",
            "interactive_transition_allowed",
            "probe_transaction_rolled_back",
        )
    )
    assert queue.get(job["id"]) == before
    assert len(queue.list()) == 1
    assert control.state()["holds"] == []
