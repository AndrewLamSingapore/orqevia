# ORQEVIA Intelligence — God's Eye, Geospatial and RAG

Active architecture: ORQEVIA. JARVIS PRIME is retired. There is no SSOT.
DigitalOcean, Azure and the historical 21-agent registry are parked.

## Components

- `app/orqevia/ui.py` — read-only FastAPI surface (recovered from
  `feat/orqevia-unified-interface-20261011`, PR #244).
- `app/orqevia/intelligence_api.py` — geospatial, RAG, ingestion and detection endpoints.
- `app/geospatial.py` — WGS84 distance, bounding boxes, antimeridian,
  point-in-polygon, geodesic grid index, GeoJSON validation.
- `app/rag_grounding.py` — access-controlled, versioned retrieval grounding.
- `app/geo_ingest.py` — permitted public-data ingestion and persistence.
- `app/event_detection.py` — explainable event detection and in-app alerting.
- `app/historical_intelligence.py` — historical replay.
- `app/predictive_intelligence.py` — measurable chronological baseline.

## Public sources (no-key where feasible)

- USGS earthquakes — READY, keyless.
- Open-Meteo weather — READY, keyless point forecast.
- GDACS disaster RSS — READY, keyless.
- NASA FIRMS / NASA EPIC — READY, keyless satellite products.
- Aviation (ADSB), maritime (AIS), geopolitical (ACLED) — BLOCKED pending
  credentials or paid licenses; never replaced with mock data.

## God's Eye PR reconciliation

PR #202 (formal semantic projection) and PR #244 (unified read-only interface)
are preserved in Git history. The read-only shell and view were recovered into
this branch; the formal RDF/SHACL/OWL semantic stack from #202 remains parked
and is not required for the current geospatial/RAG baseline.

## Run

```
ORQEVIA_BASE_URL=http://127.0.0.1:8000 uvicorn app.orqevia.ui:app --port 8100
```

Set `ORQEVIA_DATA_DIR` to an external writable directory (defaults to
`<workspace>/work/orqevia-intelligence-data`).

## Tests

```
python -m pytest -q tests/test_geospatial.py tests/test_rag_grounding.py \
  tests/test_geo_ingest.py tests/test_event_detection.py \
  tests/test_historical_predictive.py tests/test_intelligence_api.py
```

## Deployment authorization

No deployment target is authorized for Dell at this time. DigitalOcean/Azure
are parked. The branch is a tested, deployable release candidate; deployment
requires an explicit Dell-authorized target.
