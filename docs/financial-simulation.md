# Financial autonomy simulation candidate

This source implements Stage 0 with synthetic money. It adds no real payment
adapter, account, funding connection, credential activation or production change.
It does not establish active model identities, L7 acceptance or live financial readiness.

## Owning contracts and entry points

`config/agent_registry.json` and `app.agent_registry.load_agent_registry` own the
21 immutable IDs. PRIME is the orchestrator, not a 22nd wallet. Retired aliases
are resolved by existing responsibility routing; financial wallets use canonical
immutable IDs only. Existing `client_auth.authenticate_owner` authenticates all
network entry points. No agent-controlled identity/policy/approval field is accepted.

`app.financial_simulation` owns policy and treasury authority. It is deliberately
separate from model prompts and uses integer USD cents. Its constructor receives
owner-controlled funding, ceiling and policy; each canonical agent gets an individual
logical wallet and independent daily/monthly allowance. Fresh price quotes bind
agent, service, merchant, amount, currency, provider, nonce and expiry with an
authority-only HMAC. Missing/unknown fields, providers or identities fail closed.

`app.financial_simulation_api` supplies authenticated discovery, quote, owner
freeze/suspension/revocation/approval/refund, transaction lifecycle and report
routes under `/api/financial-simulation`. All remain disabled unless
`PRIME_FINANCIAL_SIMULATION_ENABLED=1`. This is a candidate opt-in, not a production
installation instruction. No existing spending policy or live sink is loosened.

The existing `/api/agents/objectives` and `/api/agents/dispatch` accept the
`financial_simulation` deterministic operation. An actual owned capability resolves
the agent; a signed quote is submitted in context with exactly `quote`,
`idempotency_key` and `objective`. The financial objective must match its enclosing
owner objective. The operation requires R0, LOCAL_ONLY and max real cost zero.
The existing artifact factory and action records deliver the actual simulated
service result and receipt. No inference workers/model calls are started by this
operation. The simulated service computes a digest and word count of the paid
objective; it is labelled synthetic throughout, not presented as external data.

## Treasury, decisions and accounting

Initial simulation funding is $100 with a $100 gross spending ceiling. Default
agent policy allows only simulation.local, the three source-owned simulated
services and USD: $5 per purchase, $10 daily, $50 monthly, owner approval above
$2, and five new requests per minute. A $6 quote tests per-purchase denial.

Lifecycle: quoted -> requested -> authorized / waiting approval -> reserved ->
executing -> settled / failed / indeterminate -> reconciled. Denied, expired,
cancelled and refunded outcomes are explicit. Approval is stored against the
original transaction and cannot waive scopes, freeze or budget checks. Revocation
is permanent for that logical wallet; suspension is resumable by its owner.

SQLite `BEGIN IMMEDIATE` serializes every authority operation across threads and
processes; FULL synchronization commits policy/state/audit changes atomically.
Reservation and settlement both recheck authority. Pending/uncertain reservations
consume shared funds and limits, including across a date rollover. Gross charges
and refunds consume spending ceilings to prevent refund churn. Refunds restore
available simulated cash but do not erase spend history. Identity-bound idempotency
returns the original transaction; changed payloads and quote-nonce reuse are denied.

Only the local simulated provider can execute. It writes an idempotent receipt
under the same database transaction as financial state. Injected timeout/ambiguous
responses keep funds reserved. Recovery queries the original receipt and never
calls execute for a new payment. Missing records are provably not executed in this
specific transactional simulator; that rule MUST NOT be copied to external
providers where missing status means unknown. Failed/outage/partial outcomes never
settle. Cancellation cannot discard an uncertain reservation. Refunds are owner-only.

The separate balance invariant is `funding = available + reserved + net settled`;
`gross settled + reserved <= global ceiling`. Each settlement/refund must match its
provider receipt. Reconciliation checks these invariants before every operation.

## Audit and recovery boundaries

Every authority operation verifies an HMAC-chained append-only SQLite audit and
the signed latest state digest before changing state. Audit triggers reject updates
and deletion. Request decisions, quote prices, task IDs, identities, approval IDs,
state transitions, provider results and outcomes are durably committed together.
Credentials are redacted; only simulation authorization signatures are recorded.
An invalid audit/state/key fails closed rather than repairing or hiding evidence.

The simulator audit key is separate from SQLite, initialized atomically and never
returned in an API or artifact. It is a local integrity key, not a payment credential.
The service must run in an authority-owned directory inaccessible to agent tools.
POSIX file mode 0600 is requested; Windows ACL isolation is not established by that
mode. An administrator who controls the process/key/files remains trusted, and a
rollback of the entire authenticated store to an old backup is not detectable without
an independent external anchor. No external WORM anchor, Windows isolation,
regulatory/security certification or production-grade tamper resistance is claimed.
Those are live activation prerequisites, not reasons to stop simulation work.

SQLite crash rollback, restart of reserved transactions, reconciliation of both
ambiguous outcomes, no double settlement, freeze and revocation are executable
tests. Back up the database consistently (SQLite backup API) and preserve the
authority-only key separately. Never regenerate the key or funding to repair a
failure. An existing database without its key must not be reinitialized.

## Verification and design-only activation

Run `python -m pytest tests/test_financial_simulation.py
tests/test_financial_simulation_integration.py -q --junitxml=financial-tests.xml`.
Run `python scripts/financial_simulation_evidence.py --output <evidence-directory>
--runtime <isolated-work-directory> --junit financial-tests.xml` to exercise every
real canonical capability through the existing HTTP objective interface and emit
individual agent matrices, ledger, action records, artifacts and recovery evidence.
Only public synthetic objectives and test-owner authentication are used.

External adapters (Cloudflare Wallets, x402, MPP, API billing and future regulated
providers) are explicitly UNAVAILABLE_UNIMPLEMENTED. No speculative URLs or SDKs
exist. Stage 1 requires separate owner approval for one verified agent/provider
and a minimal real-money allowance, verified financial/regulatory controls,
authority isolation, durable externally anchored audit and rollback/readiness
receipts. Stage 2 requires fresh approval and accepted pilot evidence. Stage 3
requires individual admission of all selected agents under shared limits. Stage 4
requires ongoing reconciliation, anomalies/suspension and owner oversight. Stages
1–4 are design-only and cannot be enabled by a flag or passing simulation tests.

Source rollback: remove this candidate commit through the normal Git review process.
No deployed runtime or persistent production data is modified by this candidate.
