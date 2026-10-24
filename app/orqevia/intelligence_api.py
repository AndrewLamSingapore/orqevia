"""ORQEVIA intelligence endpoints: geospatial, RAG, ingestion and detection."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..event_detection import DetectionEngine
from ..geo_ingest import SOURCES, ObservationStore, Poller
from ..geospatial import haversine_km, validate_coordinate
from ..rag_grounding import DocumentStore
from ..postgres_intelligence import PostgresObservationStore

router = APIRouter(prefix="/api/orqevia/intelligence")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_configured_data_dir = os.getenv("ORQEVIA_DATA_DIR")
DATA_DIR = Path(
    _configured_data_dir
    if _configured_data_dir
    else _REPO_ROOT.parent / "work" / "orqevia-intelligence-data"
)
if os.getenv('ORQEVIA_OBSERVATION_BACKEND','sqlite') == 'postgres':
    OBSERVATIONS = PostgresObservationStore()
elif os.getenv('ORQEVIA_OBSERVATION_BACKEND','sqlite') == 'sqlite':
    OBSERVATIONS = ObservationStore(DATA_DIR / "observations.db")
else:
    raise RuntimeError('Unknown observation backend')
DOCUMENTS = DocumentStore.load(DATA_DIR / "documents.json")
DETECTION = DetectionEngine(DATA_DIR / "alerts.json")
INGEST_LOCK = threading.Lock()


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
    if not 1 <= limit <= 500:
        raise HTTPException(400, 'Limit must be between 1 and 500')
    records = OBSERVATIONS.query(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon, limit=limit)
    return {"count": len(records), "records": records}


@router.get("/geo/radius")
def geo_radius(lat: float, lon: float, radius_km: float) -> dict:
    if not 0 <= radius_km <= 40075:
        raise HTTPException(400, 'Radius is outside supported bounds')
    try:
        validate_coordinate(lat, lon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(OBSERVATIONS, PostgresObservationStore):
        records=OBSERVATIONS.query(lat=lat,lon=lon,radius_km=radius_km,limit=500)
        return {'count':len(records),'records':records}
    records = OBSERVATIONS.query(limit=500)
    within = [r for r in records if haversine_km(lat, lon, r["location"]["lat"], r["location"]["lon"]) <= radius_km]
    return {"count": len(within), "records": within}


@router.get('/geo/features')
def geo_features(min_lat: float | None = None, max_lat: float | None = None,
                 min_lon: float | None = None, max_lon: float | None = None,
                 min_time: str | None = None, max_time: str | None = None,
                 source: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    from datetime import datetime, timezone
    import math
    try:
        if not 1<=limit<=500 or not 0<=offset<=100000:raise ValueError('Invalid pagination')
        bounds=(min_lat,max_lat,min_lon,max_lon)
        if any(v is not None for v in bounds):
            if any(v is None or not math.isfinite(v) for v in bounds) or not -90<=min_lat<=max_lat<=90 or not -180<=min_lon<=max_lon<=180:
                raise ValueError('A valid complete bounding box is required')
        for stamp in (min_time,max_time):
            if stamp and datetime.fromisoformat(stamp.replace('Z','+00:00')).tzinfo is None:raise ValueError('Timezone required')
        if source and source!='USGS':raise ValueError('Unsupported source filter')
        if isinstance(OBSERVATIONS,PostgresObservationStore):
            records=OBSERVATIONS.query(min_lat=min_lat,max_lat=max_lat,min_lon=min_lon,max_lon=max_lon,min_time=min_time,max_time=max_time,source=source,limit=limit,offset=offset)
        else:
            # Compatibility path for the preserved bounded public SQLite store.
            records=OBSERVATIONS.query(min_lat=min_lat,max_lat=max_lat,min_lon=min_lon,max_lon=max_lon,min_time=min_time,max_time=max_time,limit=10000)
            records=[r for r in records if not source or r.get('source')==source][offset:offset+limit]
        features=[]
        for record in records:
            location=record.get('location') or {}
            lat,lon=validate_coordinate(location.get('lat'),location.get('lon'))
            if not math.isfinite(lat) or not math.isfinite(lon):continue
            features.append({'type':'Feature','id':record['event_id'],'geometry':{'type':'Point','coordinates':[lon,lat]},'properties':record})
        return {'type':'FeatureCollection','features':features,'count':len(features),'limit':limit,'offset':offset,
                'next_offset':offset+limit if len(records)==limit else None,'as_of':datetime.now(timezone.utc).isoformat(),
        'scope':'PUBLIC_REFERENCE','attribution':'U.S. Geological Survey','coverage':'Stored observations only; Singapore-centred regional USGS window; not live global coverage'}
    except (ValueError,TypeError,OverflowError):
        raise HTTPException(422,'Invalid geographic filter or stored coordinate') from None


@router.get('/geo/regions')
def geo_regions() -> dict:
    if not isinstance(OBSERVATIONS,PostgresObservationStore):raise HTTPException(503,'Regional aggregation requires the opt-in PostGIS backend')
    return {'grid_degrees':10,'regions':OBSERVATIONS.regions(),'scope':'PUBLIC_REFERENCE'}


@router.post("/rag/retrieve")
def rag_retrieve(request: RetrieveRequest) -> dict:
    if not request.query.strip() or len(request.query) > 4096:
        raise HTTPException(400, 'A bounded retrieval query is required')
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
    if not INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(429, 'Ingestion already in progress')
    try:
        return _ingest_run()
    finally:
        INGEST_LOCK.release()


def _ingest_run() -> dict:
    import time as _time
    total_bytes=sum(p.stat().st_size for p in DATA_DIR.iterdir() if p.is_file())
    if total_bytes > 128*1024*1024 or OBSERVATIONS.count()>10000:
        raise HTTPException(507, 'Intelligence storage budget reached; existing observations preserved')
    receipt = Poller(OBSERVATIONS, source="usgs-earthquakes").run(
        run_id=f"run-{_time.time_ns()}", timeout_seconds=20, max_retries=0)
    if receipt.ok:
        if 'usgs-magnitude-5' not in DETECTION.data['rules']:
            DETECTION.add_rule('usgs-magnitude-5', min_magnitude=5.0, geo_scope=None,
                severity='HIGH', cooldown_seconds=86400)
        for record in OBSERVATIONS.query(limit=500):
            DETECTION.evaluate(record)
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


@router.get('/health')
def intelligence_health() -> dict:
    return {'ok': True, 'source_revision': os.getenv('ORQEVIA_SOURCE_REVISION', 'UNKNOWN'),
        'observation_count': OBSERVATIONS.count(), 'ingestion_suspended': (DATA_DIR/'suspended').exists(),
        'persisted_source': 'USGS public observations', 'provider_runtime_acceptance': 'SEPARATE_RECEIPT_REQUIRED'}


@router.get('/history/timeline')
def historical_timeline(limit: int = 200) -> dict:
    from ..historical_intelligence import validate_timeline
    if not 1 <= limit <= 500:
        raise HTTPException(400, 'Limit must be between 1 and 500')
    return validate_timeline(OBSERVATIONS.query(limit=limit))


@router.get('/predictive/baseline')
def predictive_baseline() -> dict:
    from dataclasses import asdict
    from ..predictive_intelligence import evaluate_last_value_baseline
    rows=OBSERVATIONS.query(limit=500)
    return {**asdict(evaluate_last_value_baseline(
        [(r['observed_at'],r['magnitude']) for r in rows if r.get('observed_at')])),
        'disclosure': 'Last-value sequence benchmark only; not earthquake prediction or an accepted predictive service'}


@router.get("/detection/alerts")
def detection_alerts(rule_id: str | None = None) -> dict:
    return {"alerts": DETECTION.alerts(rule_id)}
