"""Isolated patient scheduling tests; no production DB or model requests."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from types import SimpleNamespace

import pytest

from app.agent_registry import registered_agent_ids
from app.home_eco import ExecutionBudget
from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool


MODEL = Provider("ollama-deep", "local", "gemma3:12b", 32768, 0, 1)


def queue_at(path, **changes):
    policy = replace(QueuePolicy(coordinated=True, global_concurrency=1), **changes)
    return JobQueue(path, policy)


def submit(queue, agent="a17", **kw):
    return queue.submit(
        agent=agent, prompt="Isolated deterministic executor fixture", model="gemma3:12b", max_retries=0, **kw
    )


def test_independent_queue_connections_share_one_physical_slot(tmp_path):
    first = queue_at(tmp_path / "jobs.db")
    second = queue_at(tmp_path / "jobs.db")
    a = submit(first)
    b = submit(first, "a18")
    claims = []
    barrier = threading.Barrier(2)

    def claim(queue):
        barrier.wait()
        claims.append(queue.claim("independent", [MODEL]))

    threads = [threading.Thread(target=claim, args=(q,)) for q in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert all(not t.is_alive() for t in threads)
    assert sum(x is not None for x in claims) == 1
    assert sorted(first.get(j["id"])["status"] for j in (a, b)) == ["queued", "running"]
    assert first.metrics()["actual_local_slot_owners"] == 1


def test_named_dispatch_cannot_bypass_priority_or_single_slot(tmp_path):
    queue = queue_at(tmp_path / "jobs.db")
    background = submit(queue, priority="background")
    interactive = submit(queue, "a18", priority="high")
    assert queue.claim_direct(background["id"], [MODEL]) is None
    assert queue.claim("worker", [MODEL])["id"] == interactive["id"]
    assert queue.get(background["id"])["lifecycle_state"] == "QUEUED"


def test_aged_background_work_eventually_outranks_interactive(tmp_path):
    queue = queue_at(tmp_path / "jobs.db", starvation_interval_seconds=1)
    old = submit(queue, priority="background")
    submit(queue, "a18", priority="critical")
    with queue.connect() as db:
        db.execute(
            "UPDATE compute_jobs SET created_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(), old["id"]),
        )
    assert queue.claim("worker", [MODEL])["id"] == old["id"]


def test_idempotency_replay_still_works_when_queue_is_full(tmp_path):
    queue = queue_at(tmp_path / "jobs.db", max_waiting_jobs=1)
    original = submit(queue, idempotency_key="same-owned-task")
    assert submit(queue, idempotency_key="same-owned-task")["id"] == original["id"]
    with pytest.raises(ValueError, match="INFERENCE_QUEUE_FULL"):
        submit(queue, "a18")
    assert len(queue.list()) == 1


def test_queue_wait_does_not_consume_patient_execution_budget(tmp_path):
    queue = queue_at(tmp_path / "jobs.db")
    job = submit(queue, priority="background", timeout_seconds=1800)
    with queue.connect() as db:
        timing = json.loads(queue.get(job["id"])["timings_json"])
        timing["queued_at"] -= 7200
        db.execute("UPDATE compute_jobs SET timings_json=? WHERE id=?", (json.dumps(timing), job["id"]))
    claimed = queue.claim("worker", [MODEL])
    assert claimed["lifecycle_state"] == "ADMITTED"
    timing = json.loads(claimed["timings_json"])
    assert timing["queue_wait_seconds"] >= 7200
    assert ExecutionBudget.for_job(claimed).active == 1800
    assert claimed["lease_until"] > time.time() + 1800


def test_legacy_submission_without_timing_records_real_wait_from_creation(tmp_path):
    legacy = JobQueue(tmp_path / "jobs.db", QueuePolicy(coordinated=False))
    job = submit(legacy, timeout_seconds=1800)
    with legacy.connect() as db:
        created = (datetime.now(timezone.utc) - timedelta(seconds=463)).isoformat()
        db.execute("UPDATE compute_jobs SET created_at=? WHERE id=?", (created, job["id"]))
    queue = queue_at(tmp_path / "jobs.db")
    claimed = queue.claim("worker", [MODEL])
    timing = json.loads(claimed["timings_json"])
    assert 463 <= timing["queue_wait_seconds"] < 470
    assert timing["queue_wait_source"] == "JOB_CREATED_AT"
    assert timing["budget"]["active"] == 1800


def test_cancelled_http_request_holds_slot_until_cleanup(tmp_path):
    queue = queue_at(tmp_path / "jobs.db")
    active = submit(queue)
    submit(queue, "a18")
    queue.claim("worker", [MODEL])
    queue.cancel(active["id"])
    assert queue.claim("other-process", [MODEL]) is None
    assert queue.get(active["id"])["lifecycle_state"] == "CANCELLED"
    queue.settle_local(active["id"])
    assert queue.claim("other-process", [MODEL]) is not None


def test_patient_stream_reports_real_phase_and_usage(monkeypatch):
    import app.direct_stream as stream

    phases = []

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "correct"}})
            yield json.dumps(
                {
                    "message": {"content": ""},
                    "done": True,
                    "eval_count": 2,
                    "prompt_eval_count": 3,
                    "load_duration": 1000000000,
                    "prompt_eval_duration": 2000000000,
                    "eval_duration": 4000000000,
                }
            )

    class Client(Response):
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(stream.httpx, "AsyncClient", Client)
    settings = SimpleNamespace(
        ollama_base_url="http://isolated-fixture", keep_alive="2m", context_tokens=8192, max_output_tokens=4096
    )
    job = {"prompt": "fixture", "timeout_seconds": 1800, "priority": 10, "lifecycle_state": "ADMITTED"}
    result = asyncio.run(
        stream.infer(job, MODEL, settings=settings, capacity=lambda _: None, options=lambda: {}, stage=phases.append)
    )
    assert phases == ["MODEL_LOADING", "INFERENCING", "POSTPROCESSING"]
    assert result["result"] == "correct"
    assert result["timing_metrics"]["tokens_per_second"] == 0.5
    assert result["timing_metrics"]["model_load_seconds"] == 1
    assert result["timing_metrics"]["prompt_evaluation_seconds"] == 2


def test_progressing_stream_does_not_reapply_ram_admission_after_model_loading(monkeypatch):
    import app.direct_stream as stream

    admissions = []

    def admit(model):
        admissions.append(model)
        if len(admissions) > 1:
            raise PermissionError("Measured Compute Profile memory reserve reached; local inference held")

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "one "}})
            yield json.dumps({"message": {"content": "two"}})
            yield json.dumps({"message": {"content": ""}, "done": True, "eval_count": 2, "prompt_eval_count": 1})

    class Client(Response):
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(stream.httpx, "AsyncClient", Client)
    settings = SimpleNamespace(
        ollama_base_url="http://isolated-fixture", keep_alive="2m", context_tokens=8192, max_output_tokens=4096
    )
    job = {"prompt": "fixture", "timeout_seconds": 1800, "priority": 10, "lifecycle_state": "ADMITTED"}
    result = asyncio.run(stream.infer(job, MODEL, settings=settings, capacity=admit, options=lambda: {}))
    assert result["result"] == "one two" and admissions == [MODEL.model]


def test_expired_worker_recovery_keeps_original_job_and_bounded_retries(tmp_path):
    queue = queue_at(tmp_path / "jobs.db")
    job = queue.submit(agent="a17", prompt="fixture", model="gemma3:12b", max_retries=1)
    queue.claim("dead-worker", [MODEL])
    with queue.connect() as db:
        db.execute("UPDATE compute_jobs SET lease_until=? WHERE id=?", (time.time() - 1, job["id"]))
    restarted = queue_at(tmp_path / "jobs.db")
    assert restarted.recover_expired() == 1
    recovered = restarted.claim("replacement", [MODEL])
    assert recovered["id"] == job["id"] and recovered["attempts"] == 2
    restarted.finish(job["id"], result="recovered correctly")
    assert restarted.get(job["id"])["lifecycle_state"] == "COMPLETED"


def test_retry_backoff_prevents_immediate_reexecution(tmp_path):
    queue = queue_at(tmp_path / "jobs.db")
    job = queue.submit(agent="a17", prompt="fixture", model="gemma3:12b", max_retries=1)
    queue.claim("worker", [MODEL])
    queue.finish(job["id"], error="TRANSIENT_LOCAL_FAILURE")
    assert queue.claim("worker", [MODEL]) is None
    with queue.connect() as db:
        db.execute("UPDATE compute_jobs SET not_before=0 WHERE id=?", (job["id"],))
    assert queue.claim("worker", [MODEL])["id"] == job["id"]


@pytest.mark.parametrize("agent", registered_agent_ids(include_orchestrator=False))
def test_all_registered_agents_dispatch_execute_persist_and_observe(tmp_path, agent):
    # An actual deterministic tool executor exercises the whole scheduler path.
    # This is not represented as model inference or role-competence acceptance.
    queue = queue_at(tmp_path / "jobs.db")
    job = submit(queue, agent, priority="background", timeout_seconds=1800)
    pool = WorkerPool(queue, [MODEL], lambda _job, _provider: {"result": json.dumps({"sum": 2 + 3})})
    try:
        pool.start()
        deadline = time.monotonic() + 5
        while queue.get(job["id"])["status"] not in ("completed", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        pool.stop()
    result = queue.get(job["id"])
    assert result["status"] == "completed"
    assert json.loads(result["result"]) == {"sum": 5}
    assert result["lifecycle_state"] == "COMPLETED"
    assert result["local_inflight"] == 0
    with queue.connect() as db:
        events = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT details_json FROM compute_events WHERE job_id=? AND event_type='lifecycle'", (job["id"],)
            )
        ]
    assert "ADMITTED" in {x["phase"] for x in events}
    assert "COMPLETED" in {x["phase"] for x in events}
