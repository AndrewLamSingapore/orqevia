"""Historical event replay from persisted observations."""
from __future__ import annotations

from typing import Any


def timeline(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return observations ordered by observation time, then ingestion time."""
    def key(record: dict[str, Any]) -> tuple[str, str]:
        return (
            str(record.get("observed_at") or ""),
            str(record.get("ingested_at") or ""),
        )
    return sorted(records, key=key)


def validate_timeline(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Check ordering and provenance presence without inventing missing data."""
    ordered = timeline(records)
    pairs = [r.get("observed_at") for r in ordered if r.get("observed_at")]
    ordering_ok = pairs == sorted(pairs)
    missing_observed = sum(1 for r in records if not r.get("observed_at"))
    missing_provenance = sum(1 for r in records if not (r.get("source") and r.get("event_id")))
    return {
        "record_count": len(records),
        "ordering_ok": ordering_ok,
        "missing_observed_time": missing_observed,
        "missing_provenance": missing_provenance,
        "timeline": ordered,
    }


def replay(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic replay projection for display; never fabricates fields."""
    return [
        {
            "event_id": r.get("event_id"),
            "kind": r.get("kind"),
            "magnitude": r.get("magnitude"),
            "place": r.get("place"),
            "location": r.get("location"),
            "observed_at": r.get("observed_at"),
            "ingested_at": r.get("ingested_at"),
            "source": r.get("source"),
        }
        for r in timeline(records)
    ]
