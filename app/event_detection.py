"""Explainable event detection and in-app alerting for ORQEVIA."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class DetectionEngine:
    """Persisted rule configuration, deduplication, cooldowns and alert history."""

    def __init__(self, store_path: Path | str) -> None:
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"rules": {}, "alerts": [], "fired": {}}
            self._persist()

    def _persist(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def add_rule(
        self,
        rule_id: str,
        *,
        min_magnitude: float,
        geo_scope: list[float] | None,
        severity: str,
        cooldown_seconds: int,
        max_distance_km: float | None = None,
    ) -> None:
        if geo_scope is not None and len(geo_scope) != 4:
            raise ValueError("geo_scope must be [min_lat, max_lat, min_lon, max_lon]")
        self.data["rules"][rule_id] = {
            "min_magnitude": float(min_magnitude),
            "geo_scope": geo_scope,
            "severity": severity,
            "cooldown_seconds": int(cooldown_seconds),
            "max_distance_km": max_distance_km,
        }
        self._persist()

    def evaluate(self, event: dict[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
        """Return a new alert record, or None when suppressed/not eligible."""
        now = time.time() if now is None else float(now)
        fired = []
        for rule_id, rule in self.data["rules"].items():
            if not self._eligible(event, rule):
                continue
            dedup_key = f"{rule_id}:{event.get('event_id')}"
            last = self.data["fired"].get(dedup_key)
            if last is not None and now - last < rule["cooldown_seconds"]:
                continue
            severity = rule["severity"]
            alert = {
                "alert_id": f"alert-{int(now * 1000)}-{rule_id}",
                "rule_id": rule_id,
                "event_id": event.get("event_id"),
                "severity": severity,
                "created_at": now,
                "delivery_status": "INTERNAL",
                "evidence": {
                    "triggered_by": event.get("event_id"),
                    "magnitude": event.get("magnitude"),
                    "location": event.get("location"),
                    "source": event.get("source"),
                    "observed_at": event.get("observed_at"),
                },
            }
            self.data["alerts"].append(alert)
            self.data["fired"][dedup_key] = now
            fired.append(alert)
        if fired:
            self._persist()
        return fired[0] if fired else None

    @staticmethod
    def _eligible(event: dict[str, Any], rule: dict[str, Any]) -> bool:
        magnitude = event.get("magnitude")
        if not isinstance(magnitude, (int, float)) or magnitude < rule["min_magnitude"]:
            return False
        loc = event.get("location")
        if not isinstance(loc, dict):
            return False
        lat, lon = loc.get("lat"), loc.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        scope = rule["geo_scope"]
        if scope is not None:
            min_lat, max_lat, min_lon, max_lon = scope
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                return False
        return True

    def alerts(self, rule_id: str | None = None) -> list[dict[str, Any]]:
        if rule_id is None:
            return list(self.data["alerts"])
        return [a for a in self.data["alerts"] if a["rule_id"] == rule_id]
