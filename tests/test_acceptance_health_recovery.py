import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app import harness_api, operator_health
from app.job_queue import JobQueue, QueuePolicy, WorkerPool


@pytest.mark.parametrize("secret,ready", [("", True), ("short", False), ("x" * 31, False), ("x" * 32, True), ("é" * 16, True)])
def test_status_uses_actual_harness_signer_configuration(monkeypatch, tmp_path, secret, ready):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-only")
    monkeypatch.setenv("PRIME_HARNESS_SIGNING_SECRET", secret)
    monkeypatch.setenv("PRIME_HARNESS_PILOT_ENABLED", " true ")
    monkeypatch.setenv("PRIME_HARNESS_DB", str(tmp_path / "harness.db"))
    monkeypatch.setattr(harness_api, "_runtime_cache", None)
    monkeypatch.setattr(harness_api, "_runtime_fingerprint", None)
    observed = operator_health.authority_configuration()
    assert observed == {"configured": ready, "pilot_enabled": True}
    assert not (tmp_path / "harness.db").exists()
    assert secret not in json.dumps(observed) if secret else True
    if ready:
        harness_api._runtime()
    else:
        with pytest.raises(HTTPException) as exc:
            harness_api._runtime()
        assert exc.value.status_code == 503
        assert not (tmp_path / "harness.db").exists()


def test_missing_token_is_not_configuration_readiness(monkeypatch):
    monkeypatch.delenv("PRIME_SPINE_TOKEN", raising=False)
    monkeypatch.setenv("PRIME_HARNESS_SIGNING_SECRET", "x" * 32)
    assert operator_health.authority_configuration()["configured"] is False


def test_real_queue_retains_recovery_events_before_safe_resume(tmp_path, monkeypatch):
    queue = JobQueue(tmp_path / "queue.db", QueuePolicy())
    original = queue.recover_expired
    calls = 0
    def unavailable_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("PRIVATE-FAULT-DETAIL")
        return original()
    monkeypatch.setattr(queue, "recover_expired", unavailable_once)
    execute = Mock(side_effect=AssertionError("no work authorized"))
    pool = WorkerPool(queue, [], execute)
    pool.stop_event = Mock()
    pool.stop_event.wait.side_effect = [False, False, False, True]
    pool._run("recovery-fixture")
    with queue.connect() as db:
        events = [json.loads(r[0]) for r in db.execute(
            "select details_json from compute_events where event_type='queue.recovery' order by rowid")]
    assert [e["state"] for e in events] == ["retry_wait", "recovered"]
    assert all(e["authority_expanded"] is False for e in events)
    assert "PRIVATE-FAULT-DETAIL" not in json.dumps(events)
    assert pool.recovery_failures["recovery-fixture"] == 0
    assert calls == 2
    execute.assert_not_called()

