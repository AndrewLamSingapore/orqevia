#!/usr/bin/env python3
"""Compare two structured performance receipts against explicit guardrails.

The comparator never makes requests or changes the host. Exit codes: 0 pass,
1 measured regression, 2 invalid/incomparable evidence or policy.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    """A receipt cannot support the requested comparison."""


def _at(document: dict[str, Any], path: str) -> Any:
    if not path or any(not segment for segment in path.split(".")):
        raise EvidenceError(f"invalid metric path: {path!r}")
    value: Any = document
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            raise EvidenceError(f"missing field: {path}")
        value = value[segment]
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise EvidenceError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise EvidenceError(f"{label} must be a finite number")
    return result


def _metric(value: Any, spec: dict[str, Any], label: str) -> tuple[float, int]:
    aggregate = spec.get("aggregate", "value")
    if aggregate == "value":
        return _number(value, label), 1
    if aggregate not in {"median", "p95"}:
        raise EvidenceError(f"{label}: unsupported aggregate {aggregate!r}")
    if not isinstance(value, list) or not value:
        raise EvidenceError(f"{label}: expected a nonempty sample array")
    samples = [_number(item, f"{label}[{index}]") for index, item in enumerate(value)]
    min_samples = spec.get("min_samples", 3)
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise EvidenceError(f"{label}: min_samples must be a positive integer")
    if len(samples) < min_samples:
        raise EvidenceError(f"{label}: {len(samples)} samples, requires {min_samples}")
    if aggregate == "median":
        return statistics.median(samples), len(samples)
    ordered = sorted(samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1], len(samples)


def compare(
    before: dict[str, Any], after: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    if not all(isinstance(item, dict) for item in (before, after, policy)):
        raise EvidenceError("receipts and policy must be JSON objects")
    if policy.get("schema_version") != 1:
        raise EvidenceError("policy schema_version must be 1")
    comparisons = policy.get("comparability", [])
    if not isinstance(comparisons, list) or not all(isinstance(p, str) for p in comparisons):
        raise EvidenceError("comparability must be an array of field paths")
    for path in comparisons:
        if _at(before, path) != _at(after, path):
            raise EvidenceError(f"incomparable receipts: {path} differs")
    specs = policy.get("metrics")
    if not isinstance(specs, list) or not specs:
        raise EvidenceError("policy needs at least one metric")
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
            raise EvidenceError("each metric requires a path")
        path = spec["path"]
        if path in seen:
            raise EvidenceError(f"duplicate metric path: {path}")
        seen.add(path)
        direction = spec.get("direction")
        if direction not in {"lower", "higher"}:
            raise EvidenceError(f"{path}: direction must be lower or higher")
        rel = _number(spec.get("relative_tolerance", 0), f"{path}.relative_tolerance")
        absolute = _number(spec.get("absolute_tolerance", 0), f"{path}.absolute_tolerance")
        if not 0 <= rel < 1 or absolute < 0:
            raise EvidenceError(f"{path}: tolerances must be nonnegative; relative < 1")
        prior, before_n = _metric(_at(before, path), spec, f"before.{path}")
        current, after_n = _metric(_at(after, path), spec, f"after.{path}")
        if direction == "lower":
            limit = prior + abs(prior) * rel + absolute
            passed = current <= limit
        else:
            limit = prior - abs(prior) * rel - absolute
            passed = current >= limit
        results.append({
            "path": path, "direction": direction, "aggregate": spec.get("aggregate", "value"),
            "before": prior, "after": current, "before_samples": before_n,
            "after_samples": after_n, "limit": limit, "passed": passed,
        })
    return {"schema_version": 1, "passed": all(r["passed"] for r in results), "metrics": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("policy", type=Path)
    args = parser.parse_args(argv)
    try:
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in (args.before, args.after, args.policy)]
        result = compare(*documents)
    except (OSError, json.JSONDecodeError, EvidenceError) as exc:
        print(json.dumps({"schema_version": 1, "passed": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
