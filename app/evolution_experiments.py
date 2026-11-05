"""Bounded native workflow experiments, with no model calls or production changes.

The frozen synthetic evaluator is separate from three fixed candidate workflows.
Candidates receive job inputs only, never expected outputs. This is functional
separation, not a sandbox for untrusted self-modifying Python. Candidate code and
the evaluator are release-reviewed source; callers cannot supply executable code,
alter permissions, change scores, or choose a production policy through this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import heapq
import json
from pathlib import Path
import statistics
import time

from .deterministic_scheduling import parse_jobs, solve_schedule


SCHEMA = "orqevia.evolution-experiment.v1"
REPETITIONS = 128
FROZEN_SUITE_SHA256 = "a080d94fdd8c182e8281ffbc981b7e7fe40c1da84baf92b6fcaf66dab8e1bc12"


@dataclass(frozen=True)
class FrozenCase:
    name: str
    split: str
    jobs: tuple[tuple[str, int, int, str], ...]
    # Explicit independently calculated (name,start,finish,wait) values.
    expected: tuple[tuple[str, int, int, int], ...]

    def inputs(self):
        return [dict(zip(("name", "arrival", "duration", "priority_class"), row)) for row in self.jobs]

    def answer(self):
        result = {
            f"{name}_{field}": value
            for name, *values in self.expected
            for field, value in zip(("start", "finish", "wait"), values)
        }
        return {**result, "waiting_consumes_execution_budget": False}


# Versioned evaluation data, not examples made by the candidate under assessment.
# Held-out cases differ in input values, order, count and arrival shapes.
_CASES = (
    FrozenCase(
        "idle_gap",
        "development",
        (("Da", 0, 4, "background"), ("Db", 10, 2, "interactive")),
        (("Da", 0, 4, 0), ("Db", 10, 12, 0)),
    ),
    FrozenCase(
        "same_class_fifo",
        "development",
        (("Ea", 0, 5, "background"), ("Eb", 0, 3, "background"), ("Ec", 0, 2, "background")),
        (("Ea", 0, 5, 0), ("Eb", 5, 8, 5), ("Ec", 8, 10, 8)),
    ),
    FrozenCase(
        "queued_priority",
        "development",
        (("Fa", 0, 6, "background"), ("Fb", 1, 5, "background"), ("Fc", 2, 1, "interactive")),
        (("Fa", 0, 6, 0), ("Fc", 6, 7, 4), ("Fb", 7, 12, 6)),
    ),
    FrozenCase(
        "occupied_slot",
        "development",
        (("Ga", 0, 10, "background"), ("Gb", 3, 2, "interactive"), ("Gc", 4, 1, "background")),
        (("Ga", 0, 10, 0), ("Gb", 10, 12, 7), ("Gc", 12, 13, 8)),
    ),
    FrozenCase(
        "simultaneous_classes",
        "development",
        (("Ha", 0, 4, "background"), ("Hb", 0, 2, "interactive"), ("Hc", 0, 1, "background")),
        (("Hb", 0, 2, 0), ("Ha", 2, 6, 2), ("Hc", 6, 7, 6)),
    ),
    FrozenCase(
        "zero_duration",
        "development",
        (("Ja", 0, 0, "background"), ("Jb", 0, 0, "interactive"), ("Jc", 0, 2, "background")),
        (("Jb", 0, 0, 0), ("Ja", 0, 0, 0), ("Jc", 0, 2, 0)),
    ),
    FrozenCase(
        "two_waiting_interactive",
        "held_out",
        (
            ("Ka", 5, 7, "background"),
            ("Kb", 6, 4, "background"),
            ("Kc", 8, 2, "interactive"),
            ("Kd", 9, 1, "interactive"),
        ),
        (("Ka", 5, 12, 0), ("Kc", 12, 14, 4), ("Kd", 14, 15, 5), ("Kb", 15, 19, 9)),
    ),
    FrozenCase(
        "future_priority_cannot_idle",
        "held_out",
        (("La", 0, 3, "background"), ("Lb", 8, 4, "interactive"), ("Lc", 5, 2, "background")),
        (("La", 0, 3, 0), ("Lc", 5, 7, 0), ("Lb", 8, 12, 0)),
    ),
    FrozenCase(
        "arrival_on_release",
        "held_out",
        (
            ("Ma", 0, 2, "background"),
            ("Mb", 1, 5, "background"),
            ("Mc", 1, 1, "interactive"),
            ("Md", 3, 2, "interactive"),
            ("Me", 3, 1, "background"),
        ),
        (("Ma", 0, 2, 0), ("Mc", 2, 3, 1), ("Md", 3, 5, 0), ("Mb", 5, 10, 4), ("Me", 10, 11, 7)),
    ),
    FrozenCase(
        "zero_duration_and_ties",
        "held_out",
        (
            ("Na", 2, 0, "background"),
            ("Nb", 2, 2, "interactive"),
            ("Nc", 2, 1, "interactive"),
            ("Nd", 2, 4, "background"),
        ),
        (("Nb", 2, 4, 0), ("Nc", 4, 5, 2), ("Na", 5, 5, 3), ("Nd", 5, 9, 3)),
    ),
    FrozenCase(
        "finite_interactive_burst",
        "held_out",
        (
            ("Pa", 0, 8, "background"),
            ("Pb", 1, 3, "background"),
            ("Pc", 2, 2, "interactive"),
            ("Pd", 4, 3, "interactive"),
            ("Pe", 7, 1, "interactive"),
            ("Pf", 9, 2, "background"),
        ),
        (
            ("Pa", 0, 8, 0),
            ("Pc", 8, 10, 6),
            ("Pd", 10, 13, 6),
            ("Pe", 13, 14, 6),
            ("Pb", 14, 17, 13),
            ("Pf", 17, 19, 8),
        ),
    ),
    FrozenCase(
        "all_interactive",
        "held_out",
        (("Qa", 6, 2, "interactive"), ("Qb", 6, 0, "interactive"), ("Qc", 7, 3, "interactive")),
        (("Qa", 6, 8, 0), ("Qb", 8, 8, 2), ("Qc", 8, 11, 1)),
    ),
    FrozenCase(
        "late_start",
        "held_out",
        (("Ra", 20, 1, "background"), ("Rb", 21, 2, "background"), ("Rc", 21, 1, "interactive")),
        (("Ra", 20, 21, 0), ("Rc", 21, 22, 0), ("Rb", 22, 24, 1)),
    ),
    FrozenCase(
        "declaration_not_arrival_order",
        "held_out",
        (
            ("Sa", 9, 2, "background"),
            ("Sb", 0, 3, "background"),
            ("Sc", 2, 1, "interactive"),
            ("Sd", 1, 5, "background"),
        ),
        (("Sb", 0, 3, 0), ("Sc", 3, 4, 1), ("Sd", 4, 9, 3), ("Sa", 9, 11, 0)),
    ),
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _suite_payload():
    return [dict(name=case.name, split=case.split, inputs=case.inputs(), oracle=case.answer()) for case in _CASES]


def _validate_suite():
    if _digest(_suite_payload()) != FROZEN_SUITE_SHA256:
        raise ValueError("Frozen experiment evaluator integrity mismatch")
    hashes = {
        split: {_digest(case.inputs()) for case in _CASES if case.split == split}
        for split in ("development", "held_out")
    }
    if hashes["development"] & hashes["held_out"]:
        raise ValueError("Development/held-out input overlap")
    return hashes


def _fifo(jobs):
    now, result = 0, {}
    for job in sorted(parse_jobs(jobs), key=lambda item: (item.arrival, item.sequence)):
        start = max(now, job.arrival)
        now = start + job.duration
        result.update({f"{job.name}_start": start, f"{job.name}_finish": now, f"{job.name}_wait": start - job.arrival})
    return {**result, "waiting_consumes_execution_budget": False}


def _priority_heap(jobs):
    pending = sorted(parse_jobs(jobs), key=lambda item: (item.arrival, item.sequence))
    ready, result, now, index = [], {}, 0, 0
    while index < len(pending) or ready:
        if not ready:
            now = max(now, pending[index].arrival)
        while index < len(pending) and pending[index].arrival <= now:
            job = pending[index]
            heapq.heappush(ready, (job.priority_class != "interactive", job.arrival, job.sequence, job))
            index += 1
        job = heapq.heappop(ready)[-1]
        start = now
        now += job.duration
        result.update({f"{job.name}_start": start, f"{job.name}_finish": now, f"{job.name}_wait": start - job.arrival})
    return {**result, "waiting_consumes_execution_budget": False}


def _exact_tool(jobs):
    return solve_schedule(jobs)


# No caller-supplied candidates, plugins, shell commands or model execution.
_CANDIDATES = (
    ("arrival_fifo", _fifo, 1, "Minimal arrival FIFO baseline; does not distinguish interactive work."),
    (
        "release_aware_priority_heap",
        _priority_heap,
        1,
        "Independent priority coordinator using arrivals and a ready heap; adds a scheduler implementation.",
    ),
    (
        "existing_exact_tool",
        _exact_tool,
        0,
        "Reuse the installed deterministic single-slot capability through one direct function call.",
    ),
)


def _judge(answer, expected):
    return (
        type(answer) is dict
        and answer.keys() == expected.keys()
        and all(type(answer[key]) is type(value) and answer[key] == value for key, value in expected.items())
    )


def _valid_execution(answer, inputs):
    if type(answer) is not dict or answer.get("waiting_consumes_execution_budget") is not False:
        return False
    occupied = []
    for job in inputs:
        name, arrival, duration = job["name"], job["arrival"], job["duration"]
        values = [answer.get(f"{name}_{field}") for field in ("start", "finish", "wait")]
        if any(type(value) is not int for value in values):
            return False
        start, finish, wait = values
        if start < arrival or finish != start + duration or wait != start - arrival:
            return False
        if finish > start:
            occupied.append((start, finish))
    occupied.sort()
    return all(occupied[index][1] <= occupied[index + 1][0] for index in range(len(occupied) - 1))


def _evaluate(candidate, cases):
    name, function, new_algorithms, rationale = candidate
    rows, waits, interactive_waits, background_waits = [], [], [], []
    for case in cases:
        # Copy public inputs on every call: mutation cannot alter later cases or the oracle.
        inputs = case.inputs()
        answer = function(inputs)
        valid = _valid_execution(answer, case.inputs())
        correct = valid and _judge(answer, case.answer())
        for job in case.inputs():
            wait = answer.get(f"{job['name']}_wait")
            if type(wait) is int and wait >= 0:
                waits.append(wait)
                (interactive_waits if job["priority_class"] == "interactive" else background_waits).append(wait)
        rows.append(
            {
                "case_id": case.name,
                "input_sha256": _digest(case.inputs()),
                "oracle_sha256": _digest(case.answer()),
                "valid_execution": valid,
                "correct": correct,
                "jobs": len(inputs),
                "answer": answer,
            }
        )
    cpu_samples, wall_samples = [], []
    for _ in range(3):
        began_cpu, began_wall = time.process_time_ns(), time.perf_counter_ns()
        for _ in range(REPETITIONS):
            for case in cases:
                function(case.inputs())
        cpu_samples.append(max(0, time.process_time_ns() - began_cpu))
        wall_samples.append(max(0, time.perf_counter_ns() - began_wall))
    passed = sum(row["correct"] for row in rows)
    useful_jobs = sum(row["jobs"] for row in rows if row["correct"])
    measured_calls = REPETITIONS * len(cases)
    measured_cpu_seconds = statistics.median(cpu_samples) / 1e9
    return {
        "candidate": name,
        "rationale": rationale,
        "cases": len(cases),
        "correct_cases": passed,
        "accuracy": passed / len(cases),
        "valid_executions": sum(row["valid_execution"] for row in rows),
        "useful_completed_jobs": useful_jobs,
        "attempted_jobs": sum(row["jobs"] for row in rows),
        "mean_queue_wait_ticks": statistics.mean(waits),
        "mean_interactive_wait_ticks": statistics.mean(interactive_waits) if interactive_waits else None,
        "mean_background_wait_ticks": statistics.mean(background_waits) if background_waits else None,
        "queue_wait_scope": "SYNTHETIC_SCHEDULE_TIME_UNITS_NOT_LIVE_QUEUE_SECONDS",
        "candidate_cpu_ns_samples": cpu_samples,
        "candidate_wall_ns_samples": wall_samples,
        "calls_per_timing_sample": measured_calls,
        "median_cpu_seconds_per_call": statistics.median(cpu_samples) / measured_calls / 1e9,
        "cpu_seconds_per_correct_workload": measured_cpu_seconds / (REPETITIONS * passed) if passed else None,
        "cpu_seconds_per_useful_completed_job": measured_cpu_seconds / (REPETITIONS * useful_jobs)
        if useful_jobs
        else None,
        "median_wall_seconds_per_call": statistics.median(wall_samples) / measured_calls / 1e9,
        "cpu_timing_limit": "Process CPU clock may be coarse; samples include case-input construction. No speedup claim.",
        "coordination": {
            "candidate_calls_per_workload": 1,
            "output_job_decisions": sum(row["jobs"] for row in rows),
            "new_scheduler_algorithms": new_algorithms,
            "model_calls": 0,
            "network_calls": 0,
        },
        "observations": rows,
    }


def _record(kind, payload, parents=()):
    body = {"kind": kind, "payload": payload, "parents": list(parents)}
    return {"record_id": _digest(body), **body}


def _persist(output_dir, result):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Experiment evidence directory cannot be a symlink")
    target = directory / f"{result['run_id']}.json"
    raw = json.dumps(result, indent=2, allow_nan=False) + "\n"
    # Exclusive creation preserves earlier evidence. No mutable latest file or policy pointer.
    with target.open("x", encoding="utf-8") as stream:
        stream.write(raw)
    return str(target)


def run_experiment(output_dir=None):
    """Run one fixed local scheduling experiment; optionally preserve new evidence.

    No providers, production databases, queues, permissions or configuration are
    read or changed. Retention means an experimental recommendation only.
    """
    fingerprints = _validate_suite()
    development = tuple(case for case in _CASES if case.split == "development")
    held_out = tuple(case for case in _CASES if case.split == "held_out")
    dev_results = [_evaluate(candidate, development) for candidate in _CANDIDATES]
    eligible = [row for row in dev_results if row["correct_cases"] == row["cases"]]
    selected = (
        min(eligible, key=lambda row: (row["coordination"]["new_scheduler_algorithms"], row["candidate"]))
        if eligible
        else None
    )
    # Freeze the proposed winner before inspecting held-out outcomes.
    proposed = selected["candidate"] if selected else None
    held_results = [_evaluate(candidate, held_out) for candidate in _CANDIDATES]
    confirmation = next((row for row in held_results if row["candidate"] == proposed), None)
    accepted = bool(confirmation and confirmation["correct_cases"] == confirmation["cases"])
    baseline = next(row for row in held_results if row["candidate"] == "arrival_fifo")
    gain = confirmation["correct_cases"] - baseline["correct_cases"] if confirmation else 0
    retained = accepted and gain > 0
    source_hashes = {
        "evaluator_and_candidates": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "existing_exact_tool": hashlib.sha256(
            Path(__file__).with_name("deterministic_scheduling.py").read_bytes()
        ).hexdigest(),
    }
    observation = _record(
        "observation",
        {
            "evidence": "operations/efficiency-sweep-20261102/BENCHMARK-SUMMARY-20261102.json",
            "finding": "Historical deep-model synthetic scheduling trial failed its exact quality gate.",
            "comparison_limit": "Historical live-model trial is motivation, not a concurrent performance baseline.",
        },
    )
    hypothesis = _record(
        "hypothesis",
        {
            "statement": "Direct reuse of the exact scheduling tool can satisfy release-point priority semantics without another coordinator.",
            "selection_rule": "Development full correctness, then fewer new scheduler algorithms; held-out may confirm or reject only.",
            "success_rule": "Full held-out correctness plus more correct held-out cases than FIFO.",
            "suite_sha256": FROZEN_SUITE_SHA256,
        },
        (observation["record_id"],),
    )
    experiment = _record(
        "experiment",
        {
            "source_sha256": source_hashes,
            "development": dev_results,
            "held_out": held_results,
            "candidate_selected_before_held_out": proposed,
        },
        (hypothesis["record_id"],),
    )
    conclusion = _record(
        "result",
        {
            "status": "RETAIN_EXPERIMENTAL_METHOD" if retained else "REJECT_NO_VERIFIED_GAIN",
            "candidate": proposed if retained else None,
            "additional_correct_held_out_cases_vs_fifo": gain,
            "production_policy_changed": False,
            "scope": "CONTROLLED_SYNTHETIC_HELDOUT_ONLY",
        },
        (experiment["record_id"],),
    )
    result = {
        "schema": SCHEMA,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": _digest({"suite": FROZEN_SUITE_SHA256, "source": source_hashes}),
        "evidence_scope": "CONTROLLED_SYNTHETIC_HELDOUT_ONLY",
        "suite_sha256": FROZEN_SUITE_SHA256,
        "input_fingerprints": {split: sorted(values) for split, values in fingerprints.items()},
        "development": dev_results,
        "held_out": held_results,
        "selection": conclusion["payload"],
        "records": [observation, hypothesis, experiment, conclusion],
        "limitations": [
            "Hand-authored, non-adversarial synthetic cases; no claim of unseen real-mission generalization.",
            "Fixed workflows, not arbitrary code generation or autonomous evaluator modification.",
            "No new model inference; the historical model result is not a simultaneous benchmark.",
            "Wait ticks are simulated; CPU/wall observations do not establish live throughput gains.",
            "Existing exact tool already exists; retaining this method does not change production routing.",
        ],
        "next_experiment": "Evaluate representative owner-supplied, independently withheld scheduling missions before any routing change.",
        "production_policy_changed": False,
        "financial_actions": 0,
        "network_calls": 0,
        "model_calls": 0,
    }
    result["run_id"] = _digest(result)
    if output_dir is not None:
        result["artifact_path"] = _persist(output_dir, result)
    return result
