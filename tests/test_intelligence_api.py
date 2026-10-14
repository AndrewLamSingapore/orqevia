from fastapi.testclient import TestClient

from app import geo_ingest
from app.event_detection import DetectionEngine
from app.geo_ingest import ObservationStore
from app.orqevia import intelligence_api as ia
from app.rag_grounding import DocumentStore


FEATURE = {
    "type": "Feature",
    "id": "us7000e2e",
    "properties": {
        "mag": 4.7,
        "place": "Near test location",
        "time": 1760000000000,
        "url": "https://earthquake.usgs.gov/eventpage/us7000e2e",
        "status": "reviewed",
    },
    "geometry": {"type": "Point", "coordinates": [103.8, 1.3, 10.0]},
}


def test_end_to_end_api_path(monkeypatch, tmp_path):
    ia.OBSERVATIONS = ObservationStore(tmp_path / "obs.db")
    ia.DOCUMENTS = DocumentStore()
    ia.DETECTION = DetectionEngine(tmp_path / "alerts.json")
    monkeypatch.setattr(geo_ingest, "_http_fetch", lambda url, timeout: {"features": [FEATURE]})
    client = TestClient(ia.router)

    ingest = client.post("/api/orqevia/intelligence/ingest/run")
    assert ingest.status_code == 200 and ingest.json()["inserted"] == 1

    events = client.get("/api/orqevia/intelligence/geo/events")
    assert events.status_code == 200 and events.json()["count"] == 1

    rag = client.post("/api/orqevia/intelligence/rag/retrieve", json={"query": "earthquake magnitude"})
    assert rag.status_code == 200 and rag.json()["status"] == "GROUNDED"
    assert rag.json()["results"][0]["content_is_authority"] is False
