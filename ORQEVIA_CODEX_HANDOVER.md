# CODEX HANDOVER - ABEX / ORQEVIA - 27 October 2026

**CURRENT SAFE CHECKPOINT. OPEN TO EVERY AUTHORIZED CODEX SESSION.**

Owner ordered SAVE EVERYTHING FIRST NOW because Codex allowance was below8%. Owner explicitly requested generic CODEX labeling, not a specific model. Preserve this checkpoint before further work. Saved handover is not completed system certification. No PC shutdown was performed.

## What is LIVE and actually verified

- Entry point: **https://localhost:8443/pwa/**. HTTPS certificate and hostname checks remain enabled. Port8081 stays retired.
- Live interface source **42b8baffdf6bfd1cbfed5738a4af5429399fc905**, merged PR463. Image `orqevia:observability-42b8baff`, ID `sha256:d4db93494de32a0f0aa98621236e6b41497e5fbd495e98a9540535c367ee422c`. PWA shellv43.
- Backend and coaching remain **b360da98641a1332856c8fdeb2063d36312b7669**. Backend image `sha256:d8cf1f7ed9001c013fe1473414aabd5e8d741b507d98310493f7f58ea5c1f15c`; coaching `sha256:73171676cd0904a9bf53502c1c68f578d2a2d996d5d01897802a28901f8121ab`. Their IDs and inference/intelligence/OTel IDs were preserved during interface deployment.
- Real Windows source **DESKTOP-27LKJ2V**, existing protected SYSTEM sampler `C:/ProgramData/ABEX/PrimeHostMetrics/collect-host-metrics.ps1`. Existing task now invokes fixed sibling operational hook; no new task/daemon. Real receipt directory is mounted READONLY into interface at `/run/orqevia-host-metrics`. Source/host/boot checks PASS and OTel current-namespace export PASS observed.
- Native sampler, wrapper, Python producer, public CA and digest inventory are installed under that root. Configured Owner/Docker/SYSTEM/Admin writer access is preserved. Prior source and SDDL are in protected checkpoint directories. Installer uses DACL-only Windows API after repeat Set-Acl unnecessarily requested SeSecurityPrivilege. No credential, owner/group or SACL broadening.
- Production HTTPS API and actual desktop1440/mobile390 browser checks PASS, zero page errors/plaintext requests, test session revoked. Served JS matches exact Git archive build export; CRLF export normalizes to canonical LF Git blob. Earlier byte mismatch was line endings only, not source drift.
- Actual displayed sample at05:54UTC: CPU62%, memory82.3%, disk29.2%, gateway RTT6ms. These are DATED readings, not current fixed values. Host summary may legitimately be PARTIAL when a virtual/disconnected NIC lacks some counters/rates; CPU/memory/disk and interface values retain individual provenance. Network RTT does not prove Internet readiness.
- Service/critical/agent data is backend driven. Incomplete monitoring NEVER yields authoritative0critical. Current known limits keep core DEGRADED / critical UNKNOWN; details explain why.

## What is SAVED but NOT LIVE

**Readiness query fix:** candidate changes only `app/interface_telemetry.py` and `tests/test_interface_telemetry_counts.py`, plus checkpoint docs/status. Worktree `C:/Users/Admin/Documents/ABEX/work/orqevia-observability-20261027`; branch **codex/observability-readiness-closure-20261027**, starting from live main42b8baff. Exact saved commit/push/PR/bundle hashes are in checkpoint CUSTODY.json; do not assume merge or deployment.

Actual live ready-agent-count is still UNKNOWN because the old observer scans the full job journal and exhausts0.2s. The model observer already has genuine status/timestamp; no model timestamp repair was needed. Candidate SQL projects timestamps once, uses grouped maxima and validates only bounded candidate metadata instead of thousands of Python rows. Actual read-only in-memory verification on6,881rows returned all21 roles in0.0591s and0.1298s, under the unchanged0.2s deadline.24 focused tests, strict lint and diff check passed. Source test evidence: `agents/agent-readiness-reader-closure.json` under ABEX operations.

Candidate actual classification at06:09UTC: **0CONFIRMED /21UNCONFIRMED**, comprising12 stale activity,8 latest tasks failed and1 execution in progress. This is a measured classification, not21dead workers or a reason to force READY. Roles are on-demand; no dedicated role heartbeat exists. Preserve original IDs/times/errors and recent-success scope, not competence claims.

**Identity package:** `operations/observability-recovery-20261027/identity-candidate/README.md`. Gen23 preview, parameterized generator, scoped acceptance receipt, proposed publisher/canary compatibility diffs and independent validator.7 tests, strict lint and PowerShell AST checks PASS. **UNSIGNED, UNAPPROVED, NOT INSTALLED, NOT PUBLISHED.** Gen22 remains unchanged. Never run publisher -NoPublish as a dry run: it STILL signs/writes and only suppresses docker copy. Never read the private signing key.

## Nightly shutdown / extended offline requirement

Owner turns this PC off nightly. Durable jobs, learning, incidents, trusted sessions/certificates/profiles must survive; restart must resume without duplicate work or pre-shutdown healthy data.

-13 actual isolated HTTPS acceptance checks PASS. Actual stage stop180seconds preserved21 learning records, trusted cookie/session and incident history; original samples stayed stale after restart until fresh native receipts arrived. Actual browser offline, request timeout, SQLite open failure, incident replay dedup and recovery were tested. No production failure was induced or model jobs submitted.
- Additional meaningful source regression clears stale facts immediately on visibility/pageshow restoration, before waiting on network.48 focused frontend checks PASS. All10 PWA CI command groups passed; last production head a32e90e had quality/tooling/browser/status checks PASS before PR463 merge42.
- Windows Docker Desktop AutoStart=true observed; existing logon startup and watchdog StartWhenAvailable=true. Native startup reentry exited0 at13:55SGT; primary verification is now **HTTPS localhost**, so unavailable LAN/Internet does not gate local readiness. Existing container restart policies are always; all persistent volumes and source/image pins retained. Native watchdog now distinguishes invisible protected task registration from a fresh same-boot collector, not false TASK_MISSING.
- **Actual whole-PC power-off/overnight/reboot has NOT been performed for these changes.** Verify fresh boot ID, sampler source checks, current interface image, original jobs/leases/sessions and new samples after Owner's next real restart. Never use the dated boot ID as a fixed expected boot variable.
- Normal offline operation cannot perform live external requests; retain explicit OFFLINE/UNKNOWN and bounded retries until connectivity returns. No plaintext fallback.

## Historical jobs and deletion request - NO DELETION DONE

At06:09UTC: **6,881 total** =6,053completed +724failed +103cancelled +1running. Oldest19September2026, newest27October. Journal file32,133,120bytes (about30.6MiB), not6,900simultaneous jobs.1,444IDs were found in coaching events/current sessions;20cohorts and3,000coaching events were observed. Other history may back ordinary tasks, artifacts, certification or retained learning; do not assume the other IDs are disposable.

Owner authorized deleting unnecessary history, then explicitly ordered SAVE FIRST. **No historical jobs, active jobs, database rows or model weights have been deleted in this resumed phase.** Before purge, use fresh protected backup, enumerate all persistent cross-store references, preserve the running job and original evidence needed by tasks/coaching/retained methods/last success/failure. Archive removable terminal records if needed, then delete/compact only a proven safe subset with counts, integrity and end-to-end checks. Deleting all rows would break the required evidence and is not a valid timeout fix; deploy the tested query optimization.

Disposable build contexts/stage containers/images are candidates for measured cleanup after checkpoint. Previous maintenance already recovered~28.82GB host space plus3.35GB retired model internally; do not attribute that earlier recovery to this phase. Retired4B model remains removed; preserve needed1B/12B/embedding weights. No broad Docker volume/cache prune.

## Exact next steps

1. Read ROOT and worktree AGENTS.md; load latest CUSTODY.json. Fetch canonical main, preserve saved candidate, inspect two-file optimized reader diff and24-test/current native evidence. Do not rediscover or fake source timestamps.
2. Complete CI/PR/merge for readiness fix, build exact accepted Git export and minimally update interface only. Existing helpers: `build_image.py`, `deploy_interface.py`, `live_browser.cjs`. **Make deploy helper idempotent before reuse:** runtime Compose already has component fallback variables and receipt env entries; its old-to-new replacements currently assume first deployment. Preserve all unrelated env/mounts/data/peer IDs. Parameterize browser revision/export directory for the new accepted interface. Keep backend/coaching b360 unless separate justified change.
3. Verify live all21 classifications with original times and real numeric count; accept actual0 if evidence supports it. Repair legitimate failures where feasible; never convert idle/stale roles into fakeREADY or role competence.
4. Regenerate gen23 candidate for final actual interface build/deploy/browser evidence, independently verify hashes and all three component bindings. Review/install only narrow compatibility diffs, then use existing signing pathway without key disclosure. Preserve gen22. Current expected-runtime/publisher still gen22 and therefore correctly disagree with b360backend/newinterface; never copy observed IDs into expectations just to pass.
5. Gateway only exposes private HTTP static GATEWAY_ONLY liveness; no coordinated functional HTTPS path. Public `https://orqevia.lamjarvis.com/api/orqevia/intelligence/health` returned certificate-verified403. Current tunnel connection proof and idle-worker heartbeat are not exposed. Scope these limits correctly; do not bypass auth/TLS or call running processes healthy. Authoritative critical count remains null until coverage supports it.
6. After preservation, perform safe reference-aware job retention/owned artifact cleanup and record actual reclaimed bytes. Keep historical failure/source evidence.
7. Update six mission docs with final commits/runtime results. Only COMPLETE — VERIFIED when every required criterion is actually met; otherwise preserve honest PARTIALLY COMPLETE — BLOCKED or FAILED VERIFICATION. Whole-PC overnight result waits for real restart.

## Saved evidence and recovery paths

-Current checkpoint: `C:/Users/Admin/Documents/ABEX/operations/observability-recovery-20261027/checkpoint-20261027T0614Z/`; current private SQLite snapshot path/count/hash/quick_check and custody in that directory. Backups are per-database consistent, not one atomic distributed snapshot. No restore into production performed.
-Prior immutable checkpoint `.../handover/` contains b22source bundle and465database snapshot report; retain it as dated history. New checkpoint includes the current operational-health store and current job/coaching state.
-Actual live receipts: `interface-deployment.json`, `live-browser.json`, production desktop/mobile screenshots, `stage-acceptance.json`, `runtime-watchdog-repair.json`, `collector-install-fixed.json`, `integration-tests.xml`, `pwa-ci-local.json`. Initial test-harness failures remain dated; final stage13PASS/livePASS are separate evidence.
-Runtime root `runtime/orqevia-epoch-20261016`, main Compose plus `docker-compose.otel-collector-20261022.yml`, project orqevia-epoch-20261016/profileclients. Private env/compose/pre-interface captures: `C:/Users/Admin/AppData/Local/ORQEVIA/releases/orqevia36-live-20261024/observability-interface-20261027T054919Z`. Never print full env, Docker config, cookies or secrets. Retained rollback images b360 and gen22db22290; rollback app config/images, not old DBs over new work.
-Native startup `operations/Start-Orqevia-Pathway.ps1`; watchdog `operations/permanent-readiness-20261017/Orqevia-Runtime-Watchdog.ps1`; originals preserved in this operations directory. Collector original scripts/SDDL privately backed up. Preserve native certificates/profiles/sessions in place.
-Old remote-worker WIP at `work/orqevia-digitalocean-20261027` remains unmerged/undeployed,78pass/1fail historical; three files preserved, no changes here. Earlier sealed763-file preservation remains intact.

## Standing scope

Full operational access means all configured ORQEVIA agents/services, not every Windows/network user. No new approval gate, queue guard, queue lock, artificial execution hold or mandatory sandbox. Preserve auth, credentials, evidence and independent research. HTTPS only,8081retired; existing private transports need coordinated TLS migration before config changes. REA/MiroFish excluded. Dell-origin test parked, not blocker. Cloud migration/new provisioning/paid calls remain held. Use gemma3:12b for reasoning/assessment, one resident/parallel,8192context,2minute keepalive; pace heavy work sequentially.

Earlier probability learner tests genuinely failed: v1 no retained methods; v2 ordinary probe1f994723-60de-48fd-8a32-a12c95c9ae48 completed on the older executor, strict wrapper failed calculation-length cap, diagnostic10/14math. No v3 patch exists. Scope36fabric records to prior97ef661, not current-source certification;14CLI versions do not prove agent/tool/account effects. Continued coaching must use real gaps, unseen assessments and verified retention while preserving capacity. Do not claim maximum competence from execution activity.

**Overall engineering mission: PARTIALLY COMPLETE — BLOCKED.** Dashboard live and verified; safe checkpoint is independently verifiable; pending reader deployment, identity closure, reference-aware cleanup, remaining functional monitoring and real overnight verification are explicit.
