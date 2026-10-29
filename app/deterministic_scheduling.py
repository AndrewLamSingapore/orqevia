"""Deterministic nonpreemptive single-slot scheduling for formulaic work.

First-principles computation with zero model calls. This is the deterministic
alternative for the formulaic task class that the deep-lane qualification
(gemma3:12b) failed on 2026-10-28: the model produced a schedule that violated
the nonpreemptive single-slot constraint. The solver below reproduces, from
first principles, the exact oracle used by that trial.

Candidate source only. Production dispatch integration is the existing
registry-v1 deterministic lane (`deterministic_operation='schedule_single_slot'`)
and is not deployed until an approved release window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


INTERACTIVE = "interactive"
BACKGROUND = "background"
PRIORITY_CLASSES = (INTERACTIVE, BACKGROUND)
_PRIORITY_RANK = {INTERACTIVE: 0, BACKGROUND: 1}
MAX_JOBS = 100
MAX_TIME = 1_000_000


class SchedulingSpecError(ValueError):
    """Rejected or malformed scheduling specification."""


@dataclass(frozen=True)
class SlotJob:
    name: str
    arrival: int
    duration: int
    priority_class: str
    sequence: int


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchedulingSpecError(f"{field} must be an integer")
    if not 0 <= value <= MAX_TIME:
        raise SchedulingSpecError(f"{field} must be between 0 and {MAX_TIME}")
    return value


def parse_jobs(jobs: Any) -> tuple[SlotJob, ...]:
    """Validate a declarative job list into bounded immutable jobs."""
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= MAX_JOBS:
        raise SchedulingSpecError(f"jobs must be a non-empty list of at most {MAX_JOBS}")
    parsed: list[SlotJob] = []
    for sequence, raw in enumerate(jobs):
        if not isinstance(raw, dict):
            raise SchedulingSpecError("each job must be an object")
        name = raw.get("name")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 32
            or not (name.replace("_", "").isalnum())
            or not name[0].isalpha()
        ):
            raise SchedulingSpecError("job name must be an alphanumeric identifier")
        priority_class = raw.get("priority_class", BACKGROUND)
        if priority_class not in PRIORITY_CLASSES:
            raise SchedulingSpecError("priority_class must be interactive or background")
        parsed.append(
            SlotJob(
                name=name,
                arrival=_nonnegative_int(raw.get("arrival"), "arrival"),
                duration=_nonnegative_int(raw.get("duration"), "duration"),
                priority_class=priority_class,
                sequence=sequence,
            )
        )
    names = [job.name for job in parsed]
    if len(set(names)) != len(names):
        raise SchedulingSpecError("job names must be unique")
    return tuple(parsed)


def solve_schedule(jobs: Any) -> dict[str, int | bool]:
    """Exact nonpreemptive single-slot schedule.

    One slot processes jobs without interruption. At every release point the
    slot takes, among all arrived jobs, the highest priority class
    (interactive before background), then earliest arrival, then declaration
    order. Waiting never consumes the execution budget.
    """
    pending = list(parse_jobs(jobs))
    result: dict[str, int | bool] = {}
    now = 0
    while pending:
        next_arrival = min(job.arrival for job in pending)
        if now < next_arrival:
            now = next_arrival
        arrived = [job for job in pending if job.arrival <= now]
        chosen = min(
            arrived,
            key=lambda job: (_PRIORITY_RANK[job.priority_class], job.arrival, job.sequence),
        )
        pending.remove(chosen)
        start = max(now, chosen.arrival)
        finish = start + chosen.duration
        result[f"{chosen.name}_start"] = start
        result[f"{chosen.name}_finish"] = finish
        result[f"{chosen.name}_wait"] = start - chosen.arrival
        now = finish
    result["waiting_consumes_execution_budget"] = False
    return result


def solve_from_context(context: Any) -> dict[str, int | bool]:
    """Solve a schedule from a JSON context carrying a ``jobs`` list."""
    if isinstance(context, bytes):
        try:
            context = context.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchedulingSpecError("context must be UTF-8 JSON") from exc
    if isinstance(context, str):
        try:
            payload = json.loads(context)
        except json.JSONDecodeError as exc:
            raise SchedulingSpecError("context must be a single JSON object") from exc
    else:
        payload = context
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise SchedulingSpecError("context must encode a JSON object with a jobs list")
    return solve_schedule(payload["jobs"])


def check_answer(answer: Any, jobs: Any, required_keys: Any = None) -> dict[str, Any]:
    """Exact cross-check gate for any produced schedule.

    A produced schedule is accepted only when it is exactly equal, including
    key set, key order semantics and value types, to the deterministic
    solution. This is the guard that would have rejected the 2026-10-28 deep
    failure, which violated the occupied-slot constraint.
    """
    expected = solve_schedule(jobs)
    if required_keys is not None:
        if not isinstance(required_keys, (list, tuple)) or not required_keys:
            raise SchedulingSpecError("required_keys must be a non-empty sequence")
        required = list(required_keys)
        if set(required) - set(expected):
            raise SchedulingSpecError("required_keys reference unknown schedule fields")
        expected = {key: expected[key] for key in required}
    if not isinstance(answer, dict):
        return {"match": False, "expected": expected, "observed": None, "reason": "answer-is-not-an-object"}
    if set(answer) != set(expected):
        return {"match": False, "expected": expected, "observed": answer, "reason": "answer-keys-mismatch"}
    if any(type(answer[key]) is not type(expected[key]) or answer[key] != expected[key] for key in expected):
        return {"match": False, "expected": expected, "observed": answer, "reason": "answer-values-or-types-mismatch"}
    return {"match": True, "expected": expected, "observed": answer, "reason": "exact-match"}


def oracle_agreement(expected: dict[str, Any], jobs: Any) -> dict[str, Any]:
    """Prove a fixed oracle equals the first-principles solution on its keys."""
    solved = solve_schedule(jobs)
    agreement = all(solved.get(key) == value for key, value in expected.items())
    return {
        "agreement": bool(agreement),
        "expected": expected,
        "deterministic": {key: solved.get(key) for key in expected},
    }
