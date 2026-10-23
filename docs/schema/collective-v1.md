# Governed collective board schema and operator contract

This component provides durable, tenant and owner scoped registry observations,
knowledge contributions, investigations, puzzles and remediation records. It
does not replace the canonical agent registry, Stable Spine, queue authorization,
notebooks, evidence stores or executor. Its routing interface is read-only shadow
routing. Knowledge cannot grant execution permissions.

Implementation: `app/collective_intelligence.py`; transport envelope:
`app/collective_contracts.py`; mechanism tests:
`tests/test_collective_intelligence.py`. The API version is `1.0`; SQLite
`user_version` and the first recorded schema migration are `1`.

## Physical schema

The normalized identity and provenance model uses six tables. Each logical
entity has an independently queryable SQLite view over the common record table.
This avoids duplicating tenant, owner, version and attribution columns across
thirty nearly identical tables. A record's document is validated by its fixed
command handler; documents cannot supply authority or SQL.

| Table | Purpose and constraints |
| --- | --- |
| `schema_migrations` | Version, application time and migration description. A newer schema fails closed. |
| `registry_records` | Composite primary key `(tenant_id, owner_id, id)`; kind, state, positive optimistic version, creator, canonical creator agent, creation/update times and valid JSON document. Indexed by scope, kind, state and time. |
| `registry_relations` | Typed, append-only links with composite foreign keys to both scoped records. Indexed by target. Links never cross tenant or owner. |
| `audit_events` | Immutable event identifiers, actor, canonical agent and authenticated queue execution, operation, subject, time, reason, evidence, complete record snapshot, previous digest and SHA-256 event digest. Separate chains per tenant and owner. |
| `command_receipts` | Scoped actor and idempotency key, request digest and original response. A key replay with different content conflicts. |
| `deduplication_keys` | Scoped kind and normalized finding fingerprint, with a foreign key to the original challenge or gap. |

Entity views: `agents`, `orchestrators`, `fabrics`, `capabilities`,
`agent_capabilities`, `fabric_capabilities`, `dependencies`, `policies`,
`evidence`, `models`, `health_snapshots`, `execution_records`, `knowledge_claims`,
`knowledge_contributions`, `knowledge_relationships`, `knowledge_reviews`,
`knowledge_challenges`, `challenge_evidence`, `challenge_resolutions`, `puzzles`,
`puzzle_requirements`, `puzzle_contributions`, `gaps`, `gap_assignments`,
`remediation_plans`, `remediation_executions`, `remediation_verifications`,
`lessons_learned` and `registry_versions`.

Every record creation and update receives a complete immutable event snapshot
in the same `BEGIN IMMEDIATE` transaction. Each significant workflow transition
also records its reason and evidence. Foreign keys, WAL, an eight second busy
timeout, optimistic versions and idempotent receipts protect concurrent writes.
Operations contain no arbitrary shell, network target, SQL or filesystem path.

`provision(principal)` reads the existing validated
`config/agent_registry.json` through `load_agent_registry()`. It mirrors the
21 canonical identities and 29 responsibility capabilities, with source SHA-256.
It preserves `model: unassigned`, advisory/restricted authority and actual
hierarchy. A changed canonical digest requires an explicit mirror migration;
contributions cannot edit the source mirror. Runtime health, qualification,
certification, authorization and contributions remain separate states.

Fabrics are not invented from a fixed count. A trusted service must publish an
observed, source-bound inventory using `registry.observe`. Source configuration
alone is `CONFIGURED`, not verified live. `OBSERVED` health and verified
integration require linked, successful attested execution evidence.

## Authentication boundary

The authenticated service creates `CollectivePrincipal(tenant_id, owner_id,
actor_id, agent_id=None, execution_id=None, roles=frozenset(...))`. Request bodies
must never supply principal roles, owner, tenant, or a verifier identity.

| Trusted role | Permitted use |
| --- | --- |
| `OWNER` | Scope reads, contribution, investigation, prepared plans, dispositions and an explicitly approved evidence-bound knowledge correction. Cannot mint execution or verification evidence. |
| `AGENT` | Requires an exact canonical identity and trusted completed queue execution. Can contribute, question, detect gaps and provide puzzle pieces. Assigned investigators/owners may advance their work. Cannot combine roles or attest execution/verification. |
| `SYSTEM` | Server-only source inventory and fixed execution observation adapter. May attest a completed existing queue inference, fixed fabric probe or authorized notebook indexing execution. |
| `VERIFIER` | Server-only independent observer. May attest verification and accept evidence-bound facts, challenge outcomes, puzzle completion and repair closure. Must differ from the relevant producer/executor. |

No principal may be constructed from a model's assertion of its own identity.
AGENT attribution is tied to the authoritative queue job, not an arbitrary agent
name in a POST body. The server adapters retain their existing authorization.
An unavailable registry cannot increase their authority.

## Python API

`command(principal, operation, payload, idempotency_key)` returns
`{api_version, record, replayed, authority}`. A record contains `id`, `kind`,
`state`, `version`, attribution, times and `data`. Every mutation of an existing
workflow record requires `expected_version`. `query(principal, kind, id=None,
filters=None)` supports only `state`, `limit` (1–200) and `offset` (0–10000).

Convenience reads: `lookup_agent`, `lookup_fabric`, `lookup_capability`,
`lookup_dependencies` (maximum depth four and 64 nodes), `lookup_policy`,
`lookup_evidence`, `lookup_health`, `lookup_knowledge`, `lookup_puzzle`,
`lookup_gap`, `trace_claim_provenance`, `find_conflicting_claims`,
`find_missing_capabilities`, `find_unresolved_dependencies`, `metrics`,
`snapshot` and scoped paginated `audit`.

`resolve_shadow` and its `resolve_task`, `resolve_execution_path`,
`resolve_fallback`, `explain_routing_decision` aliases evaluate canonical
capability ownership, trusted caller authorization and fresh observed health.
Certification requirements fail closed unless separately established. These
results always carry `execution_authorized: false`; they do not dispatch work.
Fallback absence is explicit. The trusted authorization mapping must not be
derived from contributed records or request data.

| Operation | Required payload; optional fields in parentheses |
| --- | --- |
| `evidence.record` | `content`, `source`, `kind`, `environment`; (`subject_id`, `execution_id`) |
| `claim.contribute` | `title`, `statement`, `evidence_ids`; (`classification`, `subject_id`) |
| `claim.review` | `id`, `expected_version`, `decision`, `reason`, `evidence_ids` |
| `claim.correct` | `id`, `expected_version`, `challenge_id`, `statement`, `reason`, `evidence_ids` |
| `knowledge.link` | `source_id`, `target_id`, `relation`, `reason`, `evidence_ids` |
| `challenge.open` | `target_id`, `question`, `reason`, `severity`, `evidence_ids`; (`reviewer_agent_id`, `actionable`, `gap_title`, `capability`) |
| `challenge.transition` | `id`, `expected_version`, `state`, `reason`, `evidence_ids` |
| `challenge.resolve` | `id`, `expected_version`, `outcome`, `reason`, `evidence_ids` |
| `challenge.reopen` | `id`, `expected_version`, `reason`, `evidence_ids` |
| `gap.detect` | `title`, `description`, `severity`, `environment`, `evidence_ids`; (`owner_agent_id`, `capability`) |
| `gap.transition` | `id`, `expected_version`, `state`, `reason`, `evidence_ids` |
| `gap.plan` | `gap_id`, `expected_version`, `objective`, `adapter`, `scope`, `restricted`, `evidence_ids`; (`root_cause`) |
| `gap.execute` | `gap_id`, `expected_version`, `plan_id`, `evidence_id` |
| `gap.verify` | `gap_id`, `expected_version`, `evidence_id` |
| `gap.reopen` | `id`, `expected_version`, `reason`, `evidence_ids` |
| `puzzle.create` | `title`, `objective`, `requirements`, `assigned_agent_ids`, `completion_condition`, `evidence_ids` |
| `puzzle.contribute` | `puzzle_id`, `expected_version`, `requirement_key`, `claim_id`, `evidence_ids` |
| `puzzle.complete` | `id`, `expected_version`, `reason`, `evidence_ids` |
| `puzzle.reopen` | `id`, `expected_version`, `reason`, `evidence_ids` |
| `registry.observe` | `kind`, `canonical_id`, `definition`, `source_sha256`, `evidence_ids`; (`health`, `integration_verified`, `model_assignment`) |
| `lesson.record` | `summary`, `evidence_ids`, `related_ids` |

Unknown payload fields fail validation. Errors expose a bounded message and
code: `invalid`, `denied`, `not_found`, `conflict` or `rate_limited`. Services
should map these to 422, 403, 404, 409 and 429. Infrastructure errors remain
explicit unavailable responses; they are never converted to success.

## Evidence and acceptance

The service computes `sha256 = SHA256(canonical JSON content)` and preserves
source, environment, actor and subject. `SOURCE` and `OBSERVATION` remain
untrusted. Trusted `EXECUTION` and `VERIFICATION` receipts are accepted only
from the corresponding server role. Agreement between agents is insufficient.

All trusted receipts include `plan_id`, `execution_id` and `candidate_revision`.
An execution includes `adapter`, `scope` and `outcome` (`SUCCEEDED` or `FAILED`).
The observation adapters are `queue_inference` and `fabric_probe`; inference
also requires `agent_id` and the observed `result_sha256`. They do not permit
repairs. Only `reindex_notebooks` is an executable low-risk repair adapter.

A verification includes `execution_sha256` and exactly three measured boolean
checks: `outcome`, `regression` and `security`. The adapter must measure these
from the actual service; accepting caller-supplied booleans would violate the
trust contract.

Claim verification binds `target_id`, `target_version` and `statement_sha256`.
Correction proof binds `target_id`, `target_version` and
`proposed_statement_sha256`; the owner then approves that exact correction.
Conclusive challenge resolution requires `target_id`, current `target_version`
and matching `challenge_outcome`. Known target environments must also match.
After a correction, the resolution proof must observe the new target version.
Registry definitions are never overwritten through claim correction.

Puzzle requirements each contain `key`, `description` and `evidence_criteria`.
Assigned agents provide their own attributed claims and linked evidence. The
assembly reports missing pieces and unresolved contradictions. Completion
requires a trusted independent verification whose `plan_id` is the puzzle ID
and `execution_sha256` matches the current `assembly_sha256`, including exact
claim versions. Changing supporting knowledge invalidates every completed
dependent assembly; no twenty-item truncation is applied.

Gap detection records DETECTED, TRIAGED and ASSIGNED atomically, with an
accountable canonical owner. Preparing a plan records PLANNED, or
AWAITING_APPROVAL for a restricted, high-impact or unknown adapter. A trusted
actual execution must match the current plan, exact adapter, scope and target
environment. A successful attempt enters VERIFYING; a failed attempt remains
BLOCKED. CLOSED requires an independent verifier, exact execution digest,
execution ID, revision, plan and environment, with all three checks passed.
The closure and reusable lesson remain durable. A code edit is not closure.

There is no generic autonomous shell executor, unrestricted repair service,
privilege editor, production cutover operation or paid provisioning path.
Restricted repairs remain prepared awaiting the existing approval/execution
mechanism. There is no automatic approval bypass or paid AWS dependency.

## Bounds and recovery

Payloads are capped at 32 KiB, depth twelve and one hundred list/object entries;
evidence references are capped at twenty. Suspected credentials/private keys
are rejected. Findings are deduplicated. Contributions are rate limited per
stable agent identity even when jobs rotate; challenges are limited to twelve
per hour, review cycles to three, and reopening has a thirty minute cooldown.
High-impact independently attested new content may override the cooldown, but
not the review-cycle budget. A scope has a ten thousand record budget.

`integrity(principal)` checks SQLite, foreign keys, the scoped event hash chain
and current record snapshots against the latest immutable event. A host
administrator can replace an entire database; an independently retained chain
head/backup digest is needed to detect that stronger threat. The dashboard
must not describe this local mechanism as remotely notarized or tamper-proof.

`backup(new_host_owned_path)` uses SQLite's online backup API, verifies the copy
and returns its SHA-256. `CollectiveStore.restore(backup_path,
new_destination_path, expected_sha256=...)` verifies the approved digest and
restores into a new file. Existing databases are never overwritten. These are
host-operator APIs; no HTTP request may choose filesystem paths. Preserve the
previous release and database when promoting a new local service. Roll back by
stopping only that owned service and selecting its preserved release/database;
do not overwrite the active database or remove shared production volumes.

Snapshots are private, read-only observations with explicit unavailable/stale
semantics. A cached snapshot cannot accept mutations or authorize execution.
Metric counts distinguish registered/configured pathways, authenticated
contribution attribution, and contributors with matching attested actual queue
execution evidence. None of these counts imply general model qualification,
certification, twenty-one independent workers or all gaps being closed.

## Evidence boundary

The mechanism suite uses real temporary SQLite databases, canonical identities,
scoped principals, concurrency, receipt binding, hashes and backup restoration.
Its synthetic service observations are explicitly fixtures. Passing this suite
establishes the mechanism's tested behavior. Final live acceptance additionally
requires real authenticated queue jobs, service adapters, desktop/mobile API
journeys and observed recovery in the intended deployment. Record those receipts
separately; never relabel these fixtures as live operational demonstrations.
