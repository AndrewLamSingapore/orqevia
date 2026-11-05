# Console status reads without repeated full-history verification

Actual authenticated production acceptance found that the Console's status read
could exceed its existing 20-second deadline. Each automatic dashboard refresh
called full SQLite structural checks, replayed about 88,000 audit-event hashes
and compared every materialized record in a roughly 490 MB registry.

Read-only profiling on 5 November measured 8.35 seconds for metrics, including
7.20 seconds in integrity verification. A candidate evaluated in a disposable
read-only child took 1.61 seconds, with no integrity replay. Production appended
between observations and resource contention varied; these are observations,
not a controlled whole-system speedup or intelligence-quality claim.

Routine `GET /api/collective/v1/status` now returns current scoped counts and
`registry_health: NOT_CHECKED`. Its integrity result has null verification
fields, zero events checked and no verification time. It does not reuse an
earlier PASS, hide a failure or grant execution authority.

The same authenticated route with `?verify_integrity=true` runs the original
full checker and returns the actual PASS/FAIL result. The existing owner-bound
`/interface/v1/collective/status` bridge forwards this query unchanged. Owner,
tenant, cookie, origin and service-token checks retain their existing behavior.
No additional route, service, cache, queue, approval stage or product timeout
is introduced.

Other Python callers keep full verification by default:
`CollectiveStore.metrics()` and `.snapshot()` retain their previous semantics.
Only the dashboard's `board_status()` path opts out of repeated replay by
default. The full integrity algorithm, audit chain, SQLite protections,
financial boundaries and all stored data remain unchanged.

Focused regressions verify that automatic polling never calls the full checker,
explicit verification still detects actual record tampering, other owners see
only their own counts, existing full defaults remain intact and the real bridge
preserves the explicit query and authentication boundaries. Release qualification
also includes the full local Python suite and canonical CI. Dated actual runtime
and browser evidence lives in the ABEX operational sweep receipts; deployment
must be verified separately from this source change.

Release only the backend for this correction. The already qualified interface,
coaching, intelligence, collector and native knowledge processes need no restart.
Retain the previous backend image/configuration and preserve all accepted work;
rollback must not replace current databases with older snapshots.
