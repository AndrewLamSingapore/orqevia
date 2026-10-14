from app.event_detection import DetectionEngine


def _event(mag=6.0, lat=1.3, lon=103.8, event_id="e1"):
    return {
        "event_id": event_id,
        "magnitude": mag,
        "location": {"lat": lat, "lon": lon},
        "source": "USGS",
        "observed_at": "2026-01-01T00:00:00+00:00",
    }


def test_rule_fires_once_and_suppresses_duplicates(tmp_path):
    engine = DetectionEngine(tmp_path / "alerts.json")
    engine.add_rule("r1", min_magnitude=5.0, geo_scope=[0, 5, 100, 110], severity="HIGH", cooldown_seconds=60)
    first = engine.evaluate(_event(), now=1000)
    dup = engine.evaluate(_event(), now=1010)
    assert first is not None and first["delivery_status"] == "INTERNAL"
    assert dup is None
    assert len(engine.alerts()) == 1


def test_rule_ignores_out_of_scope(tmp_path):
    engine = DetectionEngine(tmp_path / "alerts.json")
    engine.add_rule("r1", min_magnitude=5.0, geo_scope=[0, 5, 100, 110], severity="HIGH", cooldown_seconds=60)
    assert engine.evaluate(_event(lat=-10, lon=-80), now=1000) is None


def test_restart_preserves_history(tmp_path):
    path = tmp_path / "alerts.json"
    engine = DetectionEngine(path)
    engine.add_rule("r1", min_magnitude=5.0, geo_scope=None, severity="MEDIUM", cooldown_seconds=0)
    engine.evaluate(_event(), now=1000)
    reloaded = DetectionEngine(path)
    assert len(reloaded.alerts()) == 1
