# Activity Pocket Factory acceptance and closure register

This register distinguishes executable controlled acceptance from deployment.
The latest Owner scope and explicit eight-item parking register are in
[ACTIVITY-POCKET-STATUS-20261026.md](ACTIVITY-POCKET-STATUS-20261026.md).
The Owner explicitly parked live coaching completion and current 21/21
qualification work during this mission. Those activities are outside this
delivery's completion gates; their evidence remains visible and unverified.

## Reproducible evidence

Baseline source: `20bdad87a97e649eb751dd6c7add53d3fb9d65fe`.
Baseline: **103 passed, 1 skipped, 63 subtests passed** across existing Academy,
registry, Tools, coaching, skill-registry, workflow and certification suites.

Controlled verifier: `uv run python scripts/verify_activity_pockets.py`.
The completed verifier at the source-delivery checkpoint passed **41 tests, 0 failures,
0 errors, 0 skips**. Its receipt and exported actual outputs/events are in
[`evidence/activity-pockets-20261026/`](evidence/activity-pockets-20261026/).
This is real HTTPS with a transient controlled CA, real handlers and workflow
execution, real authenticated session storage, and real SQLite persistence.
Only external agent-qualification admission is supplied by labelled synthetic
domain fixtures; it is not production qualification.

The raw baseline source-reference scan is
[`evidence/activity-pocket-source-inventory.json`](evidence/activity-pocket-source-inventory.json).
It records exact files and line references across the entire tracked baseline;
presence in that index is never an operational or dependency claim.

## Twenty requested acceptance steps

Names below refer to `tests/test_activity_pockets.py`. VERIFIED means the named
controlled behavior passed, not that production performed it.

| # | Requirement | Classification and reproducible evidence |
| --- | --- | --- |
| 1 | ORQEVIA submits objective | VERIFIED: `test_complete_twenty_step_reference_workflow`, authenticated objective adapter |
| 2 | Factory creates pocket | VERIFIED: same test, actual lifecycle transaction |
| 3 | Retrieve qualified agent | VERIFIED for controlled domain fixtures through the existing projector; production/fleet qualifications remain unverified and parked |
| 4 | Authorized tools only | VERIFIED: canonical eligibility intersection, scoped handler input, `test_malformed_and_unauthorized_manifests`, both open-access settings |
| 5 | Execute extraction | VERIFIED: actual HTTPS, ConnectorRegistry handler and workflow DAG |
| 6 | Validate expected output | VERIFIED: exact two-record fixture oracle and seven independent held-out cases |
| 7 | Detect simulated layout failure | VERIFIED: original extraction fails changed field names and pauses |
| 8 | Academy receives evidence | VERIFIED: persistent training/failure references, actual executing actor |
| 9 | Coach proposes improvement | VERIFIED: existing coaching module produces bounded alias proposal |
| 10 | Laboratory evaluates candidate | VERIFIED: independent fixed expected records, current source and suite binding |
| 11 | Reject unsafe/ineffective candidates | VERIFIED: overfit rejection, source-instruction inertness, personal-data/duplicate/number checks, forbidden policy changes |
| 12 | Owner approves validated candidate | VERIFIED: real session owner decision; worker/self-promotion denied |
| 13 | Library records new version | VERIFIED: immutable owner-scoped artifact, existing registry adapter |
| 14 | Continue with approved version | VERIFIED: autonomous worker completes changed page using version 1.0.1 |
| 15 | Trace decisions/actions | VERIFIED in controlled scope: hashed original records/events and existing action journal; tampered evidence is denied |
| 16 | Restart recovery | VERIFIED: fresh store/process readback, fenced interrupted completion, eight-hour off-time reservation accounting |
| 17 | Independent pockets isolated | VERIFIED: owner-scoped data and emergency control; concurrent execution and cancellation |
| 18 | Stop at budget exhaustion | VERIFIED: attempts, transfer and output budgets; interrupted reservation accounting |
| 19 | Run without orchestration | VERIFIED: standalone API lifespan/worker, independent Factory constructor and subprocess persistence |
| 20 | Complete workflow in CI | VERIFIED at `7e45a56`: all nine checks successful; Linux canonical suite 5,909 passed, 1 existing skip, 92 subtests passed; attached CI receipt |

Additional executed tests cover real Interface creation with a separately
constructed backend Factory sharing configuration/state, source-origin pacing,
robots denial, long-delay restart progression, certificate/private-address and
redirect rejection, immutable skill revalidation after source upgrades, rollback
of completed pockets, retention-linked feedback and daemon DNS shutdown.

## Deliverable classification

| Deliverable | Classification | Scope / limitation |
| --- | --- | --- |
| Architecture reconciliation and reuse matrix | VERIFIED | `ACTIVITY-POCKET-RECONCILIATION.md`, baseline index and two source-review sweeps |
| Ten shared versioned schemas | VERIFIED | Runtime model export matches all ten checked-in JSON schemas |
| Academy/Library/Tools integration | VERIFIED in controlled source execution | Existing definitions, evaluator authority, tool dispatch and task executor reused |
| Durable Factory and reference pocket | VERIFIED in controlled source execution | No unrestricted live acceptance dependency |
| API and workbench visibility | VERIFIED for mounted APIs/static console and shared component execution | Actual browser/physical-device deployment acceptance remains separate |
| Nightly PC restart semantics | VERIFIED for simulated off-time and real subprocess persistence | No physical power cut was performed |
| Source packaging and CI | VERIFIED for source delivery | Nine successful remote checks; candidate branch, no production installation implied |
| Operational documentation | VERIFIED as delivered source instructions | Deployment overlay is an example, not an applied configuration |
| Production rollout/readiness | BLOCKED for a live configured pocket | Requires a reviewed permitted-source configuration and deployment acceptance; no production credential/data/settings changes made here |
| Fleet coaching / 21/21 current qualifications | PARTIAL; PARKED BY OWNER | Actual grades/freshness remain visible; not a delivery gate |

## Review findings and corrections

Two Codex review agents performed read-only source sweeps. They are code-review
participants, not ORQEVIA runtime agents or certification authorities. Findings
led to concrete regression coverage for owner-scoped emergency control,
interrupted byte/time accounting, preserved owner cancellation, event and record
integrity, source/suite freshness at promotion, per-run action identity, actual
coaching actor, durable Academy room state, linked retention, origin-level
source pacing, long robots delay progression, shutdown-safe DNS, admission
revalidation and symmetric Interface/backend configuration.

Historical PRIME/JARVIS/SSOT names and frozen records were preserved as migration
evidence/compatibility metadata. No retired service is started or consulted by
the Factory. REA and MiroFish remain excluded. No unnecessary files were deleted
without evidence that they were safe to remove. No mandatory sandbox, queue
guard, new inference engine, recurring research task or cloud dependency was
introduced.

## Operational limits

This reference implements static, authorized, non-personal catalogue extraction.
It does not claim general browser scraping, arbitrary-schema inference,
automatic interpretation of website terms, general PII detection, automatic
qualification or unattended approval of changed behavior. Owner free-text
success criteria remain descriptive; the executable contract is explicit.

Tamper evidence is local and exportable, without an external immutable anchor.
Physical reboot, installed source correspondence, production security/recovery
and operational acceptance must be independently observed before any
production-ready claim. Parked work is never converted into passing evidence.
