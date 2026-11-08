# Compute-journal diagnostics and native worker heartbeat, 8 November 2026

This change addresses the two remaining P1 observation gaps without widening
any freshness bound, converting missing counts to zero, or submitting work
merely to make monitoring green.

## Classified compute-journal failures with bounded timings

`app/interface_telemetry.py` now returns `(activity, diagnostic)` from
`compute_journal_observation()`. The historical `agent_activity()` contract is
unchanged (per-agent projection or `None`). The diagnostic preserves:

- fixed classified reasons: `COMPUTE_JOURNAL_DATABASE_MISSING`,
  `COMPUTE_JOURNAL_SCHEMA_REQUIRED_COLUMNS_MISSING`,
  `COMPUTE_JOURNAL_TIME_BUDGET_EXCEEDED`, `COMPUTE_JOURNAL_SQLITE_ERROR`,
  `COMPUTE_JOURNAL_STORE_IO_ERROR`, `COMPUTE_JOURNAL_VALUE_ERROR`;
- fixed exception-class vocabulary only, never exception text;
- per-phase timings (`connect`, `schema`, `ranking_execute`, `objective_join`,
  `total`) against the unchanged 0.2-second opcode budget;
- a separate objective-join status that cannot silently discard join failures.

The telemetry snapshot now exposes the aggregate reason through
`queue_freshness.reason` / `queue_freshness.journal_status`, the
`compute_journal` block, and the `observed_agents` / `fresh_agents` metric
reasons. The ranking SQL itself is unchanged: it measured ~25 ms warm against
the 9,788-row production journal, and the earlier failure classified by the
new diagnostics was a bounded transient, not a slow-ranking regression.

## Native worker heartbeat

`JobQueue.record_worker_heartbeat()` maintains one monotonic row
(`backend_worker_heartbeat`) inside the existing compute-queue database. The
application's worker lifecycle now ticks it every 10 seconds with state
`ACTIVE` (a running job exists) or `IDLE`, carrying the runtime source
revision. It never submits, admits or mutates a job.

The host collector's `BACKEND_READ` observes the tick and
`backend_readiness_check` qualifies idle backend readiness only when the tick
is within the existing 120-second window and its `source_revision` matches the
container runtime revision:

- `PASS` `PERSISTENCE_AND_RECENT_EXECUTION_PROGRESS_OBSERVED` (unchanged) or
  `PASS` `PERSISTENCE_AND_NATIVE_WORKER_HEARTBEAT_OBSERVED` (new);
- `UNKNOWN` `NATIVE_WORKER_HEARTBEAT_STALE_OR_MISMATCHED` when only a stale or
  mismatched tick exists, preserving unknown instead of invented readiness.

Heartbeat evidence is worker liveness, not execution proof; the receipt limits
list now states `NATIVE_WORKER_HEARTBEAT_IS_LIVENESS_NOT_EXECUTION_PROOF`.

## Evidence ordering tie-break

The full local suite exposed a pre-existing nondeterminism: Windows timestamp
granularity produces identical `agent_authority_events.timestamp` values for
consecutive recordings (~40% of back-to-back pairs in a local loop), so
`AgentAuthorityRuntime.recent()` could return an older `allowed` row instead
of the newest `denied` row. `recent()` now breaks ties by `rowid DESC`
(insertion order); timestamp comparisons are unchanged. A regression test
forces equal timestamps and asserts the newest recording wins.
