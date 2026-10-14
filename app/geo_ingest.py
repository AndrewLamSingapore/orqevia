"""Permitted public-data ingestion with validation, dedup and provenance.

The default real source is the USGS earthquake GeoJSON feed (public, keyless).
Other connectors are registered with an honest operational status; a provider
that requires unavailable credentials is recorded BLOCKED, never replaced with
unlabeled mock data.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .geospatial import validate_coordinate


SOURCES: dict[str, dict[str, Any]] = {
    "usgs-earthquakes": {
        "kind": "earthquake",
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
        "attribution": "U.S. Geological Survey",
        "permitted_use": "Public domain USGS feed",
        "coverage": "Global",
        "refresh_interval_seconds": 300,
        "freshness_seconds": 900,
        "credential": None,
        "status": "READY",
    },
    "satellite-imagery": {"kind": "satellite", "status": "BLOCKED", "reason": "No authorized imagery provider credential on Dell"},
    "aviation-adsb": {"kind": "aviation", "status": "BLOCKED", "reason": "No permitted ADSB feed/credential on Dell"},
    "maritime-ais": {"kind": "maritime", "status": "BLOCKED", "reason": "Live AIS requires unavailable credential/payment"},
    "weather-forecast": {"kind": "weather", "status": "BLOCKED", "reason": "No authorized weather API credential on Dell"},
    "disaster-gdacs": {"kind": "disaster", "url": "https://www.gdacs.org/xml/rss.xml", "status": "BLOCKED", "reason": "RSS discovery pending; not yet parsed/qualified"},
    "geopolitical-acled": {"kind": "geopolitical", "status": "BLOCKED", "reason": "ACLED requires paid license not present on Dell"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_usgs_earthquake(feature: dict[str, Any], *, ingested_at: str | None = None) -> dict[str, Any]:
    """Normalize one USGS GeoJSON feature into an ORQEVIA observation record."""
    if not isinstance(feature, dict):
        raise ValueError("feature must be a mapping")
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 3:
        raise ValueError("earthquake geometry requires [lon, lat, depth]")
    lon, lat, depth = float(coords[0]), float(coords[1]), float(coords[2])
    lat, lon = validate_coordinate(lat, lon)
    magnitude = props.get("mag")
    if not isinstance(magnitude, (int, float)):
        raise ValueError("earthquake magnitude is missing or invalid")
    observed_at_ms = props.get("time")
    observed_at = datetime.fromtimestamp(observed_at_ms / 1000, tz=timezone.utc).isoformat() if observed_at_ms else None
    return {
        "event_id": str(props.get("id") or feature.get("id")),
        "kind": "earthquake",
        "magnitude": float(magnitude),
        "location": {"lat": lat, "lon": lon, "depth_km": depth},
        "place": props.get("place"),
        "observed_at": observed_at,
        "ingested_at": ingested_at or utc_now(),
        "source": "USGS",
        "source_url": str(props.get("url") or ""),
        "attribution": "U.S. Geological Survey",
        "status": props.get("status"),
    }


class ObservationStore:
    """SQLite event store with idempotent upsert and provenance."""

    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                event_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                provenance TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def upsert(self, record: dict[str, Any], provenance: dict[str, Any]) -> bool:
        now = utc_now()
        cur = self.conn.execute(
            "SELECT ingested_at FROM observations WHERE event_id = ?", (record["event_id"],)
        )
        existing = cur.fetchone()
        payload = json.dumps(record, sort_keys=True)
        prov = json.dumps(provenance, sort_keys=True)
        if existing:
            self.conn.execute(
                "UPDATE observations SET payload=?, provenance=?, updated_at=? WHERE event_id=?",
                (payload, prov, now, record["event_id"]),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            "INSERT INTO observations (event_id, kind, payload, provenance, ingested_at, updated_at) VALUES (?,?,?,?,?,?)",
            (record["event_id"], record["kind"], payload, prov, record["ingested_at"], now),
        )
        self.conn.commit()
        return True

    def get(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT payload FROM observations WHERE event_id = ?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def query(self, *, min_lat=None, max_lat=None, min_lon=None, max_lon=None, min_time=None, max_time=None, limit=200):
        clauses, params = [], []
        if min_lat is not None:
            clauses.append("json_extract(payload, '$.location.lat') >= ?"); params.append(min_lat)
        if max_lat is not None:
            clauses.append("json_extract(payload, '$.location.lat') <= ?"); params.append(max_lat)
        if min_lon is not None:
            clauses.append("json_extract(payload, '$.location.lon') >= ?"); params.append(min_lon)
        if max_lon is not None:
            clauses.append("json_extract(payload, '$.location.lon') <= ?"); params.append(max_lon)
        if min_time is not None:
            clauses.append("json_extract(payload, '$.observed_at') >= ?"); params.append(min_time)
        if max_time is not None:
            clauses.append("json_extract(payload, '$.observed_at') <= ?"); params.append(max_time)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(f"SELECT payload FROM observations {where} ORDER BY ingested_at DESC LIMIT ?", (*params, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


@dataclass
class IngestionReceipt:
    run_id: str
    source: str
    started_at: str
    finished_at: str
    fetched: int
    inserted: int
    updated: int
    ok: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class Poller:
    """Bounded polling with timeout, retry/backoff and idempotent persistence."""

    def __init__(self, store: ObservationStore, source: str = "usgs-earthquakes", fetch: Callable[[str], dict] | None = None) -> None:
        self.store = store
        self.source = source
        self.config = SOURCES[source]
        self.fetch = fetch or _http_fetch

    def run(self, *, run_id: str, timeout_seconds: int = 20, max_retries: int = 2) -> IngestionReceipt:
        started = utc_now()
        inserted = updated = fetched = 0
        error = None
        ok = False
        delay = 1
        for attempt in range(max_retries + 1):
            try:
                doc = self.fetch(self.config["url"], timeout_seconds)
                features = (doc.get("features") or []) if isinstance(doc, dict) else []
                for feature in features:
                    fetched += 1
                    record = normalize_usgs_earthquake(feature, ingested_at=utc_now())
                    provenance = {
                        "provider": self.source,
                        "retrieved_at": utc_now(),
                        "source_url": self.config["url"],
                        "transformation_version": "orqevia.usgs.v1",
                    }
                    if self.store.upsert(record, provenance):
                        inserted += 1
                    else:
                        updated += 1
                ok = True
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
        return IngestionReceipt(
            run_id=run_id,
            source=self.source,
            started_at=started,
            finished_at=utc_now(),
            fetched=fetched,
            inserted=inserted,
            updated=updated,
            ok=ok,
            error=error,
        )


def _http_fetch(url: str, timeout_seconds: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ORQEVIA-geo-ingest/1.0 (Dell local)"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))
