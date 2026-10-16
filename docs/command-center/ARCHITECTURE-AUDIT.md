# ORQEVIA Command Center — Phase Zero architecture audit

Date: 2026-10-16. Branch: `codex/orqevia-command-center-20261016` (from `origin/main` = 4c99633).
This audit was produced by inspecting the actual repository source; nothing below is assumed.
Status vocabulary: Implemented / Tested / Verified / Deployed / Blocked.

## 1. What the system actually is

**One product, two runtimes, three surfaces.**

| Layer | Reality (verified in source) |
|---|---|
| Frontend | Vanilla ES-module PWA in `clients/pwa/` — `index.html` + `app.mjs`, `core.mjs`, `dashboard.mjs`, `intelligence.mjs`, `knowledge.mjs`, `workspace-tools.mjs`, `voice.mjs`, `storage.mjs`, `release.mjs`, `sw.js`, plus four CSS layers (`style.css`, `dashboard.css`, `intelligence.css`, `knowledge.css`). No framework. ~2,500 lines of modules; 12+ dedicated `*-tests.mjs` Node suites. |
| Backend | Python FastAPI app in `app/` (entry `app.production_entry:app`): objective workflow, PWA sessions/pairing (`pwa_sessions.py`), interface node + telemetry (`interface_node.py`), agent dispatch/registry, compute queue, intelligence companion (USGS geo ingest, detection, RAG), governed knowledge (local document intelligence), evidence product, certification stack, coaching, spine/action-records. SQLite stores on the `prime-data` volume. |
| Serving | Docker Compose project `prime-epoch-20260919`: `prime` backend (127.0.0.1:8000), `ollama` (127.0.0.1:11434), `interface` (TLS 192.168.1.23:8443, serves `/pwa/`, proxies `/api/orqevia/*`), `orqevia-coaching`. Interface image is built additively from this repo (`deploy/Dockerfile.interface-intelligence-abex` copies the PWA assets into `/app/app/pwa_static/`). |
| God's Eye | Real geospatial views already exist: `app/orqevia/static/gods-eye/{index.html,gods-eye.js,gods-eye.css,map.html,map.js,map.css}` — the map renders stored USGS observations with freshness; the formal semantic projection is preserved separately and stays out of PWA privilege (per `docs/GODS-EYE-INTEGRATION-AUDIT-20261015.md`). |
| Auth model | PWA pairing codes (OWNER/MEMBER), 90-day durable device sessions, per-account task/artifact ownership enforced server-side; protocol string `jarvis.interface.v1` is a load-bearing compatibility identifier (do not rename). |

## 2. Live API surface the Command Center can bind to (verified strings)

| Domain | Endpoints |
|---|---|
| Session | `GET /pwa/api/session` (trust/role/expiry), pairing + enrollment flows |
| Telemetry | `GET /interface/v1/telemetry` (authorized aggregate metrics; explicit UNKNOWN when host collector is unconfigured — `docs/ABEX-RUNBOOK-20261016.md`) |
| Intelligence | `/api/orqevia/intelligence/{health,sources,geo/events,geo/radius,detection/alerts,history/timeline,rag/retrieve,ingest/run}` |
| Knowledge | `/api/orqevia/knowledge/{health,documents,ingest,reindex,retrieve,answer}` (local AI, source-grounded, citations) |
| Objectives/tasks | Objective submission + task polling + artifacts via `app.mjs`/`core.mjs` client (`InterfaceAPI`), evidence lens routes |
| Agents | Registry (canonical 21; `a01…a29` historical), capability broker `/api/capabilities/permissions`, coaching controller |

Every panel added to the UI must bind to these real routes; unknown reality must render as
UNAVAILABLE/UNKNOWN — never fabricated metrics.

## 3. Design system reality

`clients/pwa/style.css` already defines a token root (`--bg`, `--panel`, `--line`, `--muted`,
`--text`, `--accent`, `--danger`, `--radius`, `Inter`). The fastest correct path to the
military-inspired command theme is a token re-skin layer loaded last, then progressive
structural work — not a rewrite.

## 4. Transformation plan (increments)

1. **L1 — theme + tokens (this commit):** `clients/pwa/command-center.css` (deep-navy/tactical
   palette, mono numerals, panel depth, focus states, reduced-motion), linked after all
   existing sheets; interface Dockerfile updated to ship it. No layout behavior changes.
2. **L2 — Command Shell:** topbar/nav restructure (domain nav: Overview, God's Eye,
   Intelligence, Operations, Evidence, Agents, Coaching, Data), connection/status chrome,
   mobile navigation defect sweep (safe-area, overlap, scroll traps), status tokens.
3. **L3 — Domain workspaces:** God's Eye workspace on the real map/geo APIs; Intelligence
   console on RAG/ingest APIs with explicit unknowns; agent readiness matrix from registry +
   telemetry; evidence inspector on the ownership-enforced routes.
4. **L4 — hardening:** a11y pass, reduced-motion, contrast, request cancellation, error
   boundaries per panel, security review of new handlers, dependency check.
5. **L5 — verification:** Node PWA suites (12+) + pytest subsets + browser screenshots at
   390/820/1440; mobile defect checklist; then release candidate + rollback notes.

## 5. Risks / constraints respected

- `STATUS.md` byte-pins + CI: no STATUS.md edits on this branch.
- `sw.js` caching: asset list changes require a cache-version review (planned L2).
- Load-bearing legacy identifiers (`PRIME_*`, container names, `jarvis.interface.v1`) remain.
- No fabricated claims: unauth surfaces render 401-conditional states; metrics render
  UNKNOWN until the host collector is provisioned (runbook step, already documented).
- Node for PWA tests: not on PATH in the owner shell; the Codex runtime's bundled
  `node.exe` executes the suites (verified available).

## 6. Completion matrix (living)

| Deliverable | State |
|---|---|
| Architecture audit (this doc) | Implemented, evidence-cited |
| Integration map (§1–2) | Implemented |
| L1 theme layer + Dockerfile ship | Implemented; Node suites green |
| L1.1 responsive fit (web + iPhone) | Implemented (browser QA pending) |
| Zero-tap open access (session auto-admit) | Implemented; pytest 4 + 32 green locally |
| L2–L5 | Planned |
| Security verification report | Planned |
| Deployment + rollback | Not started (blocked until RC) |
