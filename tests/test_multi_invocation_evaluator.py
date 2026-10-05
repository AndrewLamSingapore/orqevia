"""Deterministic trace scoring only; these tests do not invoke an AI provider."""
import copy
import json
from pathlib import Path

import pytest

from scripts.evaluate_multi_invocation import evaluate


FIXTURE = Path(__file__).parent / "fixtures" / "multi_invocation_synthetic.json"


def test_synthetic_fixture_keeps_quality_claim_unqualified():
    report = evaluate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert report["provenance"] == "synthetic_fixture"
    assert report["qualification"] == "NOT_QUALIFIED"
    assert report["case_count"] == 3
    assert report["modes"]["single"]["correct"] == 1
    assert report["modes"]["standard"]["correct"] == 1
    assert report["modes"]["deep"]["correct"] == 3
    assert report["modes"]["maximum"]["correct"] == 3
    assert report["modes"]["maximum"]["total_cost_usd"] > report["modes"]["deep"]["total_cost_usd"]
    assert report["modes"]["maximum"]["mean_latency_ms"] > report["modes"]["deep"]["mean_latency_ms"]


def test_missing_mode_or_wrong_single_call_count_rejected():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    missing = copy.deepcopy(fixture)
    del missing["cases"][0]["runs"]["maximum"]
    with pytest.raises(ValueError, match="all four"):
        evaluate(missing)
    duplicate = copy.deepcopy(fixture)
    duplicate["cases"][0]["runs"]["single"]["invocations"].append(
        duplicate["cases"][0]["runs"]["single"]["invocations"][0]
    )
    with pytest.raises(ValueError, match="exactly one"):
        evaluate(duplicate)


def test_negative_cost_and_reversed_timing_rejected():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bad_cost = copy.deepcopy(fixture)
    bad_cost["cases"][0]["runs"]["single"]["invocations"][0]["cost_usd"] = "-0.01"
    with pytest.raises(ValueError, match="cost_usd"):
        evaluate(bad_cost)
    bad_time = copy.deepcopy(fixture)
    bad_time["cases"][0]["runs"]["single"]["invocations"][0]["end_ms"] = 0
    bad_time["cases"][0]["runs"]["single"]["invocations"][0]["start_ms"] = 1
    with pytest.raises(ValueError, match="precedes"):
        evaluate(bad_time)


def test_non_exact_oracle_cannot_get_false_quality_pass():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["cases"][0]["oracle"] = "model_judge"
    with pytest.raises(ValueError, match="exact-answer"):
        evaluate(fixture)
