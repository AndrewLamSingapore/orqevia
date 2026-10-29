"""Isolated resource-policy/ownership cases; never call a model or production DB."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import copy
import json
import math
import subprocess
import sys
import threading
import time

import psutil
import pytest

from app.background_admission import BackgroundAdmission
from app.job_queue import JobQueue, Provider, QueuePolicy
from app.resource_guardian import MODES, Observation, Profile, ResourceGuardian, Workload
from app.resource_process import connect, run_guarded

MIB = 1048576
GIB = 1024 * MIB


def profile():
    # Synthetic envelope is explicit fixture data, never measured ABEX capacity.
    return Profile(
        {
            "schema": "abex.resource-profile.v1",
            "mode": "Balanced",
            "evidence": ["SYNTHETIC_TEST_ONLY"],
            "hardware": {
                "logical_processors": 8,
                "host_memory_bytes": 16 * GIB,
                "runtime_memory_bytes": 8 * GIB,
                "disk_bytes": 100 * GIB,
            },
            "reserve_fractions": {"host_memory": 0.2, "runtime_memory": 0.1, "disk": 0.1},
            "thresholds": {"cpu_busy_percent": 85, "cpu_recovery_percent": 65, "temperature_c": 90},
            "freshness_seconds": 150,
            "qualified_concurrency": {"inference": 1, "tools": 2, "build": 1},
            "model_memory_bytes": {"gemma3:12b": 128 * MIB},
            "modes": {
                mode: {
                    "inference": 1,
                    "tools": 1 if mode in ["Eco", "HOME_ECO", "ULTRA_ECO", "Recovery"] else 2,
                    "build": 1,
                }
                for mode in MODES
            },
        }
    )


def observation():
    return Observation(time.time(), 12 * GIB, 10, runtime_available_bytes=7 * GIB, disk_available_bytes=90 * GIB)


def guardian():
    return ResourceGuardian(profile(), sampler=lambda _: observation())


def test_modes_cannot_raise_measured_ceiling_or_invent_gpu():
    p = profile()
    for mode in MODES:
        result = p.decide(observation(), Workload("inference", 128 * MIB, inference=True, priority=100), mode=mode)
        assert result.concurrency == 1
        assert "temperature" in result.unknown_metrics
    gpu = p.decide(observation(), Workload("tools", 128 * MIB, gpu_memory_bytes=MIB))
    assert not gpu.admitted and gpu.reason == "GPU_CAPACITY_UNVERIFIED"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"host_available_bytes": GIB}, "WAITING_FOR_HOST_MEMORY"),
        ({"runtime_available_bytes": 128 * MIB}, "WAITING_FOR_RUNTIME_MEMORY"),
        ({"cpu_percent": 95}, "WAITING_FOR_CPU_CAPACITY"),
        ({"temperature_c": 94}, "OBSERVED_THERMAL_PRESSURE"),
        ({"captured_at": time.time() - 1000}, "RESOURCE_OBSERVATION_STALE"),
        ({"cpu_percent": math.nan}, "RESOURCE_OBSERVATION_INVALID"),
        ({"host_available_bytes": None}, "HOST_CAPACITY_UNKNOWN"),
        ({"commit_available_bytes": MIB}, "WAITING_FOR_COMMIT_CAPACITY"),
        ({"disk_available_bytes": GIB}, "WAITING_FOR_DISK_CAPACITY"),
    ],
)
def test_pressure_defers_new_work_without_changing_running_work(change, reason):
    result = profile().decide(replace(observation(), **change), Workload("inference", 128 * MIB, inference=True))
    assert not result.admitted and result.reason == reason and result.recovering


def test_recovery_requires_hysteresis_and_then_clears():
    p = profile()
    work = Workload("tools", 64 * MIB)
    assert p.decide(replace(observation(), cpu_percent=75), work, recovering=True).reason == "RECOVERY_HYSTERESIS"
    cleared = p.decide(observation(), work, recovering=True)
    assert cleared.admitted and not cleared.recovering and cleared.effective_mode == "Balanced"


def test_owner_pause_applies_to_inference_and_never_to_safe_tools():
    p = profile()
    sample = observation()
    assert (
        p.decide(sample, Workload("inference", 128 * MIB, priority=25, inference=True), owner_paused=True).reason
        == "OWNER_BACKGROUND_PAUSED"
    )
    assert p.decide(sample, Workload("tools", 64 * MIB, priority=25), owner_paused=True).admitted


def test_modes_persist_without_clearing_owner_pause(tmp_path):
    g = guardian()
    path = tmp_path / "jobs.db"
    queue = JobQueue(path, guardian=g)
    BackgroundAdmission(path).install_paused(actor="TEST", reason="Isolated fixture")
    for mode in MODES:
        with queue.connect() as db:
            g.set_mode(db, mode)
            assert g.status(db)["mode"] == mode
            assert tuple(db.execute("SELECT paused,generation FROM compute_background_admission").fetchone()) == (1, 0)


@pytest.mark.parametrize("requested_model", ["", "gemma3:12b"])
def test_routed_model_budget_uses_actual_provider_without_changing_requested_job(tmp_path, requested_model):
    g = guardian()
    path = tmp_path / "routed.db"
    queue = JobQueue(path, guardian=g)
    BackgroundAdmission(path).install_paused(actor="TEST", reason="Fixture initial state")
    provider = Provider("ollama-deep", "local", "gemma3:12b", 4096, 0, 1)
    job = queue.submit(
        agent="a17",
        prompt="deterministic fixture",
        model=requested_model,
        model_role="deep",
        priority="high",
        ram_mb=128,
    )
    claimed = queue.claim_direct(job["id"], [provider])
    assert claimed is not None
    assert claimed["provider"] == provider.name
    assert claimed["model"] == requested_model
    with queue.connect() as db:
        assert tuple(db.execute("SELECT paused,generation FROM compute_background_admission").fetchone()) == (1, 0)


def resident_fixture():
    from app.resource_guardian import resident_credit

    data = copy.deepcopy(profile().data)
    data.update(
        model_memory_bytes={"gemma3:12b": 6 * GIB},
        model_digests={"gemma3:12b": "a" * 64},
        qualified_context_tokens=8192,
        resident_base_reserve_bytes=128 * MIB,
    )
    p = Profile(data)
    model = [
        {
            "name": "gemma3:12b",
            "digest": "a" * 64,
            "context_length": 8192,
            "expires_at": datetime.fromtimestamp(time.time() + 120, timezone.utc).isoformat(),
        }
    ]
    return p, model, resident_credit


def test_verified_warm_model_is_not_counted_twice_or_credited_to_other_work():
    p, model, validate = resident_fixture()
    name, credit = validate(p, model, model, 5 * GIB + 384 * MIB, {"inactive_file": 256 * MIB})
    assert name == "gemma3:12b" and credit == 5 * GIB
    sample = replace(
        observation(),
        host_available_bytes=5 * GIB,
        runtime_available_bytes=3 * GIB,
        resident_model=name,
        resident_credit_bytes=credit,
    )
    work = Workload("inference", 6 * GIB, inference=True, model=name)
    assert p.decide(sample, work).admitted
    assert not p.decide(replace(sample, resident_credit_bytes=0), work).admitted
    assert not p.decide(sample, replace(work, model="other-model")).admitted
    assert not p.decide(sample, replace(work, lane="tools", inference=False)).admitted
    assert not p.decide(sample, work, reserved_bytes=3 * GIB).admitted


@pytest.mark.parametrize("change", ["digest", "context", "changed", "expired", "counter"])
def test_unknown_or_changed_residency_keeps_full_memory_budget(change):
    p, model, validate = resident_fixture()
    before = copy.deepcopy(model)
    current = 5 * GIB
    if change == "digest":
        model[0]["digest"] = "b" * 64
        before = copy.deepcopy(model)
    elif change == "context":
        model[0]["context_length"] = 32768
        before = copy.deepcopy(model)
    elif change == "changed":
        model[0]["name"] = "other-model"
    elif change == "expired":
        model[0]["expires_at"] = datetime.fromtimestamp(time.time() - 1, timezone.utc).isoformat()
        before = copy.deepcopy(model)
    elif change == "counter":
        current = float("nan")
    assert validate(p, before, model, current, {"inactive_file": 0}) == (None, 0)


def test_capture_rejects_wrong_host_and_respects_field_timestamps(tmp_path):
    from app.resource_guardian import capture

    now = time.time()
    receipt = {
        "schema": "orqevia.host-metrics.v1",
        "collector_id": "abex-host-metrics-v1",
        "host_id": "fixture-host",
        "captured_at": now,
        "cpu_percent": 10,
        "field_status": {"cpu_percent": {"collection_status": "OBSERVED", "captured_at": now - 1000}},
        "memory": {"available_bytes": 12 * GIB, "captured_at": now, "collection_status": "OBSERVED"},
    }
    path = tmp_path / "host.json"
    path.write_text(json.dumps(receipt))
    data = copy.deepcopy(profile().data)
    data.update(host_metrics_path=str(path), host_id="fixture-host")
    sample = capture(Profile(data))
    assert sample.cpu_percent is None
    assert not profile().decide(sample, Workload("tools", MIB)).admitted
    data["host_id"] = "different-host"
    with pytest.raises(ValueError, match="identity mismatch"):
        capture(Profile(data))


def test_restarting_guardian_and_changing_modes_preserves_owner_resume(tmp_path):
    g = guardian()
    path = tmp_path / "resumed.db"
    queue = JobQueue(path, guardian=g)
    BackgroundAdmission(path).install_paused(actor="TEST", reason="Fixture")
    with queue.connect() as db:
        db.execute("UPDATE compute_background_admission SET paused=0,generation=1 WHERE id=1")
    restarted = JobQueue(path, guardian=g)
    for mode in MODES:
        with restarted.connect() as db:
            g.set_mode(db, mode)
            assert tuple(db.execute("SELECT paused,generation FROM compute_background_admission").fetchone()) == (0, 1)


def test_direct_resource_waiter_runs_when_capacity_is_released(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path / "api"))
    monkeypatch.setenv("ORQEVIA_COMPUTE_QUEUE_DB", str(tmp_path / "api-default.db"))
    from app import compute_queue_api as api

    g = guardian()
    queue = JobQueue(tmp_path / "event-driven.db", guardian=g)
    BackgroundAdmission(queue.db_path).install_paused(actor="TEST", reason="Fixture")
    provider = Provider("ollama-deep", "local", "gemma3:12b", 4096, 0, 1)
    first = queue.submit(agent="a17", prompt="fixture", model_role="deep", priority="high", ram_mb=128)
    second = queue.submit(agent="a18", prompt="fixture", model_role="deep", priority="high", ram_mb=128)
    assert queue.claim_direct(first["id"], [provider])
    attempted, completed = threading.Event(), threading.Event()
    stop = threading.Event()

    def dispatch(identifier):
        claimed = queue.claim_direct(identifier, [provider])
        attempted.set()
        if claimed:
            queue.finish(identifier, result="deterministic fixture result")
            completed.set()

    monkeypatch.setattr(api, "queue", queue)
    monkeypatch.setattr(api, "_direct_stop", stop)
    monkeypatch.setattr(api, "dispatch", dispatch)
    worker = threading.Thread(target=api._direct_reap_loop)
    worker.start()
    try:
        assert attempted.wait(2)
        assert queue.get(second["id"])["status"] == "queued"
        queue.finish(first["id"], result="first complete")
        assert completed.wait(2), "The admitted successor must not wait for the15second fallback poll"
        assert queue.get(second["id"])["status"] == "completed"
    finally:
        stop.set()
        queue.wake.set()
        worker.join(2)
        assert not worker.is_alive()


def test_direct_and_worker_claims_both_observe_pressure(tmp_path):
    g = ResourceGuardian(profile(), sampler=lambda _: replace(observation(), host_available_bytes=GIB))
    queue = JobQueue(tmp_path / "jobs.db", guardian=g)
    job = queue.submit(agent="a17", prompt="fixture", model="gemma3:12b", ram_mb=128)
    provider = Provider("local", "local", "gemma3:12b", 32768, 0, 4)
    assert queue.claim_direct(job["id"], [provider]) is None
    assert queue.claim("worker", [provider]) is None
    assert queue.get(job["id"])["status"] == "queued"
    with queue.connect() as db:
        assert db.execute("SELECT count(*) FROM compute_resource_decisions").fetchone()[0] == 1


def test_independent_connections_cannot_exceed_one_inference_slot(tmp_path):
    path = tmp_path / "jobs.db"
    policy = QueuePolicy(global_concurrency=4, coordinated=True)
    queues = [JobQueue(path, policy, guardian=guardian()) for _ in range(4)]
    for agent in ["a17", "a18", "a19", "a20"]:
        queues[0].submit(agent=agent, prompt="fixture", model="gemma3:12b", ram_mb=128)
    barrier = threading.Barrier(4)
    provider = Provider("local", "local", "gemma3:12b", 32768, 0, 4)

    def claim(queue):
        barrier.wait()
        return queue.claim("fixture", [provider])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, queues))
    assert sum(value is not None for value in results) == 1
    assert sum(job["status"] == "queued" for job in queues[0].list()) == 3


def test_unqualified_model_memory_does_not_become_an_inference_claim(tmp_path):
    g = guardian()
    g.profile.data["model_memory_bytes"] = {}
    queue = JobQueue(tmp_path / "jobs.db", guardian=g)
    job = queue.submit(agent="a17", prompt="fixture", model="gemma3:12b", ram_mb=128)
    assert queue.claim_direct(job["id"], [Provider("local", "local", "gemma3:12b", 32768, 0, 1)]) is None
    with queue.connect() as db:
        assert (
            db.execute("SELECT reason FROM compute_resource_decisions").fetchone()[0]
            == "MODEL_MEMORY_BUDGET_UNQUALIFIED"
        )


def test_owned_process_executes_once_and_rejects_identity_conflict(tmp_path):
    g = guardian()
    db = tmp_path / "jobs.db"
    output = tmp_path / "counter.txt"
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys,time; p=Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(.1)",
        str(output),
    ]
    options = dict(
        workload=Workload("tools", 128 * MIB), work_key="owned:test:1", timeout_seconds=3, output=subprocess.DEVNULL
    )
    first = run_guarded(g, db, command, **options)
    second = run_guarded(g, db, command, **options)
    assert first["status"] == "COMPLETED" and second["replayed"]
    assert output.read_text() == "x"
    with pytest.raises(ValueError, match="conflicts"):
        run_guarded(g, db, [sys.executable, "-c", "pass"], **options)
    with connect(db) as connection:
        assert (
            connection.execute("SELECT count(*) FROM compute_resource_permits WHERE state='RUNNING'").fetchone()[0] == 0
        )


@pytest.mark.parametrize("cancel", ["timeout", "event", "memory"])
def test_only_owned_child_is_cancelled_and_capacity_released(tmp_path, cancel):
    event = threading.Event()
    if cancel == "event":
        event.set()
    g = guardian()
    db = tmp_path / "jobs.db"
    result = run_guarded(
        g,
        db,
        [sys.executable, "-c", "import time; time.sleep(5)"],
        workload=Workload("tools", 1 if cancel == "memory" else 128 * MIB),
        work_key="cancel:" + cancel,
        timeout_seconds=0.15 if cancel == "timeout" else 3,
        cancel_event=event,
        output=subprocess.DEVNULL,
    )
    assert (
        result["status"]
        == {"timeout": "EXECUTION_TIMEOUT", "event": "CANCELLED", "memory": "DECLARED_MEMORY_BUDGET_EXCEEDED"}[cancel]
    )
    with connect(db) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM compute_resource_permits WHERE state IN ('RESERVED','RUNNING')"
            ).fetchone()[0]
            == 0
        )
    assert psutil.pid_exists(psutil.Process().pid)


def test_live_orphan_lease_is_not_freed_or_killed(tmp_path):
    g = guardian()
    db = tmp_path / "jobs.db"
    current = psutil.Process()
    with connect(db) as connection:
        g.install(connection)
        connection.execute(
            "INSERT INTO compute_resource_permits VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "fixture-orphan",
                "build",
                128 * MIB,
                1,
                current.pid,
                current.create_time(),
                "RUNNING",
                time.time() - 100,
                time.time() - 200,
            ),
        )
    result = run_guarded(
        g,
        db,
        [sys.executable, "-c", "pass"],
        workload=Workload("build", 128 * MIB),
        work_key="orphan-check",
        timeout_seconds=3,
        output=subprocess.DEVNULL,
    )
    assert result["status"] == "DEFERRED"
    assert result["decision"]["reason"] == "QUALIFIED_LANE_CAPACITY"
    assert current.is_running()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_fast_exit_has_a_terminal_record_not_a_startup_failure(tmp_path, exit_code):
    g = guardian()
    db = tmp_path / "jobs.db"
    result = run_guarded(
        g,
        db,
        [sys.executable, "-c", f"raise SystemExit({exit_code})"],
        workload=Workload("tools", 128 * MIB),
        work_key="fast:" + str(exit_code),
        timeout_seconds=3,
        output=subprocess.DEVNULL,
    )
    assert result["exit_code"] == exit_code
    assert result["status"] == ("COMPLETED" if exit_code == 0 else "FAILED")


def test_outcome_is_not_double_counted_and_queue_wait_is_excluded(tmp_path):
    g = guardian()
    db = tmp_path / "jobs.db"
    now = time.time()
    with connect(db) as connection:
        g.install(connection)
        job = {
            "id": "one-attempt",
            "attempts": 1,
            "task_class": "fixture",
            "model": "fixture",
            "started_at": "2020-01-01T00:00:00+00:00",
            "timings_json": '{"admitted_at":' + str(now - 2) + "}",
        }
        g.record_outcome(connection, job, 0)
        g.record_outcome(connection, job, 0)
        values = g.estimates(connection)
        assert len(values) == 1 and values[0]["samples"] == 1
        assert 1.9 < values[0]["mean_seconds"] < 3


def test_unpersisted_child_identity_is_not_released_by_a_clock(tmp_path):
    g = guardian()
    db = tmp_path / "jobs.db"
    with connect(db) as connection:
        g.install(connection)
        connection.execute(
            "INSERT INTO compute_resource_permits VALUES(?,?,?,?,?,?,?,?,?)",
            ("uncertain-spawn", "build", 128 * MIB, 1, None, None, "RESERVED", time.time() - 100, time.time() - 200),
        )
    result = run_guarded(
        g,
        db,
        [sys.executable, "-c", "pass"],
        workload=Workload("build", 128 * MIB),
        work_key="uncertain-check",
        timeout_seconds=3,
        output=subprocess.DEVNULL,
    )
    assert result["status"] == "DEFERRED"
    with connect(db) as connection:
        assert g.status(connection)["active_tool_permits"][0]["id"] == "uncertain-spawn"


def test_failed_cancellation_retains_ownership_until_process_exit(tmp_path, monkeypatch):
    import app.resource_process as adapter

    g = guardian()
    db = tmp_path / "jobs.db"

    def unavailable(_):
        raise PermissionError("SYNTHETIC_TEST_ONLY")

    monkeypatch.setattr(adapter, "_stop_owned", unavailable)
    result = run_guarded(
        g,
        db,
        [sys.executable, "-c", "import time;time.sleep(.4)"],
        workload=Workload("tools", 128 * MIB),
        work_key="cancel-not-settled",
        timeout_seconds=0.03,
        output=subprocess.DEVNULL,
    )
    assert result["status"] == "CANCELLATION_PENDING"
    with connect(db) as connection:
        row = connection.execute("SELECT pid,state FROM compute_resource_permits").fetchone()
        assert row["state"] == "RUNNING"
        child_pid = row["pid"]
    try:
        psutil.Process(child_pid).wait(timeout=2)
    except psutil.NoSuchProcess:
        pass
