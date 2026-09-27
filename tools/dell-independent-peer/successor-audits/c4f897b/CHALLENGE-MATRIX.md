# Required independent coverage

These are future release requirements, not a claim that every category was executed in the initial audit. Each release must attach concrete test IDs and evidence or mark a category BLOCKED/UNPROVEN.

| Category | Independent falsification | Required result |
|---|---|---|
| Caller-controlled authority | Forge Owner/verifier/independent fields in caller payload | Server-owned authority prevails |
| Fabricated metadata | Model invents UUID/time/source/image/receipt | No promotion into trusted envelope |
| Model/system separation | Conflicting JSON, markdown and tool delimiters | Distinct trusted envelope and model content |
| Owner/Member | Cross-user IDs, artifacts, cache reuse, recovery/role races | No disclosure, mutation or inherited Owner power |
| Authentication/session | Expired/revoked token, restart, clock bounds, recovery | Correct denial and stable durable person identity |
| Duplicate/retry/timeout | Replay same key, changed payload, lost acknowledgment | One effect or deterministic conflict; bounded retry |
| STOP/COMPLETE | Stop at completion boundary and deliver late callback | One legal terminal state; no resurrection |
| TOCTOU/concurrency | Mutate evidence/state between check and commit | Atomic authorization and effect/evidence binding |
| Restart persistence | Crash after each persistence point | No orphan, duplicate or fabricated result |
| Tampered evidence | Alter/remove bytes/events/digests; replay attestation | Fail closed and preserve original failure |
| Stale state | Old receipt/version/source, moved tag | Cannot qualify new release |
| Prediction integrity | Future leakage and horizon not elapsed | Correct provenance; longer observation remains |
| Learning qualification | Reuse evidence; fake verification; missing outcome | Only qualified unique evidence creates lesson |
| Migration | Real predecessor fixture, partial upgrade/restart/version skew | Preserved data and deterministic recoverability |
| Backward compatibility | Old/new client-server combinations and stored schema | Declared compatibility or explicit rejection |
| Rollback | Restore previous image over migrated fixture | Rehearsed recovery without production mutation |
| PWA/cache | Mixed versions, stale worker, private cache, account swap | Accurate revision, upgrade and isolation |
| Offline/reconnect | Disconnect around submit/ack then reconnect | No fabricated connectivity or duplicate work |
| API/service outage | 401/429/500, malformed JSON, unavailable dependency | Bounded failure and truthful user state |
| Malformed input | Wrong types, absent fields, oversized data, traversal | Controlled rejection without authority or crash leak |
| Resource exhaustion | Small bounded queue/concurrency/size/time budgets | Enforced caps and recovery; no production stress |
| Task lifecycle | Queue/cancel/start/end/fail and replay combinations | Legal transitions and faithful receipts |
| Runtime/source/image | Green health with wrong image/source/runtime | Exact established mismatch is FAIL |
| Provenance/receipts | Self-certify independent:true; mix source/run evidence | Untrusted claims cannot authorize promotion |
| Read Aloud | Late callbacks, no terminal event, throwing APIs | Attempt ownership and bounded lifecycle |
| Physical outcomes | Real Owner device observation | Software events cannot prove audible speech |

All categories remain subject to explicit native Dell independence, source/image binding and evidence verification. Software passes are limited to measured assertions. DeepSeek suggestions are UNPROVEN until independently reproduced.
