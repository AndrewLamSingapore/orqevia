import json
from unittest.mock import Mock

import pytest

from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool
from app.operator_health import interpret
from tests.test_operator_health import evidence


def setup(tmp_path):
    queue = JobQueue(tmp_path / "queue.db", QueuePolicy())
    job = queue.submit(agent="a16", prompt="Review design")
    provider = Provider("local", "local", "fixture", 8192, 0, 1)
    execute = Mock(return_value={"result":"retained-answer", "input_tokens":3, "output_tokens":5})
    pool = WorkerPool(queue, [provider], execute)
    pool.stop_event = Mock()
    pool.stop_event.wait.side_effect = [False, False, False, True]
    return queue, job, pool, execute


def test_transient_result_write_recovers_before_lease_expiry_or_new_claim(tmp_path, monkeypatch):
    queue, job, pool, execute = setup(tmp_path)
    finish = queue.finish
    calls = 0
    def fail_once(job_id, **result):
        nonlocal calls
        calls += 1
        if calls == 1:
            with queue.connect() as db:
                db.execute("update compute_jobs set lease_until=0 where id=?", (job_id,))
            raise OSError("PRIVATE-STORE-FAULT")
        return finish(job_id, **result)
    monkeypatch.setattr(queue, "finish", fail_once)
    pool._run("worker-1")
    stored = queue.get(job["id"])
    assert stored["status"] == "completed"
    assert stored["result"] == "retained-answer"
    assert stored["input_tokens"] == 3 and stored["output_tokens"] == 5
    assert calls == 2
    execute.assert_called_once()
    with queue.connect() as db:
        events = [json.loads(r[0]) for r in db.execute("select details_json from compute_events where event_type='queue.recovery' order by rowid")]
    assert [e["state"] for e in events] == ["retry_wait", "recovered"]
    assert not any(e["authority_expanded"] for e in events)
    assert "PRIVATE-STORE-FAULT" not in json.dumps(events)


def test_committed_result_is_verified_after_lost_acknowledgement(tmp_path, monkeypatch):
    queue, job, pool, execute = setup(tmp_path)
    finish = queue.finish
    def commit_then_fail(job_id, **result):
        finish(job_id, **result)
        raise OSError("acknowledgement lost")
    wrapped = Mock(side_effect=commit_then_fail)
    monkeypatch.setattr(queue, "finish", wrapped)
    pool.stop_event.wait.side_effect = [False, True]
    pool._run("worker-1")
    assert queue.get(job["id"])["status"] == "completed"
    assert pool.recovery_failures["worker-1"] == 0
    wrapped.assert_called_once()
    execute.assert_called_once()


@pytest.mark.parametrize("conflicting_commit", [False, True])
def test_permanent_or_conflicting_save_exhausts_without_reexecution(tmp_path, monkeypatch, conflicting_commit):
    queue, job, pool, execute = setup(tmp_path)
    finish = queue.finish
    calls = 0
    def fail(job_id, **result):
        nonlocal calls
        calls += 1
        if conflicting_commit and calls == 1:
            finish(job_id, result="different-result", input_tokens=3, output_tokens=5)
        raise OSError("unavailable")
    monkeypatch.setattr(queue, "finish", fail)
    pool.stop_event.wait.side_effect = None
    pool.stop_event.wait.return_value = False
    pool._run("worker-1")
    assert calls == 5
    assert pool.health()["attention_required"]
    execute.assert_called_once()
    stored = queue.get(job["id"])
    assert stored["result"] == ("different-result" if conflicting_commit else None)
    assert stored["status"] == ("completed" if conflicting_commit else "running")


def test_recovery_is_degraded_until_verified_and_exhaustion_requires_attention():
    data = evidence()
    data["worker"]["recovering_workers"] = ["worker-1"]
    result = interpret(data)
    assert result["state"] == "DEGRADED"
    assert not result["ready_for_local_work"]
    assert result["attention"][0]["action"].startswith("No action is required")
    data["worker"]["attention_required"] = True
    assert interpret(data)["state"] == "ACTION_REQUIRED"
    data["worker"]["attention_required"] = False
    data["worker"]["recovering_workers"] = []
    assert interpret(data)["state"] == "HEALTHY"

