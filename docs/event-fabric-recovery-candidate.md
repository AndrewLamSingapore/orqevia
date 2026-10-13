# Optional EventFabric recovery candidate

This source candidate repairs the disposable-store failures reproduced on
`fd47eab861da52a928d3c4a89fc2bb29181ccb58`: concurrent projection and retry after
committed memory produced two episodes, and two producer-local subject IDs
collapsed into one graph node. Original discovery receipts remain retained.
The component remains optional and unmounted in the current production entrypoint.

`MemoryStore.record_episode` accepts an optional event idempotency key and entire
canonical-event fingerprint. The episode and its `(source,event_id)` binding
commit in one SQLite transaction. Replays return the original GUID. A guarded
JSON expression index finds exact legacy event matches without scanning every
episode from that source on each new event. Identical historical duplicates
remain readable and their IDs are disclosed; deterministic adoption uses
`created_at,episode_id`. Conflicting historical content, a changed fingerprint,
or a missing/changed bound episode fails without a compensating insertion.
Legacy adoption cannot recover the full historical event fingerprint or wire bytes.

The new graph table uses `(source,original local node_id)` as its key. `graph()`
retains local `node_id` and exposes `source` and the unambiguous JSON tuple
`scoped_node_id`; consumers must use that scoped identity across producers.
Original event IDs, subject IDs, payloads and URLs are unchanged. A one-time
transaction rebuilds the derived view from the retained inbox without replaying
memory or actions. Inbox arrival order, with event ID as the deterministic tie
break, prevents an old projector retry replacing a newer node. The original
table is untouched and accessible through `legacy_graph()`. Unreconstructible
events and orphan legacy nodes remain explicitly unresolved, without assigning
a source from a label or untrusted hint.

An optional keyword-only `original_envelope` calls the separately owned
`portfolio_event_compat.validate_original_envelope` helper before inbox writes.
Its exact validated raw bytes, version/schema pins and canonical digest commit
with the new inbox row before projection. Changed bytes or pins fail closed.
Existing rows without original bytes reject attempted backfill as
`ORIGINAL_WIRE_UNKNOWN`; default legacy ingestion/replay remains available.
Custody is provenance data and grants no authentication, authority or evidence
maturity. No original wire bytes are invented during graph recovery.

Owner pause checkpoint, 13 October 2026: 71 focused tests passed, including real
thread/process concurrency, commit-before-receipt crash/reopen, atomic rollback,
legacy GUID/duplicate/conflict recovery, indexed lookup, scoped graph migration,
orphan disclosure and envelope storage using an explicitly labelled validator
fixture. Independent earlier working-source probes passed nine cases; the later
index and envelope changes still need final independent revision review.
Real pinned V2/V3 helper integration and the full source suite remain pending.
No production database, runtime mount, authentication, provider, role prompt,
identity/session module or deployment was changed. Resume only on Owner direction.
