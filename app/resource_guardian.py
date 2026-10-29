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
import re
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
    model: str | None = None

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
    resident_model: str | None = None
    resident_credit_bytes: int = 0
    runtime_identity_valid: bool | None = None
    runtime_host_resident_bytes: int | None = None


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
        for model, value in data.get("model_digests", {}).items():
            if (
                model not in data.get("model_memory_bytes", {})
                or not isinstance(value, str)
                or not re.fullmatch(r"[0-9a-f]{64}", value)
            ):
                raise ValueError("Resident credit needs an exact qualified model digest")
        if data.get("resident_memory_path"):
            if type(data.get("qualified_context_tokens")) is not int or data["qualified_context_tokens"] < 1:
                raise ValueError("Resident credit needs a qualified context envelope")
            if type(data.get("resident_base_reserve_bytes")) is not int or data["resident_base_reserve_bytes"] < 1:
                raise ValueError("Resident credit needs a measured non-model process reserve")
        if data.get("require_runtime_identity"):
            if not isinstance(data.get("qualified_runtime_version"), str) or not data["qualified_runtime_version"]:
                raise ValueError("Runtime qualification needs a measured version")
            if set(data.get("model_digests", {})) != set(data.get("model_memory_bytes", {})):
                raise ValueError("Runtime qualification needs every budgeted model digest")
            for key in ("qualified_context_tokens", "qualified_output_tokens"):
                if type(data.get(key)) is not int or data[key] < 1:
                    raise ValueError("Runtime qualification needs the measured token envelope")
        if data.get("runtime_host_memory_ceiling_bytes") is not None:
            ceiling = data["runtime_host_memory_ceiling_bytes"]
            overhead = data.get("runtime_host_overhead_reserve_bytes")
            if type(ceiling) is not int or ceiling < hardware["runtime_memory_bytes"]:
                raise ValueError("Host accounting needs the verified VM ceiling")
            if type(overhead) is not int or overhead < 1:
                raise ValueError("Host accounting needs an explicit VM overhead reserve")
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
        if (
            workload.inference
            and workload.model is not None
            and self.data.get("require_runtime_identity")
            and observation.runtime_identity_valid is not True
        ):
            return decision(False, "MODEL_RUNTIME_QUALIFICATION_MISMATCH", True)
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
        # A measured peak is a total footprint, not another full allocation on
        # every request. Only this exact model's verified live working set can
        # offset its budget; explicit job RAM above that budget remains reserved.
        credit = 0
        if workload.inference and workload.model is not None and workload.model == observation.resident_model:
            if type(observation.resident_credit_bytes) is not int or observation.resident_credit_bytes < 0:
                return decision(False, "RESOURCE_OBSERVATION_INVALID", True)
            credit = min(
                observation.resident_credit_bytes, self.data.get("model_memory_bytes", {}).get(workload.model, 0)
            )
        required = max(0, workload.peak_memory_bytes - credit) + max(0, reserved_bytes)
        host_required = required
        # Windows already charges resident WSL physical pages. Linux model
        # allocations can reuse them; their growth cannot exceed the verified
        # VM ceiling plus an explicit host overhead reserve. Keep the entire
        # workload budget against Linux headroom, and never credit native tools.
        resident = observation.runtime_host_resident_bytes
        ceiling = self.data.get("runtime_host_memory_ceiling_bytes")
        overhead = self.data.get("runtime_host_overhead_reserve_bytes", 0)
        if workload.inference and workload.model is not None and ceiling is not None:
            if type(resident) is int and 0 <= resident <= ceiling + overhead:
                host_required = min(required, max(0, ceiling + overhead - resident))
        if observation.host_available_bytes - host_required < host_reserve:
            return decision(False, "WAITING_FOR_HOST_MEMORY", True)
        if observation.commit_available_bytes is not None and host_required > observation.commit_available_bytes:
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
    raw = Path(data["host_metrics_path"]).read_bytes()
    if len(raw) > 131072:
        raise ValueError("Oversized host receipt")
    host = json.loads(raw.decode("utf-8-sig"))
    if host.get("schema") != "orqevia.host-metrics.v1" or host.get("collector_id") != "abex-host-metrics-v1":
        raise ValueError("Unknown host receipt provenance")
    if data.get("host_id") and host.get("host_id") != data["host_id"]:
        raise ValueError("Host receipt identity mismatch")
    captured = host.get("captured_at", 0)
    from .host_metrics import SOURCES, _measurement

    now = time.time()
    cpu_field = host.get("field_status", {}).get("cpu_percent", {})
    cpu, _ = _measurement(
        host.get("cpu_percent"),
        raw=cpu_field,
        source=SOURCES["cpu"],
        stamp=cpu_field.get("captured_at", captured),
        receipt_stamp=captured,
        now=now,
        maximum=100,
    )
    memory = host.get("memory", {})
    available, _ = _measurement(
        memory.get("available_bytes"),
        raw=memory,
        source=SOURCES["memory"],
        stamp=memory.get("captured_at", captured),
        receipt_stamp=captured,
        now=now,
        integer=True,
    )
    disk = host.get("disk", {})
    disk_available, _ = _measurement(
        disk.get("available_bytes"),
        raw=disk,
        source=SOURCES["disk"],
        stamp=disk.get("captured_at", captured),
        receipt_stamp=captured,
        now=now,
        integer=True,
    )
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
    resident_model, resident_bytes = capture_resident_credit(profile)
    runtime_host_resident = None
    runtime_host = host.get("wsl_runtime", {})
    if (
        runtime_host.get("source") == "Get-Process/vmmemWSL.WorkingSet64"
        and isinstance(host.get("boot_id"), str)
        and bool(host.get("boot_id"))
        and runtime_host.get("process_count") == 1
        and runtime_host.get("boot_id") == host.get("boot_id")
    ):
        runtime_host_resident, _ = _measurement(
            runtime_host.get("working_set_bytes"),
            raw=runtime_host,
            source="Get-Process/vmmemWSL.WorkingSet64",
            stamp=runtime_host.get("captured_at"),
            receipt_stamp=captured,
            now=now,
            integer=True,
        )
    return Observation(
        captured,
        available,
        cpu,
        runtime_available,
        disk_available,
        host.get("gpu", {}).get("available_bytes"),
        host.get("thermal", {}).get("maximum_c"),
        host_boot_id=host.get("boot_id"),
        commit_available_bytes=host.get("memory", {}).get("commit_available_bytes"),
        disk_busy_percent=host.get("disk", {}).get("busy_percent"),
        resident_model=resident_model,
        resident_credit_bytes=resident_bytes,
        runtime_identity_valid=capture_runtime_identity(profile),
        runtime_host_resident_bytes=runtime_host_resident,
    )


def capture_runtime_identity(profile):
    """Revalidate model/runtime/token pins at admission, including after startup."""
    data = profile.data
    if not data.get("require_runtime_identity"):
        return None
    try:
        import urllib.request
        from .settings import SETTINGS

        if (
            SETTINGS.context_tokens > data["qualified_context_tokens"]
            or SETTINGS.max_output_tokens > data["qualified_output_tokens"]
        ):
            return False

        def read(path):
            with urllib.request.urlopen(SETTINGS.ollama_base_url.rstrip("/") + path, timeout=0.5) as response:
                return json.loads(response.read(131072))

        if read("/api/version").get("version") != data["qualified_runtime_version"]:
            return False
        installed = {model["name"]: model["digest"] for model in read("/api/tags")["models"]}
        return all(installed.get(name) == digest for name, digest in data["model_digests"].items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def resident_credit(profile, before, after, current, memory_stat, *, now=None):
    """Pure validation of the existing runtime's model and readonly cgroup view."""
    data = profile.data
    if not isinstance(before, list) or len(before) != 1 or before != after:
        return None, 0
    model = before[0]
    if not isinstance(model, dict):
        return None, 0
    name = model.get("name")
    if name not in data.get("model_memory_bytes", {}) or model.get("digest") != data.get("model_digests", {}).get(name):
        return None, 0
    context = model.get("context_length")
    if type(context) is not int or not 0 < context <= data.get("qualified_context_tokens", 0):
        return None, 0
    try:
        expiry = datetime.fromisoformat(model["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry.utcoffset() is None:
            return None, 0
        expires = expiry.timestamp()
        if expires <= (time.time() if now is None else now) + 5:
            return None, 0
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, 0
    inactive = memory_stat.get("inactive_file")
    if (
        type(current) is not int
        or type(inactive) is not int
        or not 0 <= inactive <= current <= data["hardware"]["runtime_memory_bytes"]
    ):
        return None, 0
    # Use the live working set, excluding reclaimable inactive file cache and
    # the explicitly budgeted server overhead. Do not credit virtual/model size.
    allocated = max(0, current - inactive - data["resident_base_reserve_bytes"])
    return name, min(allocated, data["model_memory_bytes"][name])


def capture_resident_credit(profile):
    directory = profile.data.get("resident_memory_path")
    if not directory:
        return None, 0
    try:
        import urllib.request
        from .settings import SETTINGS

        if SETTINGS.context_tokens > profile.data["qualified_context_tokens"]:
            return None, 0

        # Reuse the established private inference transport unchanged. No new
        # endpoint, credentials, model request or additional monitor is installed.
        def models():
            with urllib.request.urlopen(SETTINGS.ollama_base_url.rstrip("/") + "/api/ps", timeout=0.5) as response:
                value = json.loads(response.read(131072))
            fields = ("name", "digest", "context_length", "expires_at")
            return [{key: model.get(key) for key in fields} for model in value.get("models", [])]

        before = models()
        root = Path(directory)
        current = int((root / "memory.current").read_text(encoding="ascii").strip())
        stat = {
            key: int(value)
            for key, value in (line.split() for line in (root / "memory.stat").read_text(encoding="ascii").splitlines())
        }
        return resident_credit(profile, before, models(), current, stat)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, 0  # Unknown residency retains the conservative full budget.


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
        # Admission follows the resolved provider. Ordinary jobs may select a
        # role/automatic routing and deliberately leave requested model empty.
        budget = self.profile.data.get("model_memory_bytes", {}).get(provider.model, 0)
        workload = Workload(
            "inference",
            max(int(job["ram_mb"]) * 1048576, int(budget)) if local else 1048576,
            priority=int(job["priority"]),
            gpu_memory_bytes=int(job["vram_mb"]) * 1048576 if local else 0,
            inference=True,
            model=provider.model if local else None,
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
