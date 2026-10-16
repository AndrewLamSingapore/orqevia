# Geospatial and vector architecture assessment

Baseline: canonical `main` 0843c76d630e087d587836e61309022f2b6693be,
inspected 16 October 2026. Implementation branch: codex/geospatial-vector-20261016.

## Existing architecture

- Python FastAPI backend, separate authenticated intelligence companion and TLS
  Interface gateway. Plain JavaScript PWA; no frontend package manifest exists.
- SQLite observation storage in `app/geo_ingest.py`; JSON public-observation
  retrieval in `app/rag_grounding.py`. Existing USGS ingestion supplies coordinates,
  timestamps and provenance. Preserve ingestion/detection/history behavior.
- Private documents use `app/local_knowledge_service.py`, the existing owner
  boundary, bounded extraction workers, versioned FAISS generations and cached
  sentence-transformers/all-MiniLM-L6-v2 embeddings (384 normalized dimensions).
  Existing generation uses local Ollama. Codex's DeepSeek provider is a separate
  authoring configuration, not a reason to transmit private documents externally.
- God’s Eye currently draws a static canvas coordinate grid in both the PWA
  and companion view. It is not a MapLibre map.
- Windows x64; Docker Engine 29.8.0 and Compose 5.5.1 available. No psql or
  configured PostgreSQL host/service discovered. Running containers: retained
  backend, Interface, intelligence, coaching and Ollama; none is PostgreSQL.
- CI uses pytest and Node built-in tests on Linux. Existing Compose services,
  tokens, storage, release gates and rollback resources must remain unchanged.
- Inspected environment variable names only; no database secrets exported.

## Decision before structural changes

Add one optional PostgreSQL backend supporting both pgvector and PostGIS.
Qualify it in a separate Compose project with its own volume and loopback-only
port; do not add an unmanaged second production database or change existing
FAISS/SQLite defaults. Explicit backend selection must fail visibly when the
database is unavailable, never silently return unrelated fallback results.

Reuse cached MiniLM and existing extraction/generation/authorization contracts.
Use exact cosine retrieval first; no approximate index until measured scale
justifies it. Preserve versions and source hashes; filter by owner in SQL and
row-level security before ranking. Store geometry in EPSG:4326 with a GiST index.
Public observation scope remains separate from private document ownership.

Bundle MapLibre locally. Use a self-contained graticule and locally bundled
public-domain Natural Earth land polygons, with no external tile service, demo
tiles, keys or quota dependency. Disclose generalized coastlines and the absence
of streets/imagery. An operator-approved richer style can be configured later
with its own license/attribution review. Plot only supplied observation coordinates.

## Release boundary

Source implementation, isolated tests and release preparation are authorized.
Production migration, promotion and deployment remain separate. No paid cloud
resources, production data migration, credential changes or legacy service
replacement are authorized by this work. Record actual evidence and limitations;
do not promote entries into owner-only Verified sections of STATUS.md.
