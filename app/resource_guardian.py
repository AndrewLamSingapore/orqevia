"""Optional resource admission in the existing coordinator, without a new daemon.

An Owner mode is a resource preference, never permission to resume background
inference, select a provider, send source off host, or increase spending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time

MODES = {"Eco", "Balanced", "Performance", "Mission", "Recovery", "HOME_ECO", "ULTRA_ECO"}
SCHEMA = "abex.resource-profile.v1"


def number(value, *, minimum=0, maximum=math.inf):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("Finite measured resource value required")
    return value


@dataclass(frozen=True)
class Workload:
    lane: str
    peak_memory_bytes: int
    cpu_threads: int = 1
    priority: int = 50
    gpu_memory_bytes: int = 0
    inference: bool = False

    def __post_init__(self):
        if self.lane not in {"inference", "tools", "build"}:
            raise ValueError("Unknown resource lane")
        for value in (self.peak_memory_bytes, self.gpu_memory_bytes):
            if type(value) is not int or value < 0:
                raise ValueError("Nonnegative explicit memory estimate required")
        if self.peak_memory_bytes == 0:
            raise ValueError("Positive memory budget required")
        if type(self.cpu_threads) is not int or self.cpu_threads < 1:
            raise ValueError("Positive CPU thread estimate required")
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise ValueError("Invalid workload priority")


@dataclass(frozen=True)
class Observation:
    captured_at: float
    host_available_bytes: int | None
    cpu_percent: float | None
    runtime_available_bytes: int | None = None
    disk_available_bytes: int | None = None
    gpu_available_bytes: int | None = None
    temperature_c: float | None = None
    host_boot_id: str | None = None
    commit_available_bytes: int | None = None
    disk_busy_percent: float | None = None


@dataclass(frozen=True)
class Decision:
    admitted: bool
    selected_mode: str
    effective_mode: str
    reason: str
    concurrency: int
    recovering: bool
    unknown_metrics: tuple[str, ...] = ()


class Profile:
    def __init__(self, data):
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise ValueError("Unsupported resource profile")
        if data.get("mode") not in MODES or not data.get("evidence"):
            raise ValueError("Explicit mode and measurement evidence required")
        self.data = data
        hardware = data["hardware"]
        for key in ("logical_processors", "host_memory_bytes", "runtime_memory_bytes", "disk_bytes"):
            if type(hardware[key]) is not int or hardware[key] < 1:
                raise ValueError("Observed hardware envelope required")
        for key in ("host_memory", "runtime_memory", "disk"):
            number(data["reserve_fractions"][key], minimum=0.01, maximum=0.8)
        thresholds = data["thresholds"]
        number(thresholds["cpu_busy_percent"], minimum=1, maximum=100)
        number(thresholds["cpu_recovery_percent"], minimum=1, maximum=100)
        if thresholds["cpu_recovery_percent"] >= thresholds["cpu_busy_percent"]:
            raise ValueError("Distinct pressure and recovery thresholds required")
        if thresholds.get("temperature_c") is not None:
            number(thresholds["temperature_c"], minimum=1, maximum=150)
        number(data["freshness_seconds"], minimum=1, maximum=600)
        for lane in ("inference", "tools", "build"):
            value = data["qualified_concurrency"][lane]
            if type(value) is not int or not 1 <= value <= hardware["logical_processors"]:
                raise ValueError("Qualified concurrency must fit observed CPU capacity")
        for model, value in data.get("model_memory_bytes", {}).items():
            if not isinstance(model, str) or not model or type(value) is not int or value < 1:
                raise ValueError("Explicit qualified model memory budget required")
        # One heavy inference remains the qualified initial physical envelope.
        if data["qualified_concurrency"]["inference"] != 1:
            raise ValueError("Additional inference slots require a separately qualified implementation")
        for mode in MODES:
            row = data["modes"][mode]
            for lane in ("inference", "tools", "build"):
                if type(row[lane]) is not int or not 0 <= row[lane] <= data["qualified_concurrency"][lane]:
                    raise ValueError("Mode exceeds qualified concurrency")
        self.digest = hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()

    @classmethod
    def read(cls, path):
        path = Path(path)
        if path.stat().st_size > 131072:
            raise ValueError("Resource profile is too large")
        return cls(json.loads(path.read_text(encoding="utf-8-sig")))

    def decide(
        self,
        observation,
        workload,
        *,
        mode=None,
        active=0,
        reserved_bytes=0,
        owner_paused=False,
        recovering=False,
        now=None,
    ):
        mode = mode or self.data["mode"]
        if mode not in MODES:
            raise ValueError("Unknown operating mode")
        current = time.time() if now is None else now
        capacity = self.data["hardware"]
        thresholds = self.data["thresholds"]
        unknown = tuple(
            name
            for name, value in (
                ("cpu", observation.cpu_percent),
                ("host_memory", observation.host_available_bytes),
                ("gpu_memory", observation.gpu_available_bytes),
                ("temperature", observation.temperature_c),
            )
            if value is None
        )
        limit = self.data["modes"][mode][workload.lane]

        def decision(allowed, reason, recovery=None):
            state = recovering if recovery is None else recovery
            return Decision(allowed, mode, "Recovery" if state else mode, reason, limit, state, unknown)

        if workload.inference and owner_paused and workload.priority < 50:
            return decision(False, "OWNER_BACKGROUND_PAUSED")
        try:
            age = current - number(observation.captured_at)
            if not 0 <= age <= self.data["freshness_seconds"]:
                return decision(False, "RESOURCE_OBSERVATION_STALE", True)
            if observation.host_available_bytes is None or observation.cpu_percent is None:
                return decision(False, "HOST_CAPACITY_UNKNOWN", True)
            number(observation.host_available_bytes, maximum=capacity["host_memory_bytes"])
            number(observation.cpu_percent, maximum=100)
            for value in (
                observation.runtime_available_bytes,
                observation.disk_available_bytes,
                observation.gpu_available_bytes,
                observation.temperature_c,
                observation.commit_available_bytes,
                observation.disk_busy_percent,
            ):
                if value is not None:
                    number(value)
        except (ValueError, TypeError):
            return decision(False, "RESOURCE_OBSERVATION_INVALID", True)
        host_reserve = math.ceil(capacity["host_memory_bytes"] * self.data["reserve_fractions"]["host_memory"])
        runtime_reserve = math.ceil(capacity["runtime_memory_bytes"] * self.data["reserve_fractions"]["runtime_memory"])
        required = workload.peak_memory_bytes + max(0, reserved_bytes)
        if observation.host_available_bytes - required < host_reserve:
            return decision(False, "WAITING_FOR_HOST_MEMORY", True)
        if observation.commit_available_bytes is not None and required > observation.commit_available_bytes:
            return decision(False, "WAITING_FOR_COMMIT_CAPACITY", True)
        if workload.inference:
            if observation.runtime_available_bytes is None:
                return decision(False, "RUNTIME_MEMORY_UNKNOWN", True)
            if observation.runtime_available_bytes - required < runtime_reserve:
                return decision(False, "WAITING_FOR_RUNTIME_MEMORY", True)
        if observation.disk_available_bytes is not None:
            if observation.disk_available_bytes < capacity["disk_bytes"] * self.data["reserve_fractions"]["disk"]:
                return decision(False, "WAITING_FOR_DISK_CAPACITY", True)
        if observation.disk_busy_percent is not None and observation.disk_busy_percent >= thresholds.get(
            "disk_busy_percent", 100
        ):
            return decision(False, "WAITING_FOR_DISK_IO", True)
        if workload.gpu_memory_bytes:
            if observation.gpu_available_bytes is None:
                return decision(False, "GPU_CAPACITY_UNVERIFIED", True)
            if workload.gpu_memory_bytes > observation.gpu_available_bytes:
                return decision(False, "WAITING_FOR_GPU_MEMORY", True)
        thermal_limit = thresholds.get("temperature_c")
        if (
            thermal_limit is not None
            and observation.temperature_c is not None
            and observation.temperature_c >= thermal_limit
        ):
            return decision(False, "OBSERVED_THERMAL_PRESSURE", True)
        if observation.cpu_percent >= thresholds["cpu_busy_percent"]:
            return decision(False, "WAITING_FOR_CPU_CAPACITY", True)
        if recovering and observation.cpu_percent > thresholds["cpu_recovery_percent"]:
            return decision(False, "RECOVERY_HYSTERESIS", True)
        if recovering and observation.host_available_bytes < host_reserve * 1.2:
            return decision(False, "RECOVERY_MEMORY_HYSTERESIS", True)
        recovering = False
        if mode == "Recovery" and workload.priority < 100:
            return decision(False, "RECOVERY_MODE_NONESSENTIAL_DEFERRED", True)
        if active >= limit:
            return decision(False, "QUALIFIED_LANE_CAPACITY")
        available_threads = max(1, math.floor(capacity["logical_processors"] * (100 - observation.cpu_percent) / 100))
        if workload.cpu_threads > available_threads:
            return decision(False, "WAITING_FOR_CPU_THREADS")
        return decision(True, "CAPACITY_AVAILABLE")


def capture(profile):
    """Read existing host telemetry plus immediate process/VM memory headroom."""
    data = profile.data
    host = json.loads(Path(data["host_metrics_path"]).read_text(encoding="utf-8-sig"))
    available = host.get("memory", {}).get("available_bytes")
    captured = host.get("captured_at", 0)
    # The command adapter runs natively on Windows; psutil is an existing
    # project dependency. Linux uses the mounted host receipt unchanged.
    if os.name == "nt":
        import psutil

        available = psutil.virtual_memory().available
    runtime_available = None
    try:
        lines = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
        runtime_available = next(int(line.split()[1]) * 1024 for line in lines if line.startswith("MemAvailable:"))
    except (OSError, ValueError, StopIteration):
        pass
    return Observation(
        captured,
        available,
        host.get("cpu_percent"),
        runtime_available,
        host.get("disk", {}).get("available_bytes"),
        host.get("gpu", {}).get("available_bytes"),
        host.get("thermal", {}).get("maximum_c"),
        host_boot_id=host.get("boot_id"),
        commit_available_bytes=host.get("memory", {}).get("commit_available_bytes"),
        disk_busy_percent=host.get("disk", {}).get("busy_percent"),
    )


class ResourceGuardian:
    def __init__(self, profile, *, sampler=capture, clock=time.time):
        self.profile, self.sampler, self.clock = profile, sampler, clock

    @classmethod
    def from_environment(cls):
        path = os.getenv("ORQEVIA_RESOURCE_GUARDIAN_PROFILE", "").strip()
        if not path:
            return None
        try:
            return cls(Profile.read(path))
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).warning("Invalid optional resource profile; existing baseline policy retained")
            return None

    def install(self, db):
        db.executescript("""
            CREATE TABLE IF NOT EXISTS compute_resource_policy(
                id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL,
                recovering INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_resource_decisions(
                job_id TEXT PRIMARY KEY, reason TEXT NOT NULL, selected_mode TEXT NOT NULL,
                effective_mode TEXT NOT NULL, admitted INTEGER NOT NULL, observed_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_resource_outcomes(
                job_attempt TEXT PRIMARY KEY, task_class TEXT NOT NULL, model TEXT,
                duration_seconds REAL NOT NULL, actual_cost_usd REAL, recorded_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_resource_permits(
                id TEXT PRIMARY KEY, lane TEXT NOT NULL, memory_bytes INTEGER NOT NULL,
                cpu_threads INTEGER NOT NULL, pid INTEGER, process_started REAL,
                state TEXT NOT NULL, lease_until REAL NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS compute_resource_process_keys(
                key_hash TEXT PRIMARY KEY, request_hash TEXT NOT NULL, permit_id TEXT NOT NULL,
                receipt_json TEXT);
        """)
        db.execute(
            "INSERT OR IGNORE INTO compute_resource_policy VALUES(1,?,0,?)", (self.profile.data["mode"], self.clock())
        )

    def set_mode(self, db, mode):
        if mode not in MODES:
            raise ValueError("Unknown operating mode")
        db.execute("UPDATE compute_resource_policy SET mode=?,updated_at=? WHERE id=1", (mode, self.clock()))
        return self.status(db)

    def status(self, db):
        row = db.execute("SELECT mode,recovering,updated_at FROM compute_resource_policy WHERE id=1").fetchone()
        permits = [
            dict(r)
            for r in db.execute(
                "SELECT id,lane,pid,state,lease_until FROM compute_resource_permits WHERE state IN ('RESERVED','RUNNING')"
            )
        ]
        return {
            "configured": True,
            "mode": row[0],
            "recovering": bool(row[1]),
            "updated_at": row[2],
            "profile_sha256": self.profile.digest,
            "qualified_concurrency": self.profile.data["qualified_concurrency"],
            "qualification": self.profile.data.get("qualification", "UNVERIFIED"),
            "changes_owner_pause": False,
            "unregistered_process_control": False,
            "active_tool_permits": permits,
        }

    def observe(self):
        try:
            return self.sampler(self.profile)
        except (OSError, ValueError, KeyError, TypeError):
            return Observation(self.clock(), None, None)

    def admit(self, db, job, provider):
        row = db.execute("SELECT mode,recovering FROM compute_resource_policy WHERE id=1").fetchone()
        has_pause = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_background_admission'"
        ).fetchone()
        pause = (
            db.execute("SELECT paused FROM compute_background_admission WHERE id=1").fetchone() if has_pause else None
        )
        owner_paused = pause is None or bool(pause[0])
        # Cloud decisions keep their existing provider/data/cost authority. A
        # mode change cannot bypass the background pause by routing off host.
        local = provider.kind == "local"
        observation = self.observe()
        budget = self.profile.data.get("model_memory_bytes", {}).get(job.get("model"), 0)
        workload = Workload(
            "inference",
            max(int(job["ram_mb"]) * 1048576, int(budget)) if local else 1048576,
            priority=int(job["priority"]),
            gpu_memory_bytes=int(job["vram_mb"]) * 1048576 if local else 0,
            inference=True,
        )
        active = db.execute(
            "SELECT count(*) FROM compute_jobs WHERE status='running' OR local_inflight=1 OR cloud_inflight=1"
        ).fetchone()[0]
        reserved = db.execute(
            "SELECT coalesce(sum(memory_bytes),0) FROM compute_resource_permits WHERE state IN ('RESERVED','RUNNING')"
        ).fetchone()[0]
        decision = self.profile.decide(
            observation,
            workload,
            mode=row[0],
            active=active,
            reserved_bytes=reserved,
            owner_paused=owner_paused,
            recovering=bool(row[1]),
            now=self.clock(),
        )
        if local and not budget and decision.admitted:
            decision = Decision(
                False,
                decision.selected_mode,
                decision.effective_mode,
                "MODEL_MEMORY_BUDGET_UNQUALIFIED",
                decision.concurrency,
                decision.recovering,
                decision.unknown_metrics,
            )
        old = db.execute(
            "SELECT reason,selected_mode,effective_mode,admitted FROM compute_resource_decisions WHERE job_id=?",
            (job["id"],),
        ).fetchone()
        values = (decision.reason, decision.selected_mode, decision.effective_mode, int(decision.admitted))
        if old is None or tuple(old) != values:
            db.execute(
                "INSERT OR REPLACE INTO compute_resource_decisions VALUES(?,?,?,?,?,?)",
                (job["id"], *values, self.clock()),
            )
        db.execute("UPDATE compute_resource_policy SET recovering=? WHERE id=1", (int(decision.recovering),))
        return decision

    def record_outcome(self, db, job, actual_cost):
        if not job.get("started_at"):
            return
        timings = json.loads(job.get("timings_json") or "{}")
        start = timings.get("admitted_at")
        if start is None:
            if job["attempts"] > 1:
                return  # Legacy retries do not expose an independent attempt start.
            start = datetime.fromisoformat(job["started_at"]).astimezone(timezone.utc).timestamp()
        elapsed = self.clock() - start
        if not math.isfinite(elapsed) or elapsed < 0:
            return  # Clock discontinuity is not a measured zero-second execution.
        db.execute(
            "INSERT OR IGNORE INTO compute_resource_outcomes VALUES(?,?,?,?,?,?)",
            (
                str(job["id"]) + ":" + str(job["attempts"]),
                job.get("task_class", "auto"),
                job.get("model"),
                elapsed,
                actual_cost,
                self.clock(),
            ),
        )

    def estimates(self, db):
        rows = db.execute(
            "SELECT task_class,model,count(*),avg(duration_seconds),min(duration_seconds),max(duration_seconds) FROM compute_resource_outcomes GROUP BY task_class,model ORDER BY task_class,model"
        ).fetchall()
        return [
            {
                "task_class": r[0],
                "model": r[1],
                "samples": r[2],
                "mean_seconds": r[3],
                "minimum_seconds": r[4],
                "maximum_seconds": r[5],
                "uncertainty": "INSUFFICIENT_SAMPLES" if r[2] < 10 else "OBSERVED_RANGE_NOT_CONFIDENCE_BOUND",
                "scope": "EXECUTION_WALL_TIME_NOT_CPU_ENERGY_OR_SEMANTIC_QUALITY",
            }
            for r in rows
        ]
