# ORQEVIA database architecture — verified report — 16 October 2026

Scope: the `AndrewLamSingapore/orqevia` repository at `main`
`9f2e9cac7d1b6b945cb7d7d3d288176a7ed81322`, inspected from source and runtime
configuration. This report records what the source actually does; it does not
claim deployment or runtime acceptance.

## Verdict

ORQEVIA's own persistence layer is **SQLite plus filesystem**, with no
PostgreSQL in the `orqevia` repository. A PostgreSQL migration is **not
justified** for the current single-host, fail-closed deployment model.
Geospatial use is basic WGS-84 validation and distance (no PostGIS
requirement), and semantic search is served by a local FAISS index (no pgvector
requirement). Provisioning PostgreSQL would add unnecessary infrastructure and
a second source of truth against the directive. The correct action is to
**preserve and harden** the existing layer.

## What the repository actually persists

The backend resolves `PRIME_DATA_DIR` (default `/data` inside the container)
and keeps a set of purpose-scoped SQLite databases there. Connection hygiene in
the core ledgers already sets WAL journaling, `busy_timeout`, and
`foreign_keys=ON`; the queue concurrency is deliberately low
(`PRIME_QUEUE_CONCURRENCY=1`), matching SQLite's single-writer model.

| Domain | Persistence |
|---|---|
| Objectives | `objectives.db` (SQLite) + `compute-ledger.db` for inference attempts |
| Compute / job queue | `compute-queue.db` (SQLite, atomic leases) and `compute-ledger.db` |
| Agents | `config/agent_registry.json` (canonical registry) + `agent-authority.db` and queue ledgers |
| Users / sessions | `client_auth.py` compares the owner bearer token (`PRIME_SPINE_TOKEN`) in-process; PWA sessions in `pwa-sessions.db` (SQLite, HttpOnly scoped cookies) |
| God's Eye | `exposure_intelligence.py` over an `EvidenceLedger` (`synthetic-and-public-lens.db`), `event_detection.py` (atomic JSON rule/alert store), `geo_ingest.py` (SQLite event store) |
| Intelligence | `geo_ingest.py` (SQLite), `rag_grounding.py` + `local_knowledge.py` (FAISS + files), `governed_knowledge.py` (SQLite) |
| Evidence | `evidence_product.py` (append-only hash-chained SQLite ledger) and `evidence-lens.db`, with artifact bytes in `PRIME_DATA_DIR/artifacts` (SHA-256 addressed files) |
| Memory / events | `jarvis-memory.db`, `portfolio-events.db` |
| Runtime gates | `action-harness.db`, `failsafe.db`, `agent-authority.db` (SQLite event ledgers) |

Large documents and evidence files already stay out of the databases: artifacts
are stored as files under `PRIME_DATA_DIR/artifacts` and addressed by content
hash, which is the correct object-storage boundary for this deployment.

## PostgreSQL is not part of ORQEVIA

`requirements.txt` has no `psycopg`, `asyncpg`, or `SQLAlchemy`; the runtime uses
the standard-library `sqlite3` driver. `docker-compose.yml` defines no database
service (only the app, Ollama, Caddy, and Cloudflared). Supabase/PostgreSQL
references belong to **other products** — the-portal (private PRIME tables) and
game-platform (Living Worlds) — plus an outbound public trace relay, not to
ORQEVIA's own storage.

## Hardening delivered

`scripts/sqlite_backup.py` adds verified, non-destructive backup, integrity
verification, and restore testing for the SQLite stores:

- online backup via SQLite's `Connection.backup()` (read-consistent, source
  opened read-only);
- `PRAGMA integrity_check` and `PRAGMA foreign_key_check` verification;
- restore testing into a scratch file that never mutates a live database;
- a SHA-256 manifest for every backup.

Integration tests in `tests/test_sqlite_backup.py` cover backup row
preservation, integrity/foreign-key checks, WAL sidecar discovery, and restore
round-trip row counts.

## Completed vs deployment-required

Completed (source): the architecture report, the backup/restore-test tool, and
its tests. Deployment steps still require authorization: installing the tool
into the ABEX runtime and scheduling automated backups is an operational change
owned by ABEX, not performed here.
