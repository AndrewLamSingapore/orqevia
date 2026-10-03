"""Durable forecast/outcome ledger with leakage and duplicate guards."""

from datetime import datetime, timezone
from decimal import Decimal
from contextlib import closing
import math
from pathlib import Path
import sqlite3

from .core import _decimal


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


class ForecastLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.parent.exists():
            raise ValueError("ledger parent directory must already exist")
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                event_definition TEXT NOT NULL,
                probability TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                source TEXT NOT NULL,
                outcome INTEGER,
                outcome_at TEXT
            )""")

    def record_forecast(self, forecast_id: str, event_definition: str, probability: object, issued_at: datetime, source: str) -> None:
        p = _decimal(probability, "probability")
        if not 0 <= p <= 1:
            raise ValueError("probability must be within [0, 1]")
        if not forecast_id.strip() or not event_definition.strip() or not source.strip():
            raise ValueError("forecast ID, event definition, and source are required")
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute("INSERT INTO forecasts(forecast_id,event_definition,probability,issued_at,source) VALUES(?,?,?,?,?)", (forecast_id, event_definition, str(p), _utc(issued_at), source))

    def record_outcome(self, forecast_id: str, outcome: bool, observed_at: datetime) -> None:
        if not isinstance(outcome, bool):
            raise ValueError("outcome must be boolean")
        when = _utc(observed_at)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                row = connection.execute("SELECT issued_at,outcome FROM forecasts WHERE forecast_id=?", (forecast_id,)).fetchone()
                if row is None:
                    raise KeyError(forecast_id)
                if row[1] is not None:
                    raise ValueError("outcome is already recorded")
                if when <= row[0]:
                    raise ValueError("outcome must be observed after forecast issuance")
                connection.execute("UPDATE forecasts SET outcome=?,outcome_at=? WHERE forecast_id=?", (int(outcome), when, forecast_id))

    def scores(self) -> dict[str, object]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT probability,outcome FROM forecasts WHERE outcome IS NOT NULL ORDER BY forecast_id").fetchall()
        if not rows:
            return {"status": "INSUFFICIENT_EVIDENCE", "count": 0}
        brier = sum((float(Decimal(p)) - y) ** 2 for p, y in rows) / len(rows)
        log_loss = -sum(math.log(float(Decimal(p)) if y else float(1 - Decimal(p))) if 0 < (float(Decimal(p)) if y else float(1 - Decimal(p))) else math.inf for p, y in rows) / len(rows)
        return {"status": "CALCULATED", "count": len(rows), "brier_score": brier, "log_loss": log_loss, "calibrated": False}
