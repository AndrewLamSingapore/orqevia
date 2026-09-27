"""Held-out deterministic evaluation for the isolated metacognitive candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import tracemalloc

from app.metacognition import Evidence, EpistemicState, assess, brier_score, expected_calibration_error


CASES = (
    ("verified tool fact", [Evidence("e1", "p", True, "deterministic_tool", 1, True, True)], EpistemicState.VERIFIED_FACT),
    ("primary support", [Evidence("e2", "p", True, "primary_record", 1)], EpistemicState.SUPPORTED_FACT),
    ("unsupported assertion", [Evidence("e3", "p", True, "unsupported_assertion", 1)], EpistemicState.UNKNOWN),
    ("model inference", [Evidence("e4", "p", True, "model_inference", 1)], EpistemicState.INFERENCE),
    ("missing evidence", [], EpistemicState.UNKNOWN),
    ("equal contradiction", [Evidence("e5", "p", True, "primary_record", 1), Evidence("e6", "p", False, "primary_record", 2)], EpistemicState.CONTRADICTED),
    ("counterevidence", [Evidence("e7", "p", False, "deterministic_tool", 2)], EpistemicState.CONTRADICTED),
    ("secondary support", [Evidence("e8", "p", True, "secondary_summary", 2)], EpistemicState.SUPPORTED_FACT),
)


def _baseline(evidence):
    # Preserved pre-candidate behavior proxy: any syntactically present claim was
    # treated as supported, with no contradiction or unknown distinction.
    return EpistemicState.SUPPORTED_FACT if evidence else EpistemicState.UNKNOWN


def evaluate() -> dict:
    tracemalloc.start(); start = time.perf_counter()
    candidate = [assess("p", evidence).state for _, evidence, _ in CASES]
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    baseline = [_baseline(evidence) for _, evidence, _ in CASES]
    expected = [expected for _, _, expected in CASES]
    candidate_correct = sum(a == b for a, b in zip(candidate, expected))
    baseline_correct = sum(a == b for a, b in zip(baseline, expected))
    predictions = [(1.0 if actual == EpistemicState.VERIFIED_FACT else .75 if actual == EpistemicState.SUPPORTED_FACT else .35 if actual == EpistemicState.INFERENCE else 0.0,
                    expected in {EpistemicState.VERIFIED_FACT, EpistemicState.SUPPORTED_FACT})
                   for actual, expected in zip(candidate, expected)]
    rows = [{"case": name, "expected": target.value, "baseline": old.value,
             "candidate": new.value, "pass": new == target}
            for (name, _, target), old, new in zip(CASES, baseline, candidate)]
    return {
        "schema_version": "1.0", "evaluation_class": "HELD_OUT_DETERMINISTIC",
        "sample_count": len(CASES), "rows": rows,
        "baseline": {"correct": baseline_correct, "accuracy": baseline_correct / len(CASES)},
        "candidate": {"correct": candidate_correct, "accuracy": candidate_correct / len(CASES),
                      "brier_score": brier_score(predictions),
                      "expected_calibration_error": expected_calibration_error(predictions, 4),
                      "latency_ms": round(elapsed * 1000, 4), "peak_memory_bytes": peak},
        "unknown_detection": all(candidate[i] == expected[i] for i in (2, 4)),
        "contradiction_detection": all(candidate[i] == expected[i] for i in (5, 6)),
        "passed": candidate_correct == len(CASES) and candidate_correct > baseline_correct,
        "limitations": ["synthetic deterministic cases", "not production-proven", "small calibration sample"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate()
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if result["passed"] else 1)
