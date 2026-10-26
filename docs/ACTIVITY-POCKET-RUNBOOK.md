# Activity Pocket Factory operations

The Factory extends the existing Academy, Library, Tools and workflow executor.
It requires no ORQEVIA inference or orchestration service for independent
execution. This candidate is not a production deployment receipt.

## Install and verify locally

Use Python 3.12 and the existing locked development environment:

```powershell
uv sync --frozen
uv run python scripts/export_pocket_contracts.py --check
uv run python scripts/verify_activity_pockets.py
```

The verifier runs a controlled HTTPS server with a transient test CA, actual
registered tool handlers, the existing workflow executor, SQLite persistence,
Academy assessments and independent expected records. The server closes at test
completion. It does not depend on unrestricted live websites or production
credentials. Domain qualification records in this demonstration are explicitly
synthetic fixtures, not live agent certificates. Receipts and sample outputs
are exported under `.artifacts/activity-pockets/`.

## Runtime composition

`app.production_entry` starts one sequential Factory worker in its existing
lifespan. `app.interface_server` mounts the same management and objective APIs;
both processes must use the same existing data volume and trusted source
configuration. Database leases fence concurrent workers and HTTP executions.
No new service, exposed HTTP port, inference queue or queue guard is introduced.

In the ORQEVIA workbench, Operations links to `/activity-pockets`. This console
shows actual owner-scoped state, sources, artifacts, evaluations, decisions,
recovery records and all-agent evidence. An empty source configuration is shown
as `NO_AUTHORIZED_SOURCES`; missing worker observations remain explicit.

For independent operation, run the same API with the existing HTTPS certificate
and trusted session store, then open `/activity-pockets`:

```powershell
$env:ORQEVIA_DATA_DIR = 'C:/path/to/owner-controlled-data'
$env:ORQEVIA_RUNTIME_REVISION = '<the exact 40-character deployed source revision>'
$env:ORQEVIA_POCKET_SOURCES_FILE = 'C:/path/to/reviewed-sources.json'
uv run uvicorn app.activity_pockets.api:app --host 127.0.0.1 --port 8445 --no-proxy-headers --ssl-certfile C:/path/to/server.crt --ssl-keyfile C:/path/to/server.key
```

The independent API starts its worker automatically. A separately supervised
worker is also supported: `uv run python -m app.activity_pockets.worker`.
`--once` performs one bounded transition and prints its receipt. Use the same
data directory, revision, source file and public qualification verifier settings
in every process. Authentication reuses `app.pwa_sessions`; it does not invent
an account store or accept an agent-supplied owner identity. Existing trusted
sessions remain in their owning directory. New sessions are established through
the existing ORQEVIA session procedure, never by copying secret values.

## Sources and qualification

Start with `config/activity-pocket-sources.example.json`. An empty list grants
no source access. A trusted operator may add an explicitly authorized source:

```json
{
  "schema_version": "1.0",
  "sources": [{
    "id": "approved-catalogue",
    "urls": ["https://catalogue.example.org/explicitly-permitted-page"],
    "owners": ["the authenticated owner_scope from the status API"],
    "terms_reference": "Written permission or applicable published terms and review date",
    "allow_private": false,
    "min_interval_seconds": 1
  }]
}
```

The example hostname grants no actual permission and is not an acceptance source.
Only exact configured HTTPS URLs are retrievable. Source IDs on the same origin
share pacing and leases. DNS resolves to a checked, pinned address, hostname and
certificate verification remain enabled, and redirects/proxies/plaintext
fallback are absent. Private addresses require an explicit boolean permission
in trusted configuration; the controlled fixture uses this for its loopback
HTTPS server. Pages, agents and API requests cannot modify source policy.

Robots directives are checked. A permission snapshot may be persisted for one
page when a source delay exceeds a worker step; a later due attempt continues
without endlessly re-fetching robots. The snapshot expires and is consumed
after the page succeeds. Source delays and Retry-After are respected without
occupying an inference queue. Terms permission remains a human/operator input;
the system cannot infer legal permission merely from a successful response.

The reference supports UTF-8 static HTML catalogue records: `article` elements
with `data-id`/optional `data-currency`, and named `data-field` values. It rejects
invalid IDs/prices, duplicates and obvious personal-contact fields. This is a
bounded non-personal catalogue contract, not a general privacy classifier.
Authenticated pages, JavaScript rendering, CAPTCHA bypass and arbitrary domains
are outside this reference capability.

The existing `AgentCertificationRegistry` admits only current baseline and role
evidence for selected agents. Registration alone cannot pass admission. Public
Azure verifier configuration and its evidence root must be identical in backend
and Interface processes. `deploy/activity-pockets.compose.yml` is a reviewable
optional overlay supplying the same read-only source file and verifier enablement
to both services. It has not been applied by this work. Custom public pin files
and hashes, if used, must also be provided identically through the existing
configuration mechanism. No private signing key belongs in Factory configuration.

Fleet-wide live coaching completion and current 21/21 qualification work were
**parked by the Owner during this mission**. The coverage API preserves actual
coaching freshness, per-agent grades and all 29 owned responsibility projections;
it never turns the parked work into a pass or uses internal grades as certificates.

## API contract

All management calls require HTTPS and an existing persisted session. Mutations
also require the matching Origin. These checks remain scoped to Factory even
if the wider estate uses open-access mode. Responses are owner-scoped and
uncached. The ten generated JSON schemas live under
`contracts/activity-pockets-v1/`; runtime Pydantic models are their authority.

| Method and path | Operation |
| --- | --- |
| `GET /api/activity-pockets/status` | Configuration, worker freshness, source visibility, audit integrity |
| `GET /api/activity-pockets/coverage` | Existing fleet coaching snapshot and independent capability projections |
| `GET /api/activity-pockets/tools` | Actual provisioned read-tool contract |
| `GET /api/activity-pockets` | Up to 100 owned pockets, with explicit states and evidence |
| `POST /api/activity-pockets` | Create from PocketManifest; require Idempotency-Key |
| `POST /api/agents/objectives/activity-pocket` | ORQEVIA objective adapter, same Factory; require ORQEVIA provenance and Idempotency-Key |
| `GET /api/activity-pockets/{id}` | Lifecycle, outputs, costs, proposals, evaluations, decisions, recovery |
| `GET /api/activity-pockets/{id}/events` | Ordered hash-chain evidence |
| `POST /api/activity-pockets/{id}/execute` | One bounded step; body contains idempotency_key; worker normally executes automatically |
| `POST /api/activity-pockets/{id}/{pause,resume,cancel,retire}` | Validated lifecycle transition |
| `POST /api/activity-pockets/{id}/promote` | Owner decision bound to proposal_id, evaluation_id and reason |
| `POST /api/activity-pockets/{id}/rollback` | Owner restores previous pinned version using decision_id and reason |
| `POST /api/activity-pockets/{id}/revalidate` | Reassess a previously approved pinned artifact under current code; cannot change it |
| `POST /api/activity-pockets/emergency` | Set stopped boolean for this owner's pockets only |

Use the console to create a pocket without writing a manifest by hand. Every
pocket has an objective, authenticated owner, sources, permitted operations,
resource budget, success criteria, stop conditions and retention policy. The
reference's machine-enforced success contract is valid complete catalogue
records with provenance; free-text success criteria are a visible owner objective,
not an arbitrary executable acceptance language.

## Coaching and promotion

The Academy records observed failures, and `app.agent_coaching` proposes only
reviewed declarative field aliases. Seven held-out cases test the old layout,
unseen changed/mixed layouts, inert source instructions, invalid numbers,
personal-contact rejection and duplicate provenance. The bundled original
artifact has separately recorded scoped baseline admission; it does not claim
support for new layouts before promotion.

Evaluation never publishes a new version. The authenticated owner reviews
evidence and explicitly promotes it. A different registered evaluator owns the
acceptance record; the proposer/worker cannot approve itself. Candidate digest,
source revision, current suite digest, passing independent criteria, previous
version and ownership must match. The Library retains immutable versioned
artifacts. Pockets keep their pins; other pockets are not silently upgraded.

After a code upgrade, bundled baseline admission is rerun additively when needed.
Previously approved candidate artifacts pause for explicit current-code
revalidation, preserving their earlier evidence and owner decision. Revalidation
cannot change an artifact, grant a tool or bypass a quality-failure pause.

## Shutdown, restart, recovery and rollback

A nightly shutdown stops local activities. It does not require DigitalOcean.
On the next normal Docker/application startup, the existing startup path starts
the Factory worker. No new Windows recurring task is installed here.

Claims, attempt identity, cursor, reservations and state are committed before
retrieval. Expired leases recover read-only work; old completions are fenced and
discarded. Interrupted attempts conservatively charge their reserved bytes and
at most their reserved execution seconds. Eight hours powered off never become
eight hours of execution. Attempts/retries remain bounded. A very small remaining
budget may intentionally stop recovery rather than invent unused allowance.

Cancellation/pause survives restart and does not get overwritten by recovery.
Graceful stop waits for the current bounded step; abrupt power loss follows the
lease path. A daemon DNS lookup cannot prevent interpreter shutdown. Retention
purges expired retired-pocket outputs/training/linked feedback, records the purge
and preserves decision/evidence hashes. Durable Academy IDs do not repeat after
purge. Back up the database consistently with SQLite backup or a quiesced volume;
do not copy only an active main DB while omitting its WAL.

Rollback restores an existing Library pin and leaves evidence intact. It does
not undo a website change or erase output history. Already consumed sources are
not accidentally executed again after a completed-pocket rollback/resume.
Reprocessing is an explicit new pocket/objective with its own identity.

## Monitoring and troubleshooting

`READY` means due work can run; `PAUSED` includes its reason; `COMPLETED` means
all configured pages produced valid output. `FAILED`, `BUDGET_EXHAUSTED`,
`CANCELLED` and `RETIRED` remain distinct. Inspect owned events and worker
freshness before assuming an idle process is stuck.

| Finding | Action |
| --- | --- |
| HTTP 401/403 | Restore the existing session; check ownership, Origin, source permission and selected qualification |
| HTTP 409 | Inspect manifest/idempotency binding, lifecycle and integrity; do not blindly replay a changed request |
| HTTP 503 | Supply exact source revision/configuration and writable persistent storage |
| `NO_AUTHORIZED_SOURCES` | Review a source file and configure both processes; no public domain is implicitly approved |
| `QUALITY_FAILURE` | Review Academy proposal and held-out results, then owner promotion or rollback |
| `SKILL_REVALIDATION_REQUIRED` | Revalidate the existing approved artifact under current source |
| `SOURCE_NOT_DUE` / `SOURCE_RATE_RETRY` | Worker resumes when the source's permitted time arrives |
| Stale heartbeat / storage error | Inspect fixed worker error type in process logs; restore storage and let startup recover leases |
| Audit integrity failure | Preserve the original files and restore a known-good verified backup; never rewrite failures into passes |

The evidence chain detects record/event changes against retained hashes. It is
not an externally anchored immutable ledger: an administrator who can replace
the entire database and every exported anchor can rewrite history. Export and
retain the head/hash receipt separately when operational assurance requires it.

Local controlled tests, CI, installed deployment, live source authorization,
security review and production operational readiness remain separate evidence.
