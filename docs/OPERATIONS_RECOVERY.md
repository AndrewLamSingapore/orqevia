# Runtime observation and recovery

This extends the existing PRIME architecture and operator, not the authority
plane. Production remains HOLD. The read-only Control Surface boundaries,
single-slot Harness pilot and consumed-authorization semantics are unchanged.

## Health and diagnostics

`GET /api/control-surface/trusted/operator-status` uses existing trusted-local
authorization. `?diagnostics=true` adds component evidence. Missing ledgers are
opened with SQLite `mode=ro` and `query_only=ON`; status cannot create or repair
them. Each connection closes. Local model readiness reads tags, never inference.

Required store or signer evidence failure, uncertain execution, and unqualified
concurrency produce SAFE_STOP. Exhausted worker recovery produces ACTION_REQUIRED.
Unavailable local reasoning, compute records or workers produce DEGRADED. Cloud
availability is irrelevant while the pilot disables cloud. HEALTHY describes
only successful runtime checks, never production qualification. This endpoint
does not mutate or suspend the scheduler; execution continues to depend on its
independent PDP/PEP checks. Last successful verification is process-local and is
explicitly labeled as such; after restart it is unknown until a check succeeds.

`JARVIS.cmd status` uses the same summary. The existing PowerShell operator accepts
`-Diagnostics` for container details and `-Action verify` for contract plus status
checks. No new CLI, background installation or network surface is introduced.

## Recovery evidence and state safety

Queue infrastructure recovery retries at 1, 2, 4 and 8 seconds and stops after
five consecutive failures. Each transition uses `queue.recovery` in the existing
queue event table with version, worker, attempt, error type, state and explicit
`authority_expanded=false`. Database-outage events are buffered only within the
bounded retry episode; they are persisted before new admission after recovery.
Structured process logs retain evidence if the store remains unavailable.

An execution failure is not permission to reissue a consumed signed lease.
Completion persistence failure does not call the provider again. A stop timeout
retains the live worker identity and prevents a replacement. Exhaustion appears
in worker health; it does not launch an unbounded restart loop. New recovery
records do not prune authority, replay or decision evidence.

Existing Docker logging uses 10 MB files with three retained files per configured
long-running service. Existing Compose defines dependencies, readiness, grace
periods and persistent volumes. Its `unless-stopped` process restart policy is
not a bounded ABEX crash-loop policy and is not represented as one. A qualified
ABEX supervisor must implement the frozen commissioning contract on the actual
host. No systemd, TPM or provider identity is guessed or commissioned here.

EventFabric closes SQLite connections and records error types without raw
exception strings, which may contain credentials or private content. Existing
event schemas and projections are preserved. No new authority ledger is created.

## Dependency and acceptance evidence

The original development environment's OSV scan identified affected versions of
cryptography, pip, pypdf, python-multipart and Starlette. Candidate dependency pins
were updated using current PyPI metadata and tested in a fresh isolated Python
3.12 environment. Original environment and production installation are untouched.
The final scan and test evidence are in the delivery report. A clean version
scan is not a penetration test or production vulnerability assessment.

The routing corpus now includes bounded arithmetic, UTF-8 hashing, exact existing
schema validation and canonical agent lookup. A negative schema validation is a
successful deterministic answer; malformed requests reject. Lookup does not grant
scope or execution authority. Explicit deep roles cannot silently use a fast-only
provider. No dedicated Web3 tier policy is invented.

Existing `COMPUTE.md`, local benchmark script, portfolio corpus and 50-case
endpoint tests were found. A distinct versioned Compute Profile Benchmark Protocol,
its addenda and complete ABEX Workload Corpus were not identified in this checkout.
Do not label the endpoint fixture as that frozen hardware protocol. Actual ABEX
benchmarking, service reboot/rollback, protected-root and provider isolation
qualification remain pending.

## Result persistence recovery

The worker keeps at most one completed result pending in memory while it retries
saving it through the existing queue. It flushes that result before expiring
leases or claiming more work. It never invokes inference to repair a save.
A lost completion acknowledgement is settled only by matching durable status,
attempt number, result, usage and cost. Conflicting records are not overwritten.
The existing five-attempt/backoff limit applies. Active recovery is DEGRADED;
exhaustion is ACTION_REQUIRED. A process crash can still lose an unsaved in-memory
result; this does not create permission to reuse consumed authority. Physical
crash/reboot qualification remains in the owner-parked hardware track.

## Advisory provider output

The local worker validates the response object, message and nonempty text.
Supplied completion, model and role fields must match the advisory request.
Structured tool calls are rejected and recorded as ProviderToolCallRejected in
the existing compute ledger, without recording provider text or tool arguments.
Malformed replies fail the job; consumed authority is never automatically reused
for a retry or cloud fallback. Existing uncertain-outcome handling remains intact.
Job reads always label results advisory and external_action_verified=false.
Model prose, including claims of completed actions or bypass suggestions, grants
no authority and is never parsed into executable commands. This is structural
validation and evidence labeling, not a claim of semantic truth verification.

Recovery inventory now saves only container identities, images, mounts and
basic inventory; it excludes container commands and environment configuration.
Previously written inventories are not silently deleted and may still contain
secrets. This inventory is not a database backup or an automated rollback
contract. Updates must not be described as safely reversible across arbitrary
schema or authority-state changes; qualified backup/restore and migration
compatibility evidence are still required before enabling automatic rollback.
