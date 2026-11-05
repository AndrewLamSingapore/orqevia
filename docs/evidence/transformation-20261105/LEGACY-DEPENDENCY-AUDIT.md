# Legacy governance runtime dependency audit - 5 November 2026

Source inspected: `work/build-main-20261031`, HEAD `d79ef92`, upstream main
`9439c84`. Runtime inspection at 00:42 UTC is in `runtime-containers.json`
and `runtime-stores.json`. Production was inspected read-only. This report
distinguishes source presence, import dependencies and observed runtime state.

## What actually executes

The running backend starts `app.production_entry:app`; that application mounts
`direct_entry.app` at `/` (production_entry.py:290), which mounts agent dispatch,
objectives, compute, artifacts, notebooks, Academy, model registry and workflows
(direct_entry.py:1-41). Ordinary objectives call `dispatch_request` directly
(objective_api.py:429-497), selecting responsibility owners and available model
tiers. They do not traverse the legacy AgentAuthorityRuntime delegation tree,
StableSpine evaluation or cognitive routing confidence gate.

The thin frontend starts `app.interface_server:app`; its application mounts
the PWA, public site, shared design assets, session boundary and bridges for
knowledge, intelligence, workflows, sovereign-plane observations and collective
work (interface_server.py:1-64). Those are functional boundaries, not independent
intelligence authorities.

## Dependency and disposition register

| Component and source | Actual function/usage | Disposition and reason |
|---|---|---|
| app/__init__.py:4; protected_env.py:14 | Package import replaces process-wide os.getenv to resolve historical PRIME_* names. Twelve app files contain legacy literals. | RETIRE atomically with all active readers; global stdlib mutation is unnecessary compatibility coupling. |
| agent_dispatch_api.py:491,604 | Requires Registry-v1 enabled env even after owner authentication. | RETIRE enablement ceremony; source already provides native direct dispatch. Keep authentication and bounded probe slot. |
| agent_registry.py:44-128 | Validates capability ownership, fixed population, six lead hierarchy and historical successor mapping; imported widely by execution, knowledge, Academy and tools. | SIMPLIFY in stages. Capability identity and ownership remain useful; mandatory reporting tree and exact permanent population are obsolete architectural assumptions. Current Phase 1 keeps data shape intact to avoid dropping capabilities. |
| agent_registry.py:181-225; agent_runtime.py | Enforces root->lead->child delegation and lead-only consultation in old authority runtime. | RETIRE from ordinary execution (already bypassed); migrate read consumers before removing historical capability APIs. |
| app/routing_policy.py:38; cognitive_orchestrator.py:25 | Mandatory deterministic->local->confidence->frontier sequencing in old cognitive path. | REPLACE only where invoked with task-qualified direct model selection. It is not a mandatory layer in production direct_entry. |
| app/release_gate.py:57,129 | Sanitized aggregate answer-evaluation ledger, not deployment authorization. | RETAIN useful telemetry or merge later after measuring reads/writes. Do not delete based on filename. |
| app/host_guard.py:95; action_harness.py:560 | Exact-effect classification and authorization before privileged host execution. | RETAIN technical boundary; scoped automation can reduce repeated approval, but model-generated prompts must not authorize destructive actions. |
| app/spine.py:106; sovereign_plane.py:336-450 | Stores trust/audit and consequential approvals. Sovereign API still reads/decides existing approvals; no ordinary direct-dispatch dependency. | SIMPLIFY; remove filename migration and legacy default source. Preserve existing consequential records and their exact-envelope checks until replacement exists. |
| app/action_records.py:277-324 | Non-authorizing asynchronous action journal; append lock protects data integrity, never mission admission. | RETAIN minimal diagnostic/duplicate evidence. Do not confuse append serialization with a universal approval queue. |
| compute queue, background admission, HOME_ECO | Durable job recovery, fairness, cancellation, measured shared hardware capacity. | RETAIN and measure. User instruction removes obsolete bureaucracy, not bounded physical capacity or accepted mission recovery. |
| config/prime_skill_registry.json; skill_router.py:17 | Bounded advisory prompt guidance; not a tool authority registry. | ADAPT to current filename, preserve original bytes as dated evidence. Do not create another hierarchy. |
| governance/operational-manifest.json | Self-labels status STALE, records dated multi-product observations. Not copied into production image. | HISTORICAL EVIDENCE. Active CI falsely couples product release to stale manifest semantics; separate in a deliberate CI/documentation migration. |
| governance/CHANNEL_CONTRACT.md | Dated cross-product reading contract; says routine work executes directly, no universal TAP approval. No execution import. | HISTORICAL guidance; do not treat as runtime authority or delete evidence. |
| system.manifest.json + check_canonical_state.py + validate_canonical.py | CI pins registry/interface/task/artifact hashes, generated historical checkpoint and exact 21 count. | SIMPLIFY active assertions once capability-shape migration is implemented. Keep integrity and reproducibility, retire historical status-organization semantics. |
| app/main.py, spine_api.py, cognitive_api.py, harness_api.py | Older full-stack app exposing authority and phase approvals; not mounted by current backend. | RETIRE from supported launch/deployment after full import/route inventory and replacement mapping. Source presence alone is not a live blocker. |
| app/path_migration.py + memory.py:42, agent_notebooks.py:177, production_survival.py:78,141 | Automatic copies of jarvis-memory.db when current DB absent. | RETIRE only after checking current data and explicit recovery path; leave archived databases intact. |

## Signing and hash constraints

The 19 October naming note says seven source files must be byte-identical to a
signed closure. It is historical: the ordinary application has changed since,
the saved certificate expires on 20 October, and production direct dispatch is
not gated by that certificate. `tests/test_fresh_initialization_20261019_signed_closure.py`
verifies exact archived JSON/signatures, not current-file equality.

The actual signing path `scripts/sign_admitted_agent_cases.py:22-51,133-158`
compares the entire oracle/trust/runtime closure against each original reviewer
revision before re-signing cases. Changing source means old admissions cannot be
re-signed against new runtime bytes. Preserve those checks and old evidence;
use fresh source-bound runtime receipts without claiming historical signatures
qualify a new build. No new signing or credential access was performed.

The canonical CI independently pins config/agent_registry.json bytes through
system.manifest.json, and expects the stale operational manifest plus its exact
generated JARVIS checkpoint. Phase 1 does not modify those data bytes. Do not
weaken signature or hash verification just to make a cosmetic migration pass.

## Runtime observations

Backend and interface run main `16f1587` and are healthy. Access mode is closed
(`ORQEVIA_OPEN_ACCESS=0`), scheduling reports `home_eco`, and data root is `/data`.
Both current and historical spine databases exist. Current spine has two
APPROVED records; historical spine has no approval rows. Authority and release
telemetry databases exist, which does not prove current dispatch consults them.
Counts and schemas, never prompts, credentials or complete records, were read.

## Current frontend route/capability map

`/pwa/` is one large static HTML shell with home, intelligence, agents, objective,
evidence, approvals, God's Eye, ideas, architecture/build/test, coaching,
settings, data & tools, deploy/present, operations and plane views. Legacy
appearance selection is loaded by `/pwa/design/theme.mjs`; style sources include
style/dashboard/intelligence/knowledge/command-center/sovereign CSS. Additional
native routes include `/pwa/projects.html`, `/pwa/reset.html`, public `/`, public
assets and backend-local `/control` with production_control HTML/JS. Frontend
replacement must cover these surfaces, service-worker caches and static routes;
replacing only the dashboard does not retire the old interface. Essential PWA
session/owner separation must remain enforced server-side.

## Competing minimal architectures and evaluation

1. **Direct single-worker fabric.** Keep one logical coordinator, a capability
   inventory, one recoverable compute queue, current knowledge storage and
   deterministic tools. Task-tier routing calls one qualified model. Smallest
   change and lowest idle overhead; limited simultaneous inference. Baseline
   completion/accuracy/CPU-seconds/RAM and external cost are already measurable.
2. **Ephemeral task DAG.** Construct only needed capabilities per objective;
   independent nodes run under the same measured capacity envelope and merge
   outputs through explicit task dependencies. No permanent lead hierarchy.
   Better parallel independent work, but adds cancellation/recovery join logic.
   Compare withheld multi-step tasks to design 1 at equal model budget.
3. **Independent candidate competition.** For difficult tasks only, execute two
   bounded hypotheses or deterministic/model alternatives, score using a fixed
   held-out oracle, retain results with provenance. Improves error detection
   when alternatives differ; doubles some work. Compare useful successful
   outcomes per CPU-second/cost, and reject if accuracy gain is insufficient.

Recommended current default is design 1, with design 2 and 3 as experiments
under existing compute capacity. General intelligence improvement remains
unproven. A meaningful first experiment is direct deterministic arithmetic
versus model-only probability outputs with unchanged independent graders and
unseen seeds. No new permanent orchestrator or governance service is justified.

## Validation limits

This was a source/dependency and read-only runtime audit. It does not establish
that every old route is unreachable from every historical launcher, certify
21-agent competence, or prove full recovery independence. No frontend migration,
signing, source deployment or production mutation was performed by this audit.
Phase 1 code changes and targeted verification are reported separately.

## Implemented source changes - final qualification in this session

The inventory above records the pre-edit baseline. The shared source tree now
contains the following actual changes; this section does not claim deployment.

- Removed every PRIME_* environment lookup in active application code and the
  package-wide os.getenv monkeypatch. The obsolete bridge source was archived.
- Removed both Registry-v1 enablement gates from authenticated native dispatch
  and the bounded baseline probe, and removed the flag from both Compose roles.
  All 21 current capabilities were tested through direct dispatch without that
  flag. Authentication, model privacy/cost checks and probe concurrency remain.
- Removed automatic prime-spine.db and jarvis-memory.db inheritance from Spine,
  memory, notebooks and survival status. Tests verify historical bytes remain
  untouched and absent current stores are not silently copied by observation.
- Moved the advisory guidance file to config/capability_guidance.json. Its
  original bytes, old bridge and retired control HTML/JS are preserved under
  this audit's source-evidence folders and in Git history.
- Removed the mandatory six-manager/reporting-graph startup validation. A real
  registry-loading regression removes leads/reports_to metadata and proves all
  21 capability identities and responsibility owners remain available, with
  declared delegation targets unchanged and consequential authorization intact.
- Replaced the canonical release's historical subordinate-portfolio conditions
  with current component hash, source path, identity and capability-ownership
  integrity checks. Current source validation passes from a source fixture
  containing no governance directory, operational manifest, STATUS or generated
  JARVIS checkpoint. Schema, signature and secret-pattern protection was retained;
  no old signed evidence or Golden manifest was edited. system.manifest.json now
  explicitly describes source integrity only, not deployed or certified status.
- Retired backend /control HTML in favor of an authenticated 307 to the unified
  Console; /control/app.js returns 410. Existing /control/api endpoints retain
  their implementation and authorization. The old intelligence HTML proxy now
  redirects authenticated requests to the canonical Intelligence view; legacy
  scripts/styles return 410. Intelligence API forwarding is unchanged.
- Preserved explicit Evidence Lens capture/read capability in the unified UI
  through /interface/v1/lens routes. They reuse current libraries and the same
  durable stores, validate owner role/current task account ownership and CSRF,
  accept no caller-selected execution parameters and expose no server token.
- Migrated the one-shot Lens canary to verified HTTPS and the authenticated
  canonical interface. Existing owner cookie or scoped client credentials come
  only from environment, redirects are refused and no credentials enter receipts.
- Public product copy now describes missions, models, knowledge, permissions and
  recovery. /trust remains the same URL and is titled Security. README and PLAN
  now distinguish the active execution model from preserved historical material.
- Corrected HOME_ECO telemetry mode recognition so an actually supported runtime
  mode does not manufacture unavailable readiness; completion freshness and model
  observation requirements remain enforced.

Final combined targeted qualification: **210 passed, 0 failed** in 24.30 seconds.
This includes session/account/CSRF/expiry/forged-identity/oversize checks, explicit
idempotent evidence capture and HTTPS canary through real application components,
native configuration and memory isolation, control/API compatibility, registry
flattening, source integrity and secret detection. Strict lint and format checks
pass for newly added Python files. The parent performs the one full suite, CI and
deployment after all independently owned changes are consolidated.

Initial targeted failures were corrected, not hidden: historical Golden rollback
fixtures must still use their original env key because they deliberately execute
archived code; new centralized CSS replaced the old dashboard stylesheet test;
both telemetry mode allowlists needed HOME_ECO; session middleware emits no-store
rather than preserving the bridge's additional private directive. Current final
tests retain the actual security properties.

## Remaining boundaries and explicit limitations

Current capability JSON and its hash are unchanged. It still contains historical
root/lead/reporting labels and responsibility aliases for retained consumers and
dated records. Those labels are not required by ordinary direct dispatch. Legacy
AgentAuthorityRuntime, cognitive routing and harness modules still exist for
explicit historical/optional callers; this work does not claim every old module
has been removed. A future schema change must preserve or deliberately migrate
the existing responsibility aliases before retiring those identifiers.

The generic explicit path_migration utility remains available for deliberate
recovery, with no automatic application caller. The existing consequential
approval store remains an authenticated technical boundary, not a prerequisite
for ordinary inference. Archived operational/status validators remain explicit
historical-evidence tests; current source validation does not consult them.

The private intelligence service may still package its old static reference
files; the public interface proxy no longer serves them. The deployment owner
must verify there is no separate published host port serving that old UI.
Likewise, a person explicitly starting the unsupported old app.main entrypoint
would select old routes; the supported deployment must continue using the pinned
production_entry/interface_server entrypoints.

No runtime latency/quality improvement is claimed from removing these checks.
The measured result here is successful source-level functional and security
qualification. Production performance, final screenshots and deployment/recovery
acceptance belong to the parent's consolidated batch receipts.
