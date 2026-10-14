"""ORQEVIA intelligence endpoints: geospatial, RAG, ingestion and detection."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..event_detection import DetectionEngine
from ..geo_ingest import SOURCES, ObservationStore, Poller
from ..geospatial import haversine_km, validate_coordinate
from ..rag_grounding import DocumentStore

router = APIRouter(prefix="/api/orqevia/intelligence")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("ORQEVIA_DATA_DIR", str(_REPO_ROOT.parents[1] / "work" / "orqevia-intelligence-data")))
OBSERVATIONS = ObservationStore(DATA_DIR / "observations.db")
DOCUMENTS = DocumentStore.load(DATA_DIR / "documents.json")
DETECTION = DetectionEngine(DATA_DIR / "alerts.json")


class RetrieveRequest(BaseModel):
    query: str
    near_lat: float | None = None
    near_lon: float | None = None
    radius_km: float | None = None


@router.get("/sources")
def sources() -> dict:
    return {"sources": SOURCES}


@router.get("/geo/distance")
def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    try:
        return {"kilometers": haversine_km(lat1, lon1, lat2, lon2)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/geo/events")
def geo_events(
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    limit: int = 200,
) -> dict:
    records = OBSERVATIONS.query(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon, limit=limit)
    return {"count": len(records), "records": records}


@router.get("/geo/radius")
def geo_radius(lat: float, lon: float, radius_km: float) -> dict:
    try:
        validate_coordinate(lat, lon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    records = OBSERVATIONS.query()
    within = [r for r in records if haversine_km(lat, lon, r["location"]["lat"], r["location"]["lon"]) <= radius_km]
    return {"count": len(within), "records": within}


@router.post("/rag/retrieve")
def rag_retrieve(request: RetrieveRequest) -> dict:
    near = None
    if request.near_lat is not None and request.near_lon is not None:
        near = (request.near_lat, request.near_lon)
    return DOCUMENTS.retrieve(
        request.query,
        actor_scopes={"APPLICATION"},
        near=near,
        radius_km=request.radius_km,
    )


@router.post("/ingest/run")
def ingest_run() -> dict:
    import time as _time
    receipt = Poller(OBSERVATIONS, source="usgs-earthquakes").run(run_id=f"run-{_time.time():.0f}")
    if receipt.ok:
        for record in OBSERVATIONS.query(limit=500):
            if DOCUMENTS.contains(record["event_id"]):
                continue
            DOCUMENTS.ingest(
                doc_id=record["event_id"],
                text=f"Earthquake magnitude {record['magnitude']} near {record.get('place') or record['event_id']}. "
                     f"Observed at {record['observed_at']} by {record['source']}.",
                source=record.get("source_url") or record["source"],
                authority_class="PUBLIC_REFERENCE",
                scope="APPLICATION",
                geometry={"type": "Point", "coordinates": [record["location"]["lon"], record["location"]["lat"]]},
                observed_at=record["observed_at"],
            )
        DOCUMENTS.save(DATA_DIR / "documents.json")
    return receipt.as_dict()


@router.get("/detection/alerts")
def detection_alerts(rule_id: str | None = None) -> dict:
    return {"alerts": DETECTION.alerts(rule_id)}
