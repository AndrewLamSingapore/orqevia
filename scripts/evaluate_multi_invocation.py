"""Evaluate recorded invocation traces; never invokes a model or qualifies production.

The bundled fixture is synthetic. Live quality claims require independently
recorded traces, task-specific oracles, and resource/thermal measurements.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

MODES = ("single", "standard", "deep", "maximum")


def _nonnegative(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a nonnegative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a nonnegative number") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a nonnegative number")
    return number


def evaluate(data):
    """Score exact-answer fixtures, preserving measured vs synthetic provenance."""
    if data.get("provenance") not in ("synthetic_fixture", "recorded_live"):
        raise ValueError("provenance must identify synthetic or recorded live data")
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("at least one case is required")
    totals = {mode: {"correct": 0, "latency_ms": Decimal(0),
                     "cost_usd": Decimal(0), "invocations": 0,
                     "local_invocations": 0} for mode in MODES}
    ids = set()
    for case in data["cases"]:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("case IDs must be unique nonempty strings")
        ids.add(case_id)
        if case.get("oracle") != "exact" or not isinstance(case.get("expected"), str):
            raise ValueError("only a recorded exact-answer oracle is supported")
        runs = case.get("runs")
        if not isinstance(runs, dict) or set(runs) != set(MODES):
            raise ValueError("every case needs all four mode runs")
        for mode in MODES:
            run = runs[mode]
            if not isinstance(run.get("answer"), str):
                raise ValueError("answer must be a string")
            calls = run.get("invocations")
            if not isinstance(calls, list) or not calls:
                raise ValueError("each run needs invocation accounting")
            if mode == "single" and len(calls) != 1:
                raise ValueError("single baseline must have exactly one invocation")
            starts, ends = [], []
            for call in calls:
                for key in ("role", "provider", "model"):
                    if not isinstance(call.get(key), str) or not call[key]:
                        raise ValueError(f"invocation {key} is required")
                start = _nonnegative(call.get("start_ms"), "start_ms")
                end = _nonnegative(call.get("end_ms"), "end_ms")
                if end < start:
                    raise ValueError("end_ms precedes start_ms")
                _nonnegative(call.get("input_tokens"), "input_tokens")
                _nonnegative(call.get("output_tokens"), "output_tokens")
                totals[mode]["cost_usd"] += _nonnegative(call.get("cost_usd"), "cost_usd")
                if call.get("location") not in ("local", "cloud"):
                    raise ValueError("location must be local or cloud")
                totals[mode]["local_invocations"] += call["location"] == "local"
                starts.append(start)
                ends.append(end)
            totals[mode]["correct"] += run["answer"] == case["expected"]
            totals[mode]["latency_ms"] += max(ends) - min(starts)
            totals[mode]["invocations"] += len(calls)
    n = len(data["cases"])
    report = {
        "provenance": data["provenance"],
        "case_count": n,
        "qualification": "NOT_QUALIFIED",
        "limits": ["exact-answer fixtures only", "no thermal or resource measurements",
                   "no production execution or model-quality proof from synthetic data"],
        "modes": {},
    }
    for mode, value in totals.items():
        report["modes"][mode] = {
            "correct": value["correct"],
            "accuracy": round(value["correct"] / n, 4),
            "mean_latency_ms": float(value["latency_ms"] / n),
            "total_cost_usd": str(value["cost_usd"]),
            "invocations": value["invocations"],
            "local_invocations": value["local_invocations"],
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(json.loads(args.trace.read_text(encoding="utf-8"))), indent=2))


if __name__ == "__main__":
    main()
