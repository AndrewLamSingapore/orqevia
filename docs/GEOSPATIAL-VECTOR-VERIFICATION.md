# Geospatial/vector candidate verification — 16 October 2026

Source baseline: `0843c76d630e087d587836e61309022f2b6693be`.
Branch: `codex/geospatial-vector-20261016`. Agent-observed isolated evidence;
not an Owner acceptance, production deployment or claim about the physical iPhone.

| Capability | Classification | Evidence / limitation |
|---|---|---|
| Existing architecture and database decision | IMPLEMENTED | GEOSPATIAL-VECTOR-ASSESSMENT.md; retain FAISS/SQLite defaults |
| PostgreSQL development environment | TESTED | Separate Docker project, loopback 55439, private random password file; PostgreSQL 17.11 |
| pgvector and PostGIS extensions | VERIFIED | Live PostgreSQL: vector 0.8.7 and postgis 3.6.4; transactional migration |
| Document extraction/chunking/embedding | TESTED | Existing bounded extraction worker; actual cached CPU MiniLM; 384 normalized dimensions |
| Vector insertion/query/source retrieval | VERIFIED | Real public USGS text uploaded through authenticated HTTP, indexed, retrieved and SHA-256 passage checked |
| Versions/deduplication/reindex | TESTED | Real DB tests; latest source version selected; superseded versions retained |
| Document isolation | VERIFIED | Two owner scopes, raw SQL RLS denial and HTTP wrong-owner 403; anonymous 401 |
| Spatial persistence and provenance | VERIFIED | Real USGS hourly feed fetched 4 observations; original event IDs and coordinates preserved |
| Spatial filtering/indexes | TESTED | Real inserts, bbox, geography distance, source/time filtering, pagination, regions; geometry/geography GiST indexes |
| GeoJSON API | VERIFIED | Authenticated real PostGIS-backed response and browser rendering |
| Interactive MapLibre integration | TESTED | Shared PWA/companion module; local 6.14.0 assets; actual Chromium WebGL, controls, filtering and evidence inspection |
| Mobile layout | TESTED | 390×844 Chromium viewport: no horizontal overflow; screenshot captured; physical iPhone NOT tested |
| Loading/empty/error/recovery | TESTED | Live-load and recovery, explicitly labelled fault-injected empty/503 responses |
| Basemap geography | TESTED | Locally bundled public-domain Natural Earth land polygons plus graticule; licensed/pinned source and attribution; no external tile dependency, imagery, roads or geographic labels claimed |
| Backend and frontend regressions | TESTED | 40 focused existing Python tests; 39 Node tests; no complete 6,000+ test sweep claimed |
| Optional PostgreSQL suite | TESTED | 15 real DB/model tests; missing live URL causes SKIP rather than false PASS |
| Browser acceptance suite | TESTED | 11 checks; no browser errors and no external style/tile requests |
| Candidate image | TESTED | Built optional PostgreSQL-enabled companion; read-only/network-disabled import smoke test includes bundled map assets and driver |
| Backup and restore | VERIFIED | Isolated custom-format pg_dump restored to a NEW database; 4 observations and 11 chunk hashes matched at snapshot time |
| Production backend/migration/promotion | BLOCKED | Requires an approved operated PostgreSQL target, migration/backfill decision and explicit deployment authorization; no production flags or data changed |
| Existing generated-answer workflow | VERIFIED | Real authenticated HTTP 200; existing local qwen2.5:7b returned CITED_MODEL_INTERPRETATION using one actual pgvector passage; citation binding passed, factual entailment remains separate |
| Production TLS/PWA and Owner-device acceptance | BLOCKED | Candidate browser tests are not deployment or Owner acceptance receipts |
| Production deployment | NOT APPLICABLE | Not performed under this directive |

## Actual test commands

- `python -B scripts/qualify_postgres.py --development` (private development
  password file and cached local model; supplies live test URLs without logging).
- `python -B -m pytest tests/test_intelligence_api.py tests/test_abex_intelligence_integration.py tests/test_geo_ingest.py tests/test_geospatial.py tests/test_rag_grounding.py tests/test_local_knowledge.py tests/test_local_knowledge_boundary.py -q --tb=short`
- `node --test tests/command_map.test.mjs clients/pwa/intelligence-tests.mjs clients/pwa/intelligence-flow-tests.mjs clients/pwa/sw-update-tests.mjs clients/pwa/revision-tests.mjs clients/pwa/candidate-tests.mjs`
- `node scripts/verify_geospatial_browser.mjs` (external evidence/token-file
  environment and installed Chromium; no credentials appear in the report).

The first local regression run used the host's newer unpinned FastAPI and failed
its old Starlette-only fixture; using the repository's pinned requirements
passed all 40. The map-source assertion and two stale shell-generation test
expectations were updated for the shared module and coherent v26 shell.
The first browser pass found a missing exact accessible name on a select;
explicit Source/Time labels fixed it. Final browser pass: 11 checks.
Initial postgis:17-3.5 build hit a retired bullseye apt repository; the pinned
pgvector PostgreSQL 17/bookworm base plus packaged PostGIS built successfully.

## Release readiness

See GEOSPATIAL-VECTOR-RUNBOOK.md for dependency/license review, runtime role
grants, opt-in backend flags, migration, data preservation, operator-managed
target selection, staging and non-destructive rollback. Review and CI remain
separate from local test evidence. No paid services, production credential
exports or broad security changes were performed. CSP permits same-origin map workers without enabling unsafe inline styles;
auth/origin/owner checks remain.

Original test output, JSON receipts, database backup and desktop/mobile PNGs are
retained locally outside Git. Only curated non-secret implementation evidence
is included in this repository. No private document corpus was uploaded.
