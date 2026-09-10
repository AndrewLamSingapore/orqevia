import threading
from unittest.mock import Mock

from app.job_queue import Provider, QueuePolicy, WorkerPool


def test_transient_queue_outage_recovers_with_backoff():
    queue = Mock(policy=QueuePolicy())
    queue.recover_expired.side_effect = [OSError("private detail"), None]
    queue.claim.return_value = None
    pool = WorkerPool(queue, [], Mock())
    pool.stop_event = Mock()
    pool.stop_event.wait.side_effect = [False, False, False, True]
    pool._run("w")
    assert queue.recover_expired.call_count == 2
    assert [c.args[0] for c in pool.stop_event.wait.call_args_list] == [.5, 1, .5, .5]
    assert pool.recovery_failures["w"] == 0


def test_permanent_fault_stops_after_five_attempts_without_sensitive_logs(caplog):
    queue = Mock(policy=QueuePolicy())
    queue.recover_expired.side_effect = OSError("SECRET-DO-NOT-LOG")
    pool = WorkerPool(queue, [], Mock())
    pool.stop_event = Mock()
    pool.stop_event.wait.return_value = False
    pool._run("w")
    assert queue.recover_expired.call_count == 5
    assert pool.recovery_failures["w"] == 5
    assert pool.health()["attention_required"]
    assert pool.health()["recovery_exhausted"] == ["w"]
    assert "queue_recovery_exhausted" in caplog.text
    assert "SECRET-DO-NOT-LOG" not in caplog.text
    pool.execute.assert_not_called()


def test_failed_completion_does_not_repeat_provider_or_overwrite_with_error():
    queue = Mock(policy=QueuePolicy())
    provider = Provider("local", "local", "fake", 8192, 0, 1)
    queue.claim.return_value = {"id": "one", "provider": "local"}
    queue.finish.side_effect = OSError("ledger unavailable")
    execute = Mock(return_value={"result": "completed"})
    pool = WorkerPool(queue, [provider], execute)
    pool.stop_event = Mock()
    pool.stop_event.wait.side_effect = [False, True]
    pool._run("w")
    execute.assert_called_once()
    queue.finish.assert_called_once_with("one", result="completed")


def test_restart_after_clean_stop_starts_a_working_worker():
    queue = Mock(policy=QueuePolicy())
    called = threading.Event()
    queue.claim.side_effect = lambda *args: called.set() or None
    pool = WorkerPool(queue, [], Mock())
    try:
        pool.start()
        assert called.wait(2)
        pool.stop()
        called.clear()
        pool.start()
        assert called.wait(2)
        assert len(pool.threads) == 1
    finally:
        pool.stop()


def test_start_does_not_replace_a_worker_that_has_not_stopped():
    queue = Mock(policy=QueuePolicy())
    pool = WorkerPool(queue, [], Mock())
    surviving = Mock()
    surviving.is_alive.return_value = True
    pool.threads = [surviving]
    pool.stop()
    pool.start()
    assert pool.threads == [surviving]
    assert pool.stop_event.is_set()
