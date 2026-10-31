"""Patient inference budgets and admission observations for the existing queue.

No network calls, workers, model downgrades, or production configuration changes.
All durations are seconds. Queue waiting never spends an execution budget.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path


def bounded_setting(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        if not math.isfinite(value):
            raise ValueError()
    except (TypeError, ValueError):
        value = default
    return min(high, max(low, value))


@dataclass(frozen=True)
class ExecutionBudget:
    first_progress: float
    stalled_progress: float
    active: float
    persistence: float
    total: float

    @classmethod
    def for_job(cls, job: dict) -> ExecutionBudget:
        requested = max(0.01, float(job.get("timeout_seconds") or 300))
        background = int(job.get("priority", 50)) < 50
        active = requested
        first = min(requested, bounded_setting("ORQEVIA_FIRST_PROGRESS_SECONDS", 600, 1, 1800))
        stalled = min(requested, bounded_setting("ORQEVIA_STALLED_PROGRESS_SECONDS", 120, 1, 1800))
        persistence = bounded_setting("ORQEVIA_PERSISTENCE_SECONDS", 30, 1, 120)
        # Patient background jobs have a finite safety ceiling, not a short
        # overall deadline measured from submission. Explicit per-job budgets
        # remain authoritative; callers must opt into a longer active budget.
        ceiling = (
            bounded_setting("ORQEVIA_BACKGROUND_TOTAL_SECONDS", 3600, 60, 86400)
            if background
            else requested + first + persistence
        )
        return cls(first, stalled, active, persistence, min(ceiling, first + active + persistence))


def resource_observation() -> dict:
    """Observe Linux headroom; absence remains UNKNOWN, never invented zero.

    HOME_ECO reserve must be explicitly calibrated/configured. No guessed
    universal RAM, CPU, power, or temperature threshold is enabled here.
    """
    result = {
        "available_mib": None,
        "minimum_available_mib": None,
        "admission": "UNCONFIGURED",
        "source": "/proc/meminfo",
    }
    try:
        lines = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
        available = next(float(line.split()[1]) / 1024 for line in lines if line.startswith("MemAvailable:"))
        result["available_mib"] = round(available, 3)
    except (OSError, ValueError, StopIteration):
        result["admission"] = "UNKNOWN"
        return result
    raw = os.getenv("ORQEVIA_HOME_ECO_MIN_AVAILABLE_MIB")
    reserve: float | None = None
    if raw is None:
        from .compute_profile import runtime_compute_profile

        profile = runtime_compute_profile()
        if profile:
            reserve = float(profile["minimum_available_mib"])
        else:
            return result
    else:
        try:
            reserve = float(raw)
            if not math.isfinite(reserve) or reserve <= 0:
                raise ValueError()
        except ValueError:
            result["admission"] = "INVALID_CONFIGURATION"
            return result
    result.update(
        minimum_available_mib=reserve, admission="WAITING_FOR_CAPACITY" if available < reserve else "AVAILABLE"
    )
    return result
