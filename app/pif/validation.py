"""Chronological entity-separated validation; no synthetic accuracy claims."""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from .core import History, digest, estimate_markov, integer, timestamp, validate_histories


def chronological_validation(
    histories: Iterable[History],
    *,
    states: Sequence[str],
    absorbing_states: Sequence[str] = (),
    alpha: float = 0.5,
    allowed_edges: Iterable[tuple[str, str]] | None = None,
    cutoff: str | None = None,
    min_train_transitions: int = 30,
    min_test_transitions: int = 20,
) -> dict[str, Any]:
    """Evaluate one-step state predictions with a fixed, pre-test training fit.

    Entire histories ending before cutoff train; entirely later entities test.
    Crossing entities are excluded. Duplicate IDs/events fail before partition.
    No iterative fit on held-out outcomes occurs. Brier here is the sum across
    all classes (range 0..2), not the binary half-scaled convention.
    """
    integer(min_train_transitions, minimum=1)
    integer(min_test_transitions, minimum=1)
    rows = sorted(validate_histories(histories), key=lambda h: (h.observations[0].timestamp, h.entity_id))
    edges = tuple(allowed_edges) if allowed_edges is not None else None
    base = {
        "status": "INSUFFICIENT_DATA",
        "method": "CHRONOLOGICAL_ENTITY_DISJOINT",
        "metric_definition": "MULTICLASS_BRIER_SUM_0_TO_2",
        "production_quality_validated": False,
        "cutoff": None,
        "minimum_train_transitions": min_train_transitions,
        "minimum_test_transitions": min_test_transitions,
        "train_entities": 0,
        "test_entities": 0,
        "crossing_entities_excluded": 0,
        "train_transitions": 0,
        "test_transitions": 0,
        "evidence_kinds": sorted({h.evidence_kind for h in rows}),
        "calibration_interpretation": "DIAGNOSTIC_ONLY_NOT_PROMOTION",
    }
    if len(rows) < 2:
        return {**base, "reason": "TOO_FEW_INDEPENDENT_ENTITIES"}
    boundary = timestamp(cutoff) if cutoff else rows[max(1, int(len(rows) * 0.8))].observations[0].timestamp
    train = [h for h in rows if h.observations[-1].timestamp < boundary]
    test = [h for h in rows if h.observations[0].timestamp >= boundary]
    count = lambda hs: sum(max(0, len(h.observations) - 1) for h in hs)
    base.update(
        cutoff=boundary,
        train_entities=len(train),
        test_entities=len(test),
        crossing_entities_excluded=len(rows) - len(train) - len(test),
        train_transitions=count(train),
        test_transitions=count(test),
        train_evidence_digest=digest([h.as_dict() for h in train]),
        test_evidence_digest=digest([h.as_dict() for h in test]),
    )
    if base["train_transitions"] < min_train_transitions or base["test_transitions"] < min_test_transitions:
        return {**base, "reason": "MINIMUM_CHRONOLOGICAL_EVIDENCE_NOT_MET"}
    model = estimate_markov(train, states=states, absorbing_states=absorbing_states, alpha=alpha, allowed_edges=edges)
    # Score global destination frequencies from TRAIN ONLY as a second baseline.
    total = model.transition_count
    destinations = [sum(row[i] for row in model.counts) for i in range(len(model.states))]
    frequency = [(n + alpha) / (total + alpha * len(model.states)) for n in destinations]
    scores: dict[str, list[float]] = {
        "markov_brier": [],
        "frequency_brier": [],
        "persistence_brier": [],
        "markov_log_loss": [],
        "frequency_log_loss": [],
        "persistence_log_loss": [],
    }
    bins = [
        {"lower": i / 10, "upper": (i + 1) / 10, "count": 0, "predicted_sum": 0.0, "observed_sum": 0.0}
        for i in range(10)
    ]
    unseen_sources = set()
    outcomes: list[tuple[str, str]] = []
    for history in test:
        for previous, target in zip(history.observations, history.observations[1:]):
            if previous.state not in model.states or target.state not in model.states:
                raise ValueError("unrecognized held-out state")
            source_index = model.states.index(previous.state)
            target_index = model.states.index(target.state)
            markov = model.matrix[source_index]
            if not sum(model.counts[source_index]) and previous.state not in model.absorbing_states:
                unseen_sources.add(previous.state)
            persistence = [float(i == source_index) for i in range(len(model.states))]
            for name, probs in (("markov", markov), ("frequency", frequency), ("persistence", persistence)):
                scores[name + "_brier"].append(
                    math.fsum((p - float(i == target_index)) ** 2 for i, p in enumerate(probs))
                )
                scores[name + "_log_loss"].append(-math.log(max(probs[target_index], 1e-15)))
            for i, probability in enumerate(markov):
                bin_ = bins[min(9, int(probability * 10))]
                bin_["count"] += 1
                bin_["predicted_sum"] += probability
                bin_["observed_sum"] += float(i == target_index)
            outcomes.append((target.timestamp, target.state))
    results = {name: math.fsum(values) / len(values) for name, values in scores.items()}
    calibration = [
        {
            "lower": b["lower"],
            "upper": b["upper"],
            "count": b["count"],
            "mean_probability": b["predicted_sum"] / b["count"] if b["count"] else None,
            "observed_frequency": b["observed_sum"] / b["count"] if b["count"] else None,
        }
        for b in bins
    ]
    outcomes.sort()
    halfway = len(outcomes) // 2

    def frequencies(values):
        return {state: sum(outcome == state for _, outcome in values) / len(values) for state in model.states}

    earlier = frequencies(outcomes[:halfway])
    later = frequencies(outcomes[halfway:])
    shift = 0.5 * math.fsum(abs(earlier[s] - later[s]) for s in model.states)
    observed_frequency = frequencies(outcomes)
    train_frequency = dict(zip(model.states, (n / total for n in destinations)))
    train_test_shift = 0.5 * math.fsum(abs(train_frequency[s] - observed_frequency[s]) for s in model.states)
    calibration_count = sum(b["count"] for b in calibration)
    calibration_error = (
        math.fsum(b["count"] * abs(b["mean_probability"] - b["observed_frequency"]) for b in calibration if b["count"])
        / calibration_count
    )
    return {
        **base,
        "status": "EVALUATED",
        "reason": "HELD_OUT_DIAGNOSTICS_RECORDED",
        "training_model_digest": model.version,
        "scores": results,
        "calibration_bins": calibration,
        "unseen_test_source_states": sorted(unseen_sources),
        "beats_frequency_brier": results["markov_brier"] < results["frequency_brier"],
        "beats_persistence_brier": results["markov_brier"] < results["persistence_brier"],
        "pooled_class_bin_expected_calibration_error": calibration_error,
        "train_outcome_frequency": train_frequency,
        "test_outcome_frequency": observed_frequency,
        "train_test_outcome_shift_total_variation": train_test_shift,
        "held_out_outcome_shift_total_variation": shift,
        "shift_scope": "TWO_CHRONOLOGICAL_HALVES_DESCRIPTIVE_NOT_SIGNIFICANCE_TEST",
        "test_period": [test[0].observations[0].timestamp, max(h.observations[-1].timestamp for h in test)],
    }
