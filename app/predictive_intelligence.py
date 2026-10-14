"""Measurable, uncertainty-labelled forecasting baseline.

Only a last-observation baseline is implemented. It is chronological (no
future leakage) and reports MAE plus an explicit validity decision. A forecast
chart or baseline alone is not acceptance evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Forecast:
    horizon: int
    method: str
    predictions: list[tuple[str, float]]
    actuals: list[tuple[str, float]]
    mae: float | None
    justified: bool
    reason: str


def _chronological(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(series, key=lambda pair: pair[0])


def evaluate_last_value_baseline(
    series: Iterable[tuple[str, float]],
    *,
    horizon: int = 1,
    min_train: int = 5,
) -> Forecast:
    """Evaluate a one-step-persist baseline over held-out chronological pairs."""
    rows = _chronological([(str(t), float(v)) for t, v in series])
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if len(rows) < min_train + horizon:
        return Forecast(
            horizon=horizon,
            method="last_value_baseline",
            predictions=[],
            actuals=[],
            mae=None,
            justified=False,
            reason=f"insufficient data: {len(rows)} < {min_train + horizon}",
        )
    predictions: list[tuple[str, float]] = []
    actuals: list[tuple[str, float]] = []
    errors: list[float] = []
    for index in range(min_train, len(rows) - horizon + 1):
        baseline = rows[index - 1][1]
        target_time, target = rows[index + horizon - 1]
        predictions.append((target_time, baseline))
        actuals.append((target_time, target))
        errors.append(abs(baseline - target))
    mae = sum(errors) / len(errors) if errors else None
    return Forecast(
        horizon=horizon,
        method="last_value_baseline",
        predictions=predictions,
        actuals=actuals,
        mae=mae,
        justified=True,
        reason="chronological hold-out evaluation completed",
    )
