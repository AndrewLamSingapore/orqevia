from app.historical_intelligence import replay, validate_timeline
from app.predictive_intelligence import evaluate_last_value_baseline


def _records():
    return [
        {"event_id": "b", "observed_at": "2026-01-02T00:00:00+00:00", "ingested_at": "2026-01-03T00:00:00+00:00", "source": "S", "magnitude": 4.0, "kind": "earthquake"},
        {"event_id": "a", "observed_at": "2026-01-01T00:00:00+00:00", "ingested_at": "2026-01-02T00:00:00+00:00", "source": "S", "magnitude": 3.0, "kind": "earthquake"},
    ]


def test_timeline_is_ordered_and_has_provenance():
    result = validate_timeline(_records())
    assert result["ordering_ok"] is True
    assert result["missing_provenance"] == 0
    assert [r["event_id"] for r in replay(_records())] == ["a", "b"]


def test_baseline_forecast_is_chronological_and_measured():
    series = [("2026-01-01T00:00:00Z", 1.0), ("2026-01-02T00:00:00Z", 2.0), ("2026-01-03T00:00:00Z", 3.0),
              ("2026-01-04T00:00:00Z", 4.0), ("2026-01-05T00:00:00Z", 5.0), ("2026-01-06T00:00:00Z", 6.0)]
    forecast = evaluate_last_value_baseline(series, horizon=1, min_train=4)
    assert forecast.justified is True
    assert forecast.mae == 1.0


def test_baseline_declines_when_insufficient():
    forecast = evaluate_last_value_baseline([("2026-01-01T00:00:00Z", 1.0)], horizon=1, min_train=5)
    assert forecast.justified is False
    assert forecast.mae is None
