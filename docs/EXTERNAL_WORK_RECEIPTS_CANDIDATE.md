# External work evidence receipts — isolated candidate

This branch adds `app.external_work_receipts` as an **unmounted**, opt-in
receipt/catalog boundary. It does not alter the Golden Gen 2 runtime, start a
worker, use inference, call GitHub, delegate a coding agent, or enter PRIME's
boot path. Its four focused tests exercise state transitions, authentication,
seven repository identities, citation selection, and rejection of credentialed
URLs. A passing test is source evidence, not a live PRIME participation receipt.

An authenticated local adapter can report `RECEIVED → DELEGATED → RETURNED`
or failure for a bound work ID, objective digest, and one of the 21 canonical
specialists. These are **reported states**, never Owner acceptance, merge,
publish, or proof of off-host execution. SQLite stores only bounded identifiers,
enumerated states, digests, and source URLs; no task text, model responses,
repository contents, GitHub credentials, or result artifacts. The Owner digest
is an index, not an evidence verifier. Any HTTP mounting must remain behind the
existing local same-origin control boundary and Owner authentication; it is
intentionally not mounted in `production_entry.py`.

The catalog recognizes seven separate repository identities: `prime`,
`velyqua`, `the-portal`, `sky-tablet`, `game-platform`, `authority-engine`, and
the `AndrewLamSingapore` profile repository. Each snapshot records a GitHub
source URL, exact commit SHA, timezone-aware observation time, confidence,
scope, check state, and evidence digest. Up to seven repositories and four
scopes per repository may be recorded per work item; duplicate repo/scope
snapshots fail closed. Task-specific specialist selection requires explicit
repositories, filters by advisory role/scope, returns at most four citations,
and excludes private PRIME by default. It does not put one raw blob into every
agent's context or treat reported CI/deployment state as authoritative.

The 27 September portfolio index is historical. The current audit reference is
`C:/Users/Admin/Documents/ABEX/recovery-records/live-promotion-20261003/GITHUB_REPOSITORY_AUDIT_20261003.md`;
each mirrored claim must carry its actual observed SHA and timestamp. Direct
private-repository API access from PRIME remains **unimplemented and unverified**.
It would require a separately provisioned, least-privilege authenticated
GitHub identity/token, plus live access and failure-path proof. Do not copy
Codex/GitHub connector credentials into PRIME or grant write scopes. Owner
authority and the canonical deployment/acceptance gates remain unchanged.

## Capability parity and the next boundary

| Capability | Candidate evidence now | Missing for live PRIME parity |
|---|---|---|
| Repository read | Seven identities and bounded cited snapshots; no fetch | Separate least-privilege GitHub read identity, freshness and permission proof |
| Repository write/PR | Unavailable | Task-scoped broker with explicit Owner approval for publish/merge |
| CI observation | Reported status and source digest only | Authenticated job/status fetch and evidence verification |
| Local files | Existing PRIME APIs and this isolated SQLite candidate | Scoped file broker, path allowlist, mutation controls and live proof |
| Browser/network | Not supplied by this module | Task-scoped connector and network allowlist; no ambient access |
| Dell verifier | No access | Independent read-only verifier channel, without identity borrowing |
| Cloud execution | Not supplied by this module | Separate cloud identity/budget, isolation and result attestation |
| Model routing | Existing local advisory routing; this module uses zero inference | Runtime benchmark and proof for any new capacity/path |
| Approval | Owner authority unchanged; receipts cannot ACCEPT/MERGE/PUBLISH | Explicit brokered Owner approval for irreversible actions |

The safe extension is a **task-scoped broker**: bind task ID, canonical agent,
allowed operation, repository/path, credential identity, expiry, budget and
evidence destination; deny everything else. A read identity must not inherit
Codex's write rights. PRIME may summarize independently verified receipts but
must not treat an external agent's claimed completion as Owner acceptance.
