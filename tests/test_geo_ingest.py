from app.geo_ingest import ObservationStore, Poller, normalize_gdacs_item, normalize_open_meteo, normalize_usgs_earthquake


FEATURE = {
    "type": "Feature",
    "id": "us7000test",
    "properties": {
        "mag": 5.6,
        "place": "Test Region",
        "time": 1760000000000,
        "url": "https://example.gov/us7000test",
        "status": "reviewed",
    },
    "geometry": {"type": "Point", "coordinates": [103.8, 1.3, 12.0]},
}


def test_normalize_usgs_earthquake():
    rec = normalize_usgs_earthquake(FEATURE, ingested_at="2026-01-01T00:00:00+00:00")
    assert rec["event_id"] == "us7000test"
    assert rec["location"]["lat"] == 1.3
    assert rec["location"]["lon"] == 103.8
    assert rec["magnitude"] == 5.6


def test_store_deduplicates(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    rec = normalize_usgs_earthquake(FEATURE, ingested_at="2026-01-01T00:00:00+00:00")
    assert store.upsert(rec, {"provider": "test"}) is True
    assert store.upsert(rec, {"provider": "test"}) is False
    assert store.count() == 1


def test_poller_produces_receipts(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    poller = Poller(store, source="usgs-earthquakes", fetch=lambda url, timeout: {"features": [FEATURE]})
    first = poller.run(run_id="r1")
    second = poller.run(run_id="r2")
    assert first.ok and first.inserted == 1
    assert second.ok and second.inserted == 0 and second.updated == 1
    assert store.count() == 1


def test_poller_fails_closed_for_blocked_source(tmp_path):
    store = ObservationStore(tmp_path / "obs.db")
    receipt = Poller(store, source="maritime-ais").run(run_id="blocked")
    assert receipt.ok is False
    assert receipt.error and "credential" in receipt.error
    assert store.count() == 0


def test_normalize_open_meteo():
    record = normalize_open_meteo({"current_weather": {"time": "2026-01-01T00:00", "temperature": 28.0, "windspeed": 5.0, "weathercode": 1}}, lat=1.3, lon=103.8)
    assert record["kind"] == "weather"
    assert record["temperature_c"] == 28.0
    assert record["location"] == {"lat": 1.3, "lon": 103.8}


def test_normalize_gdacs_item():
    record = normalize_gdacs_item({"title": "Green earthquake", "link": "https://gdacs.org/e1", "pubDate": "2026-01-01T00:00:00Z"})
    assert record["kind"] == "disaster"
    assert record["place"] == "Green earthquake"
