"""Distinguish growing output from empty-frame timestamps and idle workers."""

import copy
import datetime
import json
import sqlite3
import ssl

import pytest

from app import job_queue
from app.observability_health import _check
from scripts import collect_operational_health as producer


NOW = 1794026700.0
REVISION = "a" * 40
PRIVATE_RESULT = "private streamed model output never exported"
PRIVATE_PROMPT = "private owner prompt never exported"


def identity():
    return {
        "container_id": "b" * 64,
        "process_state": "running",
        "source_revision": REVISION,
        "started_at": producer.iso(NOW - 600),
    }


def progress_data(*, observed=NOW, characters=30, digest="d" * 64):
    return {
        "database_read": True,
        "observed_at": producer.iso(observed),
        "runtime_revision": REVISION,
        "worker_started_at": producer.iso(NOW - 500),
        "worker_completed_at": producer.iso(NOW - 700),
        "worker_progress_samples": [
            {
                "updated_at": producer.iso(observed - 1),
                "started_at": producer.iso(NOW - 500),
                "job_key_sha256": "e" * 64,
                "lease_key_sha256": "f" * 64,
                "result_sha256": digest,
                "result_characters": characters,
                "validation": "VALID_LOCAL_INFERENCING_CURRENT_LEASE",
            }
        ],
    }


def previous_check():
    data = progress_data(observed=NOW - 60, characters=20, digest="c" * 64)
    return producer.backend_readiness_check(data, identity(), NOW - 60)


@pytest.fixture
def backend_store(tmp_path, monkeypatch, capsys):
    """Actual schema and progress writer, confined to temporary SQLite stores."""
    monkeypatch.delenv("ORQEVIA_RESOURCE_GUARDIAN_PROFILE", raising=False)
    queue = job_queue.JobQueue(tmp_path / "compute-queue.db", job_queue.QueuePolicy())
    job = queue.submit(agent="a17", prompt=PRIVATE_PROMPT)
    clock = {"now": NOW}
    timing = {"admitted_at": NOW - 500, "inferencing_at": NOW - 490, "budget": {"total": 1230}}
    with queue.connect() as connection:
        connection.execute(
            """UPDATE compute_jobs SET status='running',lifecycle_state='INFERENCING',
            local_inflight=1,cloud_inflight=0,started_at=?,updated_at=?,lease_until=?,
            timings_json=?,result=? WHERE id=?""",
            (producer.iso(NOW - 500), producer.iso(NOW - 1), NOW + 760, json.dumps(timing), PRIVATE_RESULT, job["id"]),
        )
    with sqlite3.connect(tmp_path / "objectives.db") as connection:
        connection.execute("CREATE TABLE objectives(id TEXT)")
        connection.execute("INSERT INTO objectives VALUES('private-objective')")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_COMPUTE_QUEUE_DB", str(tmp_path / "compute-queue.db"))
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", REVISION)
    original_datetime = datetime.datetime

    class FrozenDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return original_datetime.fromtimestamp(clock["now"], tz)

    monkeypatch.setattr(datetime, "datetime", FrozenDateTime)
    monkeypatch.setattr(job_queue, "utcnow", lambda: producer.iso(clock["now"] - 1))

    def observe(**changes):
        if changes:
            assert set(changes) <= {
                "status",
                "lifecycle_state",
                "local_inflight",
                "cloud_inflight",
                "started_at",
                "updated_at",
                "lease_until",
                "result",
                "timings_json",
            }
            with queue.connect() as connection:
                connection.execute(
                    "UPDATE compute_jobs SET " + ",".join(name + "=?" for name in changes) + " WHERE id=?",
                    (*changes.values(), job["id"]),
                )
        exec(compile(producer.BACKEND_READ, "<fixed-backend-read>", "exec"), {})
        raw = capsys.readouterr().out
        assert PRIVATE_PROMPT not in raw and PRIVATE_RESULT not in raw and job["id"] not in raw
        assert "lease_until" not in raw and str(NOW + 760) not in raw
        return json.loads(raw)

    return queue, job["id"], timing, clock, observe


def test_actual_writer_growth_and_readonly_probe_prove_long_job_progress(backend_store):
    queue, job_id, _, clock, observe = backend_store
    data = observe()
    first = producer.backend_readiness_check(data, identity(), NOW)
    assert first["status"] == "UNKNOWN"
    assert first["reason"] == "WORKER_EXECUTION_PROGRESS_NOT_CONFIRMED"
    clock["now"] += 60
    assert queue.update_progress(job_id, PRIVATE_RESULT + " more real output")
    second_data = observe()
    row = producer.backend_readiness_check(second_data, identity(), clock["now"], previous=first)
    assert row["status"] == "PASS"
    assert row["reason"] == "PERSISTENCE_AND_RECENT_EXECUTION_PROGRESS_OBSERVED"
    assert row["observed_at"] == producer.iso(NOW)  # Conservative previous-read bound.
    assert row["worker_progress_at"] == row["observed_at"]
    assert row["worker_progress_started_at"] == producer.iso(NOW - 500)
    assert row["worker_progress_validation"] == producer.PROGRESS_VALIDATION
    with queue.connect() as connection:
        stored = connection.execute("SELECT status,result,prompt FROM compute_jobs WHERE id=?", (job_id,)).fetchone()
    assert tuple(stored) == ("running", PRIVATE_RESULT + " more real output", PRIVATE_PROMPT)


def test_empty_stream_frames_cannot_refresh_genuine_progress(backend_store):
    queue, job_id, _, clock, observe = backend_store
    first = producer.backend_readiness_check(observe(), identity(), NOW)
    prior = first
    for elapsed in (60, 120, 240):
        clock["now"] = NOW + elapsed
        assert queue.update_progress(job_id, PRIVATE_RESULT)
        prior = producer.backend_readiness_check(observe(), identity(), clock["now"], previous=prior)
        assert prior["status"] == "UNKNOWN"
        assert prior["progress_witnesses"][0]["last_genuine_progress_at"] is None


def test_unchanged_text_retains_only_original_genuine_progress_time():
    row = producer.backend_readiness_check(progress_data(), identity(), NOW, previous=previous_check())
    assert row["status"] == "PASS" and row["observed_at"] == producer.iso(NOW - 60)
    for elapsed, status in ((60, "PASS"), (61, "UNKNOWN"), (120, "UNKNOWN")):
        row = producer.backend_readiness_check(
            progress_data(observed=NOW + elapsed), identity(), NOW + elapsed, previous=row
        )
        assert row["status"] == status
        assert row["progress_witnesses"][0]["last_genuine_progress_at"] == producer.iso(NOW - 60)
        if status == "UNKNOWN":
            assert row["reason"] == "WORKER_EXECUTION_PROGRESS_STALE"


@pytest.mark.parametrize("characters,digest", [(20, "d" * 64), (19, "d" * 64), (30, "c" * 64)])
def test_changed_hash_without_growth_or_growth_without_changed_hash_is_not_proof(characters, digest):
    row = producer.backend_readiness_check(
        progress_data(characters=characters, digest=digest), identity(), NOW, previous=previous_check()
    )
    assert row["status"] == "UNKNOWN"
    assert row["worker_progress_at"] is None


@pytest.mark.parametrize("gap", [120, 121, 3600])
def test_progress_time_is_conservative_previous_observation_not_current_update(gap):
    current = NOW - 60 + gap
    row = producer.backend_readiness_check(
        progress_data(observed=current), identity(), current, previous=previous_check()
    )
    assert row["status"] == ("PASS" if gap == 120 else "UNKNOWN")
    assert row["progress_witnesses"][0]["last_genuine_progress_at"] == producer.iso(NOW - 60)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "queued"},
        {"status": "completed"},
        {"status": "cancelled"},
        {"lifecycle_state": "MODEL_LOADING"},
        {"lifecycle_state": "PERSISTING"},
        {"lifecycle_state": None},
        {"local_inflight": 0},
        {"cloud_inflight": 1},
        {"result": None},
        {"result": ""},
        {"result": " \t\r\n\u2003"},
        {"result": b"not text"},
        {"result": "x" * 128001},
        {"result": "x\x00" + "x" * 128000},
        {"result": "x\x00y"},
        {"lease_until": None},
        {"lease_until": "not a lease"},
        {"lease_until": NOW - 1},
        {"lease_until": float("inf")},
        {"lease_until": NOW + 762},
        {"started_at": None},
        {"started_at": "not a timestamp"},
        {"updated_at": ""},
        {"updated_at": "not a timestamp"},
        {"updated_at": producer.iso(NOW - 500)},
        {"updated_at": producer.iso(NOW - 501)},
        {"updated_at": producer.iso(NOW - 121)},
        {"updated_at": producer.iso(NOW + 6)},
        {"timings_json": None},
        {"timings_json": "invalid JSON"},
        {"timings_json": "[]"},
        {"timings_json": "{}"},
    ],
)
def test_invalid_content_occupancy_lease_or_timestamps_export_no_candidate(backend_store, changes):
    _, _, _, _, observe = backend_store
    assert observe(**changes)["worker_progress_samples"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("admitted_at", NOW - 600),
        ("admitted_at", None),
        ("admitted_at", NOW - 1),
        ("inferencing_at", NOW + 1),
        ("inferencing_at", NOW - 501),
        ("inferencing_at", True),
        ("total", 0),
        ("total", float("nan")),
        ("total", float("inf")),
        ("total", 88321),
        ("total", "1230"),
    ],
)
def test_malformed_or_unbound_execution_timing_cannot_validate_lease(backend_store, field, value):
    _, _, timing, _, observe = backend_store
    if field == "total":
        timing["budget"][field] = value
    else:
        timing[field] = value
    assert observe(timings_json=json.dumps(timing))["worker_progress_samples"] == []


def test_observation_cannot_precede_admission_during_a_fresh_claim_race(backend_store):
    _, _, timing, _, observe = backend_store
    timing.update(admitted_at=NOW + 0.5, inferencing_at=NOW + 0.75)
    data = observe(
        started_at=producer.iso(NOW + 0.5),
        updated_at=producer.iso(NOW + 1),
        lease_until=NOW + 0.5 + 1230 + 30,
        timings_json=json.dumps(timing),
    )
    assert data["worker_progress_samples"] == []


@pytest.mark.parametrize("value", [None, "", "invalid", producer.iso(NOW - 500)])
def test_missing_or_nonprogress_candidate_update_cannot_use_witness(value):
    data = progress_data()
    data["worker_progress_samples"][0]["updated_at"] = value
    assert producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "field,value",
    [
        ("backend_container_id", "1" * 64),
        ("backend_source_revision", "c" * 40),
        ("backend_started_at", producer.iso(NOW - 601)),
        ("job_key_sha256", "a" * 64),
        ("lease_key_sha256", "a" * 64),
        ("job_started_at", producer.iso(NOW - 501)),
        ("schema", "unknown"),
        ("first_observed_at", producer.iso(NOW - 501)),
        ("first_observed_at", producer.iso(NOW + 1)),
        ("last_observed_at", producer.iso(NOW + 1)),
        ("last_observed_at", producer.iso(NOW)),
        ("last_updated_at", producer.iso(NOW + 1)),
        ("result_characters", 0),
        ("result_characters", True),
        ("result_sha256", "invalid"),
        ("last_genuine_progress_at", producer.iso(NOW - 1)),
        ("progress_validation", "PROCESS_RUNNING"),
    ],
)
def test_old_context_future_or_malformed_witness_cannot_prove_growth(field, value):
    prior = previous_check()
    prior["progress_witnesses"][0][field] = value
    row = producer.backend_readiness_check(progress_data(), identity(), NOW, previous=prior)
    assert row["status"] == "UNKNOWN"
    assert row["worker_progress_at"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"container_id": None},
        {"container_id": ""},
        {"container_id": "not a container ID"},
        {"process_state": "exited"},
        {"source_revision": "c" * 40},
        {"source_revision": "invalid"},
        {"started_at": producer.iso(NOW - 400)},
        {"started_at": None},
    ],
)
def test_current_candidate_requires_inspected_running_container_source_and_start(changes):
    backend = identity()
    backend.update(changes)
    row = producer.backend_readiness_check(progress_data(), backend, NOW, previous=previous_check())
    assert row["status"] == "UNKNOWN" and not row["progress_witnesses"]


@pytest.mark.parametrize("offset", [-121, 6])
def test_current_stale_or_future_timestamp_cannot_use_old_witness(offset):
    data = progress_data()
    data["worker_progress_samples"][0]["updated_at"] = producer.iso(NOW + offset)
    assert producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())["status"] == "UNKNOWN"


def test_duplicate_or_unbounded_witnesses_and_missing_source_fail_closed():
    data = progress_data()
    prior = previous_check()
    prior["progress_witnesses"] *= 2
    assert producer.backend_readiness_check(data, identity(), NOW, previous=prior)["status"] == "UNKNOWN"
    prior["progress_witnesses"] *= 17
    assert producer.backend_readiness_check(data, identity(), NOW, previous=prior)["status"] == "UNKNOWN"
    data["worker_progress_samples"] *= 33
    assert producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())["status"] == "UNKNOWN"
    data = progress_data()
    del data["runtime_revision"]
    assert producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())["status"] == "UNKNOWN"


@pytest.mark.parametrize("field", ["worker_started_at", "worker_completed_at"])
def test_original_recent_start_or_completion_fallback_stays_unchanged(field):
    data = progress_data()
    data["worker_progress_samples"] = []
    data[field] = producer.iso(NOW - 20)
    row = producer.backend_readiness_check(data, identity(), NOW)
    assert row["status"] == "PASS"
    assert row["reason"] == "PERSISTENCE_AND_RECENT_EXECUTION_OBSERVED"
    assert row["observed_at"] == data[field]


def test_persistence_failure_overrides_growth_and_no_candidate_invents_idle_readiness():
    data = progress_data()
    data["database_read"] = False
    row = producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())
    assert row["status"] == "FAIL" and row["reason"] == "BACKEND_PERSISTENCE_READ_FAILED"
    for samples in (None, [], {}, "not samples"):
        data = progress_data()
        data["worker_progress_samples"] = samples
        row = producer.backend_readiness_check(data, identity(), NOW, previous=previous_check())
        assert row["status"] == "UNKNOWN" and row["reason"] == "WORKER_HEARTBEAT_NOT_EXPOSED"


def test_missing_optional_progress_schema_preserves_readonly_database_observation(backend_store):
    queue, _, _, _, observe = backend_store
    with queue.connect() as connection:
        connection.execute("ALTER TABLE compute_jobs DROP COLUMN lifecycle_state")
    data = observe()
    assert data["database_read"] is True and data["worker_progress_samples"] == []


def test_existing_backend_consumer_accepts_new_reason_and_conservative_time():
    row = producer.backend_readiness_check(progress_data(), identity(), NOW, previous=previous_check())
    projected = _check(
        row,
        key="backend:backend-readiness",
        check_id="backend-readiness",
        service_id="backend",
        kind="DEPENDENCY",
        now=NOW,
        ttl=120,
    )
    assert projected["status"] == "PASS" and projected["state"] == "HEALTHY"
    assert projected["reason"] == row["reason"] and projected["observed_at"] == producer.iso(NOW - 60)
    assert "progress_witnesses" not in projected  # Private witness hashes stay in the protected receipt.
    assert copy.deepcopy(row)["progress_witnesses"] == row["progress_witnesses"]


@pytest.mark.parametrize(
    "previous",
    [
        {"services": [None]},
        {"services": None},
        {"services": [{"service_id": "backend", "checks": [None]}]},
        {"services": [{"service_id": "backend", "checks": None}]},
    ],
)
def test_collector_resets_malformed_previous_rows_without_crashing(previous, tmp_path, monkeypatch):
    monkeypatch.setattr(producer.time, "time", lambda: NOW)

    class ReadonlyRunner:
        def __init__(self):
            self.backend_targets = []

        def run(self, args, *, script=None, timeout=3):
            if "inspect" in args:
                return 0, json.dumps({**identity(), "name": "/" + producer.SERVICES["backend"][0]})
            if script == producer.BACKEND_READ:
                self.backend_targets.append(args[3])
                return 0, json.dumps(progress_data())
            if script == producer.COACHING_READ or (script and ":2000/ready" in script):
                return 0, "{}"
            return 0, ""

    context = {
        "native_identity": {"host_id": "fixture", "boot_id": producer.iso(NOW - 3600)},
        "host_receipt": {
            "host_id": "fixture",
            "boot_id": producer.iso(NOW - 3600),
            "captured_at": NOW - 1,
            "cadence_seconds": 60,
        },
        "integrity": {"status": "PASS", "observed_at": producer.iso(NOW - 1)},
    }
    runner = ReadonlyRunner()
    report = producer.collect(
        context,
        runner=runner,
        budget=producer.Budget(),
        now=NOW,
        previous=previous,
        archive_root=tmp_path,
        reader=lambda *args: (200, b'{"ok":true,"observation_count":1}'),
        url_reader=lambda *args, **kwargs: (200, {}, b"ok"),
        tls_context=ssl.create_default_context(),
        public_tls_context=ssl.create_default_context(),
    )
    check = next(row for row in report["services"][0]["checks"] if row["check_id"] == "backend-readiness")
    assert check["status"] == "UNKNOWN" and check["reason"] == "WORKER_EXECUTION_PROGRESS_NOT_CONFIRMED"
    assert runner.backend_targets == [identity()["container_id"]]
