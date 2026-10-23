"""Optional public observation adapters. GOD'S EYE only reads their stored snapshots.

Fixed public sources, no credentials, private prompts, vessel-AIS assertions or
actuation. Collection has a 15-minute minimum interval and bounded evidence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import time
import uuid
import xml.etree.ElementTree as ET

import httpx

INTERVAL = 900
MAX_BYTES = 2 * 1024 * 1024
SOURCE_MAX_AGE = {"aviation": 1200, "maritime": 21600, "geopolitical": 604800}
CATALOG = {
    "aviation": {
        "provider": "OpenSky Network",
        "url": "https://opensky-network.org/api/states/all?lamin=0.5&lomin=103&lamax=2&lomax=105",
        "coverage": "Aircraft-state snapshots in 0.5–2 N, 103–105 E. ADS-B coverage and anonymous rate limits apply.",
        "scope": "AIRCRAFT_STATE_SNAPSHOT",
    },
    "maritime": {
        "provider": "NOAA National Data Buoy Center",
        "url": "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt",
        "coverage": "Marine weather stations hosted by NOAA; strongest U.S. coverage. Vessel AIS is not connected.",
        "scope": "MARINE_WEATHER_NOT_VESSEL_AIS",
    },
    "geopolitical": {
        "provider": "Council of the European Union",
        "url": "https://www.consilium.europa.eu/en/rss/pressreleases.ashx",
        "coverage": "Council of the EU press-release headlines: EU policy reporting and attributed institutional positions, not independently adjudicated global facts.",
        "scope": "EU_COUNCIL_PRESS_RELEASES",
    },
}
_refresh_lock = asyncio.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def directory():
    return Path(os.getenv("ORQEVIA_DATA_DIR", "/data")) / "osip-observations"


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.timestamp()


def _number(value):
    if value in {"MM", None}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite observation")
    return number


def parse_aviation(raw):
    payload = json.loads(raw)
    timestamp = payload["time"]
    if type(timestamp) is not int or not 1 <= timestamp <= time.time() + 300:
        raise ValueError("Invalid provider timestamp")
    rows = payload.get("states") or []
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("Invalid state vectors")
    records = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 14:
            raise ValueError("Invalid state vector")
        if not isinstance(row[0], str) or not re.fullmatch(r"[a-f0-9]{6}", row[0]) or type(row[4]) is not int or not 1 <= row[4] <= time.time() + 300:
            raise ValueError("Invalid aircraft identity or contact time")
        lat, lon = _number(row[6]), _number(row[5])
        if lat is None or lon is None:
            continue
        if not 0.5 <= lat <= 2 or not 103 <= lon <= 105:
            continue
        if type(row[8]) is not bool:
            raise ValueError("Invalid ground state")
        records.append(
            {
                "icao24": str(row[0])[:6],
                "callsign": str(row[1] or "").strip()[:16],
                "origin_country": str(row[2])[:80],
                "lat": lat,
                "lon": lon,
                "barometric_altitude_m": _number(row[7]),
                "on_ground": row[8],
                "velocity_mps": _number(row[9]),
                "last_contact_epoch": row[4],
            }
        )
    return records[:100], datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def parse_maritime(raw):
    text = raw.decode("ascii")
    if not text.startswith("#STN"):
        raise ValueError("Unrecognized marine weather schema")
    records = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 19:
            raise ValueError("Incomplete marine observation")
        lat, lon = _number(parts[1]), _number(parts[2])
        if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid marine coordinate")
        stamp = datetime(*map(int, parts[3:8]), tzinfo=timezone.utc).isoformat()
        if _stamp(stamp) > time.time() + 300:
            raise ValueError("Future marine observation")
        records.append(
            {
                "station": parts[0][:12],
                "lat": lat,
                "lon": lon,
                "observed_at": stamp,
                "wind_speed_mps": _number(parts[9]),
                "wave_height_m": _number(parts[11]),
                "sea_temperature_c": _number(parts[18]),
                "source_url": "https://www.ndbc.noaa.gov/station_page.php?station=" + parts[0][:12],
            }
        )
    # Keep the nearest available reference stations to Singapore; no coverage is invented.
    records.sort(key=lambda r: (r["lat"] - 1.3521) ** 2 + (r["lon"] - 103.8198) ** 2)
    selected = records[:100]
    return selected, max((r["observed_at"] for r in selected), default=None)


def parse_news(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("External XML declarations are forbidden")
    tree = ET.fromstring(raw)
    records = []
    from email.utils import parsedate_to_datetime
    from urllib.parse import urlsplit

    for item in tree.findall("./channel/item")[:30]:
        link = item.findtext("link", "")
        if urlsplit(link).scheme != "https" or urlsplit(link).hostname != "www.consilium.europa.eu":
            raise ValueError("Unexpected news source link")
        stamp = parsedate_to_datetime(item.findtext("pubDate", ""))
        if stamp is None or stamp.tzinfo is None:
            raise ValueError("A timezone-qualified news publication timestamp is required")
        published = stamp.astimezone(timezone.utc).isoformat()
        if _stamp(published) > time.time() + 300:
            raise ValueError("Future publication timestamp")
        title = item.findtext("title", "")
        if not title.strip() or len(title) > 1000 or len(link) > 2000:
            raise ValueError("Invalid press-release title or link")
        records.append({
            "title": title, "source_url": link, "published_at": published,
            "attribution": f"Council of the European Union. © European Union, {stamp.year}. Original headline.",
        })
    if not tree.tag.endswith("rss") or not records:
        raise ValueError("Unrecognized or empty news schema")
    return records, max(r["published_at"] for r in records)


PARSERS = {"aviation": parse_aviation, "maritime": parse_maritime, "geopolitical": parse_news}


def _read(name):
    try:
        path = directory() / (name + ".json")
        if path.stat().st_size > MAX_BYTES:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("provider_id") != name or value.get("source_url") != CATALOG[name]["url"]:
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        return {}


def snapshot():
    entries = []
    for name, source in CATALOG.items():
        saved = _read(name)
        age = None
        source_age = None
        if saved.get("collected_at"):
            try:
                age = max(0, round(time.time() - _stamp(saved["collected_at"])))
            except (ValueError, TypeError):
                pass
        if saved.get("provider_observed_at"):
            try:
                source_age = max(0, round(time.time() - _stamp(saved["provider_observed_at"])))
            except (ValueError, TypeError):
                pass
        source_fresh = source_age is not None and source_age <= SOURCE_MAX_AGE[name]
        status = (
            "OBSERVED"
            if saved.get("last_attempt_ok") and age is not None and age <= INTERVAL + 60 and source_fresh
            else "STALE"
            if saved.get("records")
            else "UNAVAILABLE"
        )
        entries.append(
            {
                **saved,
                "provider_id": name,
                "provider": source["provider"],
                "source_url": source["url"],
                "scope": source["scope"],
                "coverage": source["coverage"],
                "status": status,
                "collection_age_seconds": age,
                "source_age_seconds": source_age,
                "source_freshness": "WITHIN_DECLARED_WINDOW" if source_fresh else "OLD_OR_UNAVAILABLE",
                "source_max_age_seconds": SOURCE_MAX_AGE[name],
                "records": saved.get("records", []),
                "read_only": True,
                "minimum_poll_interval_seconds": INTERVAL,
            }
        )
    return {
        "protocol": "orqevia.observations.v1",
        "observed_at": now(),
        "read_only": True,
        "providers": entries,
        "vessel_ais": {"status": "NOT_CONFIGURED", "credential_required": True},
        "formal_proof": {"status": "NOT_PROVIDED"},
    }


async def _collect(name, client):
    prior = _read(name)
    try:
        if prior.get("attempted_at") and time.time() - _stamp(prior["attempted_at"]) < INTERVAL:
            return
    except (ValueError, TypeError):
        pass
    attempt = now()
    result = {**prior, "provider_id": name, "source_url": CATALOG[name]["url"], "attempted_at": attempt}
    try:
        async with asyncio.timeout(12):
            async with client.stream(
                "GET",
                CATALOG[name]["url"],
                headers={
                    "User-Agent": "ORQEVIA/2.0 personal integration evaluation",
                    "Accept": "application/json,application/rss+xml,text/plain",
                },
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError("PROVIDER_HTTP_" + str(response.status_code))
                raw = b""
                async for part in response.aiter_bytes():
                    raw += part
                    if len(raw) > MAX_BYTES:
                        raise ValueError("PROVIDER_RESPONSE_LIMIT")
        records, provider_time = PARSERS[name](raw)
        result.update(
            last_attempt_ok=True,
            records=records,
            record_count=len(records),
            collected_at=now(),
            provider_observed_at=provider_time,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            response_bytes=len(raw),
            error=None,
        )
    except (
        httpx.HTTPError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
        ET.ParseError,
        RuntimeError,
    ) as exc:
        result.update(
            last_attempt_ok=False,
            error=str(exc)
            if isinstance(exc, RuntimeError) and str(exc).startswith("PROVIDER_HTTP_")
            else "PROVIDER_UNAVAILABLE_OR_INVALID",
        )
    root = directory()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(result, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, root / (name + ".json"))
    journal = {
        key: result.get(key)
        for key in (
            "provider_id",
            "source_url",
            "attempted_at",
            "collected_at",
            "payload_sha256",
            "record_count",
            "last_attempt_ok",
            "error",
        )
    }
    with (root / "collection-evidence.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(journal) + "\n")


async def refresh():
    if _refresh_lock.locked():
        return {"status": "COLLECTION_IN_PROGRESS", **snapshot()}
    async with _refresh_lock:
        journal = directory() / "collection-evidence.jsonl"
        if journal.exists() and journal.stat().st_size >= 16 * 1024 * 1024:
            return {"status": "EVIDENCE_STORAGE_BUDGET_REACHED", **snapshot()}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=3), trust_env=False, follow_redirects=False
        ) as client:
            await asyncio.gather(*[_collect(name, client) for name in CATALOG])
    return {"status": "COLLECTION_FINISHED", **snapshot()}


async def poll():
    while True:
        try:
            await refresh()
        except (OSError, ValueError):
            pass  # A failing optional collector does not block core execution.
        await asyncio.sleep(INTERVAL)
