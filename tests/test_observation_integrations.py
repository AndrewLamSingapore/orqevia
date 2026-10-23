"""Isolated public-feed schemas, rate bounds and failure preservation. Not live data."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import httpx
import pytest

from app import observation_integrations as observations


def fixtures():
    now = datetime.now(timezone.utc)
    aviation = json.dumps(
        {
            "time": int(now.timestamp()),
            "states": [
                [
                    "abc123",
                    "FIXTURE",
                    "Fixture country",
                    1,
                    int(now.timestamp()),
                    103.8,
                    1.3,
                    100,
                    False,
                    10,
                    0,
                    None,
                    None,
                    100,
                ]
            ],
        }
    ).encode()
    maritime = (
        "#STN LAT LON YYYY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES PTDY ATMP WTMP\n"
        f"TEST 1.3 103.8 {now:%Y %m %d %H %M} MM 1.2 MM 0.4 MM MM MM 1000 MM 25 26\n"
    ).encode()
    news = (
        "<rss><channel><item><title>Explicit synthetic headline</title><link>https://www.consilium.europa.eu/en/press/press-releases/fixture</link>"
        f"<pubDate>{now:%a, %d %b %Y %H:%M:%S GMT}</pubDate></item></channel></rss>"
    ).encode()
    return {"aviation": aviation, "maritime": maritime, "geopolitical": news}


def test_absent_snapshots_are_unavailable_without_creating_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    value = observations.snapshot()
    assert value["read_only"] is True and all(p["status"] == "UNAVAILABLE" for p in value["providers"])
    assert value["vessel_ais"]["status"] == "NOT_CONFIGURED"
    assert not list(tmp_path.iterdir())


def test_source_parsers_validate_provenance_and_preserve_missing_measurements():
    raw = fixtures()
    records, _ = observations.parse_aviation(raw["aviation"])
    assert records[0]["icao24"] == "abc123" and records[0]["on_ground"] is False
    records, _ = observations.parse_maritime(raw["maritime"])
    assert records[0]["wave_height_m"] == 0.4 and records[0]["sea_temperature_c"] == 26
    records, _ = observations.parse_news(raw["geopolitical"])
    assert records[0]["source_url"].startswith("https://www.consilium.europa.eu/")
    assert "European Union" in records[0]["attribution"]
    for body in (
        b"<!DOCTYPE x><rss/>",
        b"<rss><channel><item><link>https://private.invalid/</link></item></channel></rss>",
    ):
        with pytest.raises(ValueError):
            observations.parse_news(body)
    with pytest.raises(ValueError):
        observations.parse_maritime(b"not a marine observation")


def test_collection_has_fixed_sources_rate_bounds_and_preserves_failed_prior_readings(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    raw = fixtures()
    calls = []
    fail_aviation = False
    actual = httpx.AsyncClient

    def upstream(request):
        calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        name = next(name for name, source in observations.CATALOG.items() if str(request.url) == source["url"])
        if name == "aviation" and fail_aviation:
            return httpx.Response(429)
        return httpx.Response(200, content=raw[name])

    with patch.object(
        observations.httpx,
        "AsyncClient",
        side_effect=lambda **kw: actual(transport=httpx.MockTransport(upstream), **kw),
    ):
        first = asyncio.run(observations.refresh())
        assert all(p["status"] == "OBSERVED" for p in first["providers"])
        asyncio.run(observations.refresh())
        assert len(calls) == 3
        monkeypatch.setattr(observations, "INTERVAL", 0)
        fail_aviation = True
        second = asyncio.run(observations.refresh())
    aviation = next(p for p in second["providers"] if p["provider_id"] == "aviation")
    assert aviation["status"] == "STALE" and aviation["records"][0]["icao24"] == "abc123"
    assert aviation["error"] == "PROVIDER_HTTP_429"
    assert (tmp_path / "osip-observations/collection-evidence.jsonl").is_file()


def test_recent_collection_does_not_make_old_provider_data_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    root = tmp_path / "osip-observations"
    root.mkdir()
    (root / "aviation.json").write_text(
        json.dumps(
            {
                "provider_id": "aviation",
                "source_url": observations.CATALOG["aviation"]["url"],
                "last_attempt_ok": True,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "provider_observed_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "records": [{"icao24": "abc123"}],
            }
        ),
        encoding="utf-8",
    )
    entry = observations.snapshot()["providers"][0]
    assert entry["status"] == "STALE"
    assert entry["source_freshness"] == "OLD_OR_UNAVAILABLE"
    assert entry["collection_age_seconds"] < 10
    assert entry["records"] == [{"icao24": "abc123"}]


def test_council_update_timestamp_is_not_reported_as_a_publication_time():
    stamp = datetime.now(timezone.utc).isoformat()
    raw = (
        f'<rss xmlns:atom="http://www.w3.org/2005/Atom"><channel><item>'
        f"<title>Explicit synthetic Council headline</title>"
        f"<link>https://www.consilium.europa.eu/en/press/press-releases/fixture</link>"
        f"<atom:updated>{stamp}</atom:updated></item></channel></rss>"
    ).encode()
    records, observed = observations.parse_news(raw)
    assert records[0]["published_at"] is None
    assert records[0]["timestamp_kind"] == "PROVIDER_UPDATE"
    assert records[0]["provider_updated_at"] == observed == stamp


def test_restart_near_collection_deadline_waits_only_until_the_next_due_poll(monkeypatch):
    current = datetime.now(timezone.utc).timestamp()
    attempted = datetime.fromtimestamp(current - observations.INTERVAL + 5, timezone.utc).isoformat()
    monkeypatch.setattr(observations.time, "time", lambda: current)
    monkeypatch.setattr(observations, "_read", lambda name: {"attempted_at": attempted})
    assert observations.next_poll_delay() == pytest.approx(5)
