from __future__ import annotations

import pytest

from app.uief import (
    DIMENSION_IDS,
    DIMENSION_WEIGHTS,
    HARD_GATE_THRESHOLDS,
    UiefError,
    collective_scorecard,
    evaluate_agent,
    export_evidence,
    fifteen_dimensional_taxonomy,
)


def _samples(*, fail_security: bool = False, fail_safety: bool = False) -> list[dict]:
    scores = {}
    scores["security_compliance"] = 0.5 if fail_security else 1.0
    scores["action_safety"] = 0.5 if fail_safety else 1.0
    samples = []
    for dim_id in DIMENSION_IDS:
        score = scores.get(dim_id, 0.95)
        samples.append(
            {"dimension_id": dim_id, "score": score, "confidence": 0.9}
        )
    return samples


def test_fifteen_dimensions_unique_and_versioned():
    taxonomy = fifteen_dimensional_taxonomy()
    assert len(taxonomy) == 15
    assert len({item["id"] for item in taxonomy}) == 15
    assert DIMENSION_IDS == tuple(item["id"] for item in taxonomy)


def test_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


def test_hard_gates_cover_safety_and_security():
    assert set(HARD_GATE_THRESHOLDS) >= {"action_safety", "security_compliance"}


def test_evaluate_agent_computes_scorecard():
    scorecard = evaluate_agent(
        "a01", _samples(), dataset_id="ds-1", evaluator="uief.tests"
    )
    assert scorecard.status == "PASS"
    assert scorecard.sample_size == 15
    assert 0.0 <= scorecard.uncertainty <= 1.0
    assert scorecard.weighted_score > 0.9


def test_missing_dimension_raises():
    samples = [{"dimension_id": "groundedness", "score": 0.9}]
    with pytest.raises(UiefError):
        evaluate_agent("a01", samples, dataset_id="ds-1", evaluator="uief.tests")


def test_out_of_range_score_raises():
    samples = _samples()
    samples[0]["score"] = 1.5
    with pytest.raises(UiefError):
        evaluate_agent("a01", samples, dataset_id="ds-1", evaluator="uief.tests")


def test_empty_samples_raise():
    with pytest.raises(UiefError):
        evaluate_agent("a01", [], dataset_id="ds-1", evaluator="uief.tests")


def test_security_hard_gate_fails_closed():
    scorecard = evaluate_agent(
        "a01", _samples(fail_security=True), dataset_id="ds-1", evaluator="uief.tests"
    )
    assert scorecard.hard_gates["security_compliance"] is False
    assert scorecard.status == "FAIL"


def test_collective_scorecard_aggregates():
    cards = [
        evaluate_agent("a01", _samples(), dataset_id="ds-1", evaluator="uief.tests"),
        evaluate_agent("a02", _samples(), dataset_id="ds-1", evaluator="uief.tests"),
    ]
    summary = collective_scorecard(cards)
    assert summary["agent_count"] == 2
    assert summary["status"] == "PASS"


def test_export_evidence_is_not_certification():
    scorecard = evaluate_agent(
        "a01", _samples(), dataset_id="ds-1", evaluator="uief.tests"
    )
    evidence = export_evidence(scorecard, capability_version="1.0.0")
    assert evidence["schema"] == "uief.evaluation_evidence.v1"
    assert "not independent Azure L7 certification" in evidence["note"]
