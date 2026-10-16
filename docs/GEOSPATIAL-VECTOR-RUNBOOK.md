# Geospatial/vector release and rollback

This branch is a candidate. No production switch or deployment is implied.
Read GEOSPATIAL-VECTOR-ASSESSMENT.md before provisioning.

## Dependencies and license

- PostgreSQL 17; pgvector 0.8.7 and PostGIS 3.6.4 observed in isolated tests.
  `deploy/geospatial/Dockerfile` pins the pgvector base digest and installs
  PostGIS from the PostgreSQL package repository. Record the built image digest
  at promotion; package updates are not a claim of reproducible binary bytes.
- Optional Python driver: `requirements-postgres.txt`. Install into the existing
  service's candidate environment, not globally. For the companion image build,
  pass `--build-arg ORQEVIA_POSTGRES_ENABLED=1`.
- MiniLM all-MiniLM-L6-v2: Apache-2.0, 384 normalized dimensions, CPU inference;
  reused existing local cache with `trust_remote_code=False`. No inference API
  keys or embedding downloads are required at runtime. Evidence tests used the
  actual cached model. Preserve the existing FAISS index and document corpus.
  Model reference: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- MapLibre GL JS 6.14.0, BSD-3-Clause. Bundled local ES modules, worker and CSS;
  license in `clients/pwa/vendor/MAPLIBRE-LICENSE.txt`. Rebuild with
  `pnpm --dir clients/pwa install --frozen-lockfile --ignore-scripts` then
  `pnpm --dir clients/pwa run build:map`. No demonstration tile server is used.
  The built-in grid and locally bundled Natural Earth 1:110m public-domain land
  polygons work without third-party tiles. The exact source commit and SHA-256
  are in `vendor/NATURAL-EARTH-NOTICE.txt`; terms are at
  https://www.naturalearthdata.com/about/terms-of-use/. These generalized
  coastlines are for orientation, not navigation. Labels/roads/imagery are NOT
  provided. Adding richer tiles requires an approved provider, licensing,
  attribution, quota and privacy decision.

## Isolated qualification (never production credentials)

1. Create a random development database password file outside source. Set
   `ORQEVIA_DEV_DB_PASSWORD_FILE` to its absolute path; never log its contents.
2. `docker compose -f deploy/geospatial/compose.yml up -d --build`
   creates only the separate development project, named volume and
   `127.0.0.1:55439` listener. It does not modify the live ORQEVIA services.
3. Apply `deploy/geospatial/001-intelligence.sql` with the migration identity.
   Reapplying is additive/idempotent. It installs both extensions, owned tables,
   row policies and spatial indexes in a transaction. Never grant the runtime
   role superuser, BYPASSRLS, schema CREATE or DDL permissions.
4. Provision a separate login with CONNECT to the selected database, USAGE on
   `orqevia`, SELECT/INSERT/UPDATE on document_versions, document_chunks and
   observations, and SELECT on schema_migrations. No DELETE permission is needed.
   The code refuses superuser/BYPASSRLS connections. Private document rows also
   require a transaction-local owner scope and explicit SQL owner predicates.
5. Set private `ORQEVIA_DATABASE_URL` in the candidate service environment. Use
   verified TLS (`sslmode=verify-full` plus trusted CA) for remote hosting. The
   development-only loopback database uses password authentication over localhost.
   Never include connection URLs in logs, Git, process arguments or frontend code.
6. Enable `ORQEVIA_KNOWLEDGE_BACKEND=postgres` in the existing private knowledge
   service only when ready. The same existing bound owner account and service
   auth apply. Without this flag the original FAISS engine stays selected.
7. Enable `ORQEVIA_OBSERVATION_BACKEND=postgres` in the candidate companion only
   when ready. Without the flag SQLite stays selected. Unknown backend names
   fail; PostgreSQL failure never silently returns fallback data.
8. `ORQEVIA_TEST_DSN` (runtime role), `ORQEVIA_TEST_ADMIN_DSN` (optional negative
   test), and `ORQEVIA_TEST_DATA` must name a disposable migrated test environment.
   Run `python -B -m pytest tests/test_postgres_intelligence.py -q`.
   Without the live database environment these tests SKIP, never masquerade as PASS.
   For reproducible local bootstrap against ONLY the development Compose database,
   run `python -B scripts/qualify_postgres.py --development` with
   `ORQEVIA_DEV_DB_PASSWORD_FILE` set. It applies the migration, provisions the
   restricted development role, and supplies private test URLs in child-process
   environment variables. It does not accept an arbitrary production target.
9. Exercise authenticated `/ingest`, `/retrieve`, `/documents`, `/reindex` via the
   retained knowledge service. The TLS gateway keeps its owner binding; callers
   cannot select another account. Upload extraction, 800-character overlapping
   chunks, normalized embeddings, latest-version filtering and hashes are reused.
   `/answer` retains the existing local generation contract and model availability;
   no generation/provider switch is performed. Verified retrieval does not prove
   answer entailment or local generation availability.
10. Run real USGS ingestion then `/api/orqevia/intelligence/geo/features` with
    source/time/bbox/limit/offset filters, `/geo/radius` and `/geo/regions`.
    Spatial filtering executes before pagination on PostGIS. No invented locations.
    Only public-reference USGS records are accepted; private observation ingestion
    is deliberately unsupported. Existing authenticated bridge reads remain required.

## Browser qualification

`scripts/verify_geospatial_browser.mjs` uses Playwright against loopback port
18150, an isolated authenticated companion containing REAL ingested records.
Set external `ORQEVIA_BROWSER_EVIDENCE`, a test-only
`ORQEVIA_BROWSER_TOKEN_FILE`, and optional `ORQEVIA_TEST_CHROMIUM` executable.
Tests cover actual WebGL, local style/modules/worker, layers, source filtering,
coordinate navigation, inspection, evidence links, mobile overflow, errors and
recovery. Error/empty cases explicitly inject faults and do not count as live
source verification. Screenshots establish candidate browser behavior, not
production TLS/session acceptance or physical iPhone acceptance.

## Production preparation and rollback

Require independent review/CI and explicit promotion authorization. Select one
operated production PostgreSQL target supporting both extensions; no second
unmanaged production database is introduced by the development Compose project.
Use separate migration/runtime identities, connection limits, verified TLS,
backup retention and monitoring. Make a consistent database backup with pg_dump
custom format, restore it into a NEW disposable database, compare row counts,
extensions and evidence hashes before migrating production records.

Existing FAISS and SQLite records are NOT automatically copied, deleted or
reindexed. Plan authorized owner-by-owner document ingestion and public-source
observation backfill with manifests, counts and hash comparisons before changing
the production backend flags. Existing synchronization continues on the selected
backend; do not operate two ingestion writers over the same logical dataset.

Build the companion and additive Interface candidate, inspect generated assets,
and validate on staging through the real TLS/session boundary. Keep the original
containers, images, volumes, environment and FAISS generations. To roll back,
restore the prior application image/environment and unset the two backend flags;
the original FAISS/SQLite data remains untouched. Preserve the PostgreSQL schema
and volume. `rollback.sql` is an inspection-only receipt, not destructive down SQL.
Never use `docker compose down -v` or drop extensions as routine rollback.

Development backup/restoration was exercised only on this disposable database.
Production restoration and owner-device acceptance require their own receipts.
Exact cosine search is intentionally unindexed; qualify latency/selectivity at
real scale before considering HNSW/IVFFlat. GiST indexes cover geometry and
geography distance operations. Time/source filtering and bounded pagination are
supported; anti-meridian queries should be split into two bounding boxes.
