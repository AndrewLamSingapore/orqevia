# ORQEVIA complete live deployment plan

**Status:** PLANNED, NOT EXECUTED  
**Prepared:** 27 October 2026  
**Purpose:** Reach evidence-backed, complete live deployment of the configured ORQEVIA application and intelligence paths without destabilizing the currently running services.

## Deployment rules

- Use certificate-verified HTTPS for all user-facing acceptance and new integrations. Keep port 8081 retired. Do not rewrite private transport endpoints until a coordinated TLS migration is ready.
- Deploy directly through the established deployment pathway. Do not install a queue guard, queue lock, artificial delay, or deployment hold.
- Preserve authentication, least privilege, existing sessions/certificates, databases, job history, persistent volumes, model weights, Golden Gen22, and independent research. No broad deletion or prune.
- Keep currently healthy services available. Stage and deploy one bounded change at a time, with resource caps and an immediate rollback path. Do not start concurrent heavy model work or benchmarks.
- Report UNKNOWN when evidence is absent. Never force READY, fabricate a health value, infer agent wiring from a catalog, or claim accuracy from fixtures.
- REA and MiroFish remain excluded. Dell-origin testing remains parked unless the Owner reopens it.

## Phase 0 — Freeze the baseline and route inventory

1. Read the latest handover, mission status, runtime manifests, deployment helper instructions, and protected custody record. Verify the live commit/image/container identities and checkpoint hashes without printing secrets.
2. Build one authoritative route-to-component matrix for every deployed inference and orchestration path. For each route record: HTTPS entrypoint, backend route, auth/tenant boundary, feature flag, source revision, model/fabric, storage/evidence path, timeout, and rollback control.
3. Inventory all 36 fabric IDs and map supported capabilities to configured agents. Distinguish catalog entries, implemented adapters, registered routes, enabled runtime paths, and tested agent bindings. Do not assume every agent should use every fabric; define expected bindings explicitly and get evidence for each intended binding.
4. Capture initial health, active jobs, agent/cohort records, service IDs, storage integrity, and image identities. Do not delete or restart services during baseline capture.

**Exit evidence:** reviewed route matrix; clean source tree; protected baseline; explicit list of unknowns and intended bindings.

## Phase 1 — Close source and integration gaps

1. **Agent Factory:** Decide and implement the intended production interface through existing authenticated registry/scaffolding boundaries. Keep generated candidates advisory-only with no execution authority. Verify candidate generation, schema validation, secret rejection, durable artifact readback, and explicit registry proposal/approval behavior. Do not auto-register or activate a draft.
2. **Academy:** Trace the live endpoint and cohort controller from request through coaching store, executor, assessment, and retained-method readback. Diagnose the observed STALE state (20 READY, 1 WAITING, all baseline). Resume/repair only valid scheduled work; assess using unseen cases and real evidence. Record each of the 21 agents as PASS/FAIL/WAITING/UNAVAILABLE with reasons. Award no certification unless its independent criteria pass.
3. **PIF:** Resolve why the probed HTTPS status path returned 404 by tracing the live interface route, backend route, deployed image, feature flag, auth, and router registration. Preserve default-off/shadow-only behavior until authenticated status, bounded fit, forecast, evidence readback, owner isolation, disabled mode, and restart recovery pass.
4. **MLP:** Resolve both probed 404 paths against actual deployed routing and image identity. Validate the pinned reference artifact digest, owner-bound inference request, numerical bounds, trace idempotency, evidence persistence/readback, auth/isolation, disabled/unavailable behavior, and restart recovery. Clearly label the model as a synthetic reference, not a production accuracy claim.
5. **Fabrics:** Implement/repair only intended runtime adapters and bindings. For each intended fabric-agent pair, run a source-bound functional request, verify the expected output contract and durable receipt, test denial for unauthorized capability, and record revision/image/time/hash. Roll up count as verified / expected; do not declare 36/36 unless every intended entry passes.
6. **All inference paths:** Include non-PIF/MLP inference, model/provider adapters, collective execution, tool/fabric routes, and relevant artifact/evidence paths from the Phase 0 inventory. For every route test success, auth denial, bad input, timeout/unavailable dependency, stale evidence, retry/recovery, and persisted receipt. Preserve feature flags and production authority boundaries.

**Exit evidence:** source tests and integration tests pass for each changed component; route matrix updated; independent review verifies auth, provenance, and rollback; no production change yet.

## Phase 2 — Build and isolated staging

1. Merge only reviewed changes through the existing repository checks; record exact commit and source export hash.
2. Build immutable candidate images under the established CPU/memory limits. Bind each image to source, configuration digest, dependencies, and intended runtime role. Preserve current and Golden rollback images.
3. Run a single staged candidate at a time on isolated test state. Exercise positive, negative, timeout, storage-failure, offline, duplicate/replay, restart, and recovery cases without production data or user sessions.
4. Compare stage results with explicit acceptance criteria. Any unexpected write, authority expansion, secret exposure, failed integrity check, or broken existing service rejects that candidate. Fix and rebuild; do not waive the failed criterion.

**Exit evidence:** exact-image staging report; test logs; data-integrity and rollback proof; no impact on production containers or data.

## Phase 3 — Controlled live deployment

1. Recheck protected production backups and current service/container identities immediately before deployment.
2. Deploy the smallest independent component change through the established direct deployment procedure. Preserve unrelated container IDs, mounts, env/config, volumes, jobs, sessions, certificates, model state, and network policy.
3. Begin with read-only/status routes and dashboard bindings. Then enable one approved shadow inference path at a time. Keep execution authority unchanged. Do not simultaneously deploy Agent Factory, Academy, PIF, MLP, and all fabrics as one opaque bundle.
4. Run certificate-verified local HTTPS canaries for each route and representative desktop/mobile flows. Verify source/image binding, auth and tenant isolation, latency/timeouts, real output schema, provenance, persisted evidence readback, and absence of plaintext requests.
5. Roll out remaining intended routes sequentially, watching resource load and service health between changes. Stop on a regression and use the recorded component rollback; preserve new valid database writes.
6. Verify the OTel collector, both tunnels, integration gateway, core services, critical-issue coverage, host telemetry, and all 21 agent classifications from actual measurements. Keep missing checks UNKNOWN/DEGRADED with explicit reasons until corrected.

**Exit evidence:** per-component live deployment receipt, route-level request/response evidence, stored receipt lookup, image/config hashes, health before and after, and rollback test reference.

## Phase 4 — Offline durability and full end-to-end acceptance

1. Before the planned PC shutdown, confirm the complete checkpoint is current, hashes validate, database backups pass integrity checks, startup/watchdog configuration is present, and all deployment evidence is saved.
2. At the Owner's next real power-off/restart, verify boot identity changes; Docker and persistent services return automatically; HTTPS dashboard and local authenticated routes recover; collectors emit fresh current-boot readings; no stale reading is presented as healthy; jobs, leases, sessions, incidents, Academy records, and inference evidence persist without duplication or loss.
3. Run one real success and bounded failure/recovery through each intended inference family and configured fabric/agent binding. Verify timeout, auth denial, dependency outage, offline mode, stale data, reconnect, durable evidence, and replay behavior.
4. Confirm critical-issue totals are authoritative only when complete fresh coverage supports them. Confirm every agent has an evidence-backed classification; report intended-agent blockers instead of forcing readiness.
5. Reconcile any cleanup only after reference inventory and a fresh backup. Preserve active/recent jobs and evidence required by coaching, tasks, artifacts, certifications, and last-success/failure history.

**Exit evidence:** real post-boot receipt, HTTPS browser/API logs, current-boot sample timestamps, persistence comparison, route/fabric/agent receipts, failure/recovery evidence, database integrity, and no unexplained regressions.

## Phase 5 — Closure

Update the six mission documents and this plan with exact commits, image digests, deployment timestamps, routes tested, results, residual limitations, and artifact paths. Acceptance requires:

- all configured production routes inventoried and authenticated;
- Agent Factory, Academy, every intended fabric-agent binding, PIF, MLP, and other inference routes verified at the correct deployment scope;
- real telemetry and individually checked core services, agents, and critical issues;
- no unreported UNKNOWN/STALE data or fabricated healthy state;
- offline/full-PC restart durability proven;
- security, data integrity, rollback, and regression criteria passed;
- no unresolved required acceptance criterion.

If any acceptance item is still open, record **PARTIALLY COMPLETE — BLOCKED** (with the specific evidence dependency) or **FAILED VERIFICATION** (if a required test failed). Declare **COMPLETE — VERIFIED** only when all acceptance evidence exists. This plan itself is not deployment evidence and does not authorize a claim of completion.

## Work order after the present checkpoint

1. Finalize the route/component and 36-fabric expected-binding inventory.
2. Fix runtime route/image discrepancy for PIF and MLP, and add production-safe Agent Factory integration plus Academy stale-cohort recovery.
3. Verify each inference route and intended fabric-agent pair in isolated staging.
4. Build and deploy sequentially with per-component live receipts and rollback proof.
5. Close monitoring/healthcheck, cleanup, and identity publication items without deleting evidence.
6. Perform the actual Owner-controlled PC shutdown/restart, capture fresh-boot evidence, then complete the acceptance matrix and closure documents.

## Exhaustive mandatory verification register

**Owner requirement:** every in-scope item currently UNVERIFIED, UNKNOWN, STALE, or only source-/historically verified must receive a current live verification result before closure. “Not tested,” “route unknown,” “404,” “process running,” “catalog entry,” fixture pass, or source test is not a passing live result. If an item cannot be verified, the mission stays open and records the exact cause and evidence. Do not close a gap by weakening the criterion or changing the label.

| Scope item | Current recorded status | Required proof to close |
|---|---|---|
| Complete live inference inventory | UNVERIFIED | Inventory every deployed model/provider/inference/fabric/agent entry path, feature flag, auth boundary, dependency, evidence store and rollback. Exercise each intended live path and all failure/recovery classes. |
| Agent Factory | Production use UNVERIFIED | Authenticated candidate generation, validation, secret rejection, persistence/readback, registry proposal; prove drafts remain advisory and cannot activate without existing authority. |
| Academy | Live endpoint; cohort STALE/incomplete | Resolve stale controller/session cause; assess all 21 registered roles with valid unseen cases, persist real results, verify retained-method readback and restart persistence; record pass/fail/waiting reasons. Certification remains separate. |
| Activity Pockets | UNVERIFIED | Identify exact feature/routes and intended user flow; verify create/update/readback, authorization, durable storage, dashboard integration, stale/error behavior, and restart/offline recovery using non-destructive test data. |
| Fabric catalog and agent wiring (36) | 0/36 current verified; wiring UNVERIFIED | Enumerate 36 entries, define intended agent-capability pairs (not assumed all-to-all), execute each pair, verify output and durable source-bound receipt, denial and recovery; account for every entry as PASS/NOT APPLICABLE with reason. No unknown left. |
| PIF | Source tests; live status path probe 404 | Trace route/image/flag/proxy/auth; restore or correctly document intended route, then authenticated status, fit, forecast, evidence readback, tenant isolation, disabled and failure modes, restart persistence. |
| MLP | Historical live check; current probed paths 404 | Trace exact live route and image; verify pinned artifact digest, authenticated bounded inference, numeric contract, durable evidence, isolation, disabled/failure and restart behavior. Keep synthetic reference clearly scoped. |
| Other inference/fabric adapters | Incomplete inventory | For every item in route matrix, verify real request-to-model/fabric, provenance, evidence readback, authority constraints, timeouts, outage/retry and recovery; never infer group health from a sample. |
| Agent readiness (21) | Latest dashboard observation 0 confirmed / 21 unconfirmed | Collect current role-by-role evidence and classify all 21 accurately; repair only legitimate faults, do not force READY. Verify freshness and reasons in the live dashboard. |
| Academy coaching requests: helper and OTel | Request recorded; outcome unverified | Map “helper” only to a real registered identity or document no such identity; coach from observed gaps with unseen assessment. For OTel, evaluate receiver/exporter failures, bounded load and restart recovery, then record measured improvement. |
| OTel collector, Cloudflare tunnels (2), integration gateway | Four containers lack meaningful checks | Add intended, bounded, certificate-verified functional checks where supported; prove correct endpoint/auth and healthy/degraded/offline transitions, freshness and recovery. Preserve current private transports until coordinated TLS migration. |
| Core service and critical-issue monitoring | DEGRADED / authoritative count UNKNOWN | Verify each configured service at process, endpoint, dependency and readiness levels; trigger/recover representative incident; confirm dedup, persistence and authoritative totals. Never turn missing coverage into zero. |
| Historical job and storage cleanup | Reference-aware cleanup pending; no rows deleted | Fresh protected backups; cross-store reference inventory; preserve active/recent/coaching/artifact/certification/last-outcome evidence; delete/archive only proved-disposable items; measure reclaimed bytes and recheck DB integrity, API behavior, and recovery. |
| Component identity / Golden lineage | Gen22 preserved; Gen23 unsigned/unpublished | Review narrow compatibility change, bind source/image/config hashes, run independent verifier and canary, sign/publish through established path without key disclosure; preserve rollback and prove deployment identity. |
| Shutdown/offline recovery | No actual whole-PC cycle after these changes | Owner's real full power-off/restart; verify automatic service recovery, new boot-bound fresh telemetry, local HTTPS, image/volume identity, jobs/sessions/incidents/learning/evidence persistence, and no duplicate/lost work. |
| Overall deployment regression/rollback | Partial component acceptance only | Per-component live canary and rollback evidence plus final cross-component desktop/mobile E2E; preserve existing production functions and security boundaries. |

**Scope exceptions:** Dell-origin authenticated test remains parked by Owner; REA and MiroFish remain excluded. These are not to be silently activated. All other configured ORQEVIA components discovered during the route inventory are in scope and must be verified or explicitly resolved as not configured with evidence.

### Completion gate

No required row may remain UNVERIFIED, UNKNOWN, STALE, source-only, fixture-only, historically-only, or missing evidence. Every configured component must have a current live result (PASS, a correctly evidenced non-healthy state with remediation closed, or evidenced NOT CONFIGURED where appropriate). Any unresolved access or infrastructure limitation prevents **COMPLETE — VERIFIED**. Closing all gaps requires a fresh full acceptance matrix after the final live deployment and the real offline/restart cycle.
