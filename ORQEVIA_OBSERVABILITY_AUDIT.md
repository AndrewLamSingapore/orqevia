# ORQEVIA observability audit - initial checkpoint, 27 October 2026

Source baseline b360da98641a1332856c8fdeb2063d36312b7669. This is a dated source/runtime investigation, not a final production acceptance.

| Indicator | Actual source -> collector -> transport -> API -> UI | Root cause / impact | State |
| --- | --- | --- | --- |
| CPU/memory/disk/network | Native Windows CIM/adapter data -> ProgramData host sampler -> atomic JSON -> Docker readonly bind -> app/host_metrics.py -> interface_telemetry.py -> dashboard.mjs | Interface bound empty placeholder; old reader/projection lost reason, detail and original dates; UI only scalars | Source repair tested; install/remount/UI undone |
| Host identity | DESKTOP-27LKJ2V and current Windows boot -> receipt -> host reader/API source | Interface host env blank, source UNKNOWN; broad writer ACL means NOT_ATTESTED | Config/provenance repair undone |
| Core services | Nine Docker/services + real functional probes + existing canary -> operational host receipt -> observability_health.py -> telemetry -> health card | No producer/feed; static UNKNOWN UI; process presence insufficient | Helper source tested; producer/runtime/UI undone |
| Critical issues | Real declared observations -> SQLite operational-health.db -> telemetry -> critical card | Previously no operational journal/feed; unrelated geospatial alerts cannot supply this count | Dedup/recovery/store-failure fixture tests pass; continuous producer/UI undone |
| 21 agent registry | Canonical registry -> dispatch config + job/model observations -> role_observation -> telemetry -> agents/card | Old MAX(rowid)/updated_at heartbeat surrogate; recent failed tasks could count ready | Source classification tested; live/UI acceptance undone |
| Active jobs | Existing compute-queue/objective persistence -> readonly observer -> authorized telemetry work rows -> task cards | Activity is not completion, health or competence; retain actual source/task/job distinction | Existing flow preserved; new-candidate runtime acceptance undone |
| Application connection | Actual verified HTTPS response | Establishes reachability only, not host/services/agent health | Dated HTTP200 observations saved |
| Runtime/canary | Live container image/source -> 10-minute full-stack canary -> original receipt -> operational helper | Old expected gen22/db22290 mismatches b360 runtime; preserve mismatch until new accepted identity exists | Reconciliation undone |

Initial Windows receipts were fresh at03:50–03:55UTC, while the container mount was empty. Source data exists; the missing gauge is not proof of host failure. Protected SYSTEM task enumeration was denied, so exact scheduler identity is UNVERIFIED; receipt updates prove sampler liveness only. Existing ACLs gave Users FullControl; no ACL change made.

All21 registry roles are active logical on-demand roles. Initial old API showed21 historical /6recent at03:54UTC; later counts change with coaching. Never freeze the Owner's starting12/9 as current state. Completion of a compute job is not correctness of its role assessment.

Source traces, original per-role metadata and service evidence: operations/observability-recovery-20261027/agents/. See ORQEVIA_CODEX_HANDOVER.md for exact ownership, paths, contract and next actions.


## CURRENT OWNER-REQUESTED CODEX SAFE CHECKPOINT

The Owner requested generic CODEX labeling and immediate saving at below8%allowance. Current authority/resume instructions: **ORQEVIA_CODEX_HANDOVER.md**. Previous checkpoint statements below/above are dated; they do not override this update.

-LIVE: merged42b8baff interface/PWAv43, real native receipt readonly bind, CPU/memory/disk/network detail, all21agent records, nine service classifications and persistent incident coverage. Backend/coaching b360preserved. Actual production HTTPS desktop/mobile PASS, zero page errors/plaintext requests; session revoked. Stage13actual failure/offline/restart checks PASS,180seconds stopped with21learning records/trusted session/incidents retained, stale readings rejected until fresh samples.
-PERSISTENT CONFIGURATION: fixed existing Windows sampler+operational hook, protected digest inventory, configured writer access, DockerAutoStarttrue, restartalways, Windows logon/StartWhenAvailable tasks. Startup uses HTTPSlocalhost and reentry exited0. Actual full-PC overnight cycle NOTexecuted.
-SOURCE ONLY: optimized readonly readiness query;24tests PASS, actual6,881row reads return all21roles in0.059–0.130s under0.2s. Current live oldquery still returnsUNKNOWN on timeout. Actual candidate classification0confirmed/21unconfirmed with12stale/8latestfailed/1inprogress; no forcedREADY. Source queued for CI/merge/deploy, not represented as live.
-CANDIDATE ONLY: scopedgen23 receipt/manifest/compatibility diffs and7tests PASS. Unsigned, unapproved, unpublished; legacyexpected identity remains mismatched. Gateway/tunnel/public403/idle-worker evidence limitations remain. Critical authoritative count null rather than fakezero.
-NO JOB DELETION:6,881historical records since19September,6,053completed/724failed/103cancelled/1running,32,133,120bytes at the observation.1,444coaching-linkedIDs; reference-aware purge/compaction still pending after preservation. No active jobs/data/models removed.
-Exact latest saved commit, push/PR, archive/bundle verification, current private database backup/hash/quick_check and open actions are in ABEX operations/observability-recovery-20261027/checkpoint-20261027T0614Z/CUSTODY.json. The save is not full system certification or a whole-PC image backup. Original data/models/certificates/profiles/volumes remain in place.

Overall mission remains **PARTIALLY COMPLETE — BLOCKED**. See generic CODEX handover for exact next steps; no model-specific continuation is required.

## Live runtime checkpoint — 27 October 2026, 06:52 UTC

- PR #464 merged to canonical main as `60c5c11a4c6c2cc9f4f442ea28d88861740c8f17`; all nine required checks passed. The exact merged source was built as `orqevia:observability-60c5c11a`, image `sha256:feb8d833cca35026ac7af69b1d613b54bb353864c54eafc888c72ca73bd132a1`, using a 1 CPU / 1 GiB bounded BuildKit build.
- The interface-only deployment succeeded at 06:48 UTC. It uses the verified ABEX host receipt read-only. Deployment evidence confirms all peer container IDs and unrelated mounts were preserved; no database restore/deletion and no model job were started.
- Live HTTPS desktop/mobile acceptance passed at 06:50 UTC: source/build binding matched, CPU/memory/disk and network values rendered, no JavaScript or plaintext requests, no mobile overflow, offline/reconnect passed, and the test session was revoked. The readiness count is now a measured `0`; all 21 logical roles are correctly `UNCONFIRMED` in this observation (11 stale activity, 9 latest task failed, 1 task in progress). This is not 21 READY and not proof the agents are dead.
- The disposable observability stage was stopped; its 10.7 MB volume remains intact. Nine persistent ORQEVIA containers remain running. No jobs, databases, models, persistent volumes, certificates, profiles, or rollback images were deleted. The prior running workload was one `gemma3:12b`; heavy work remains single-model/sequential. No queue guard or deployment hold was used.
- Still incomplete: meaningful healthchecks for OTel, both Cloudflare tunnels, and the integration gateway; signed/published component identity; authoritative critical-issue coverage and remaining functional service evidence; reference-aware historical-job cleanup; and actual whole-PC power-off/restart verification. The live core status remains DEGRADED and critical count UNKNOWN where coverage is incomplete.
- Owner coaching request recorded: **coach the helper** using actual task feedback and unseen assessment. The canonical 21-agent registry has no separate identity named `helper`; the existing Academy cohort covers the 21 registered specialist roles. Do not invent an identity or claim a coaching outcome. Attach any dedicated coaching record only to a verified registered target.
- Permanent offline recovery is still not fully verified: no real whole-PC power-off/reboot has followed these changes. The next boot must confirm a fresh boot-bound collector receipt, local HTTPS dashboard recovery, and persisted jobs/sessions/incidents before closure.

Overall verdict remains **PARTIALLY COMPLETE — BLOCKED**. This dated section supersedes older status wording in this file where those earlier entries describe the candidate as unmerged or the readiness count as UNKNOWN; retain those entries as historical evidence.
## Shutdown save and Golden/coaching update — 27 October 2026, 06:58 UTC

Fresh checkpoint: `operations/observability-recovery-20261027/checkpoint-20261027T0658Z/SHUTDOWN-HANDOVER.md`; private data/config custody is in `C:/Users/Admin/AppData/Local/ORQEVIA/checkpoints/observability-shutdown-save-20261027T0658Z`. It contains 466 protected SQLite snapshots with copied-hash and host quick-check PASS, current private Compose/environment captures, and private full-container inspection. Canonical-main and current-doc-branch source archives are sealed alongside runtime evidence. This is not a whole-PC image or end-to-end completion; the PC was not shut down.

Golden Gen22 was checked read-only: the manifest SHA-256 `e833232a0f9bc8dc2bb76d62f2fb2d4d7c73ea79c1fc7699cfa698db80399c38` matches `EXPECTED-RUNTIME.json`; its pinned image `sha256:181d59eaad8a856dd676b297f9f8af7dade0b6f404354c69beef88414adde4b9` is present. Three containers based on that image are stopped stage/rollback containers. Their data mounts and the Golden image remain preserved.

Owner coaching requests: coach the helper through real feedback and unseen assessments (registry identity is not mapped; do not fabricate one), and continuously improve the OTel collector from measured receiver/exporter reliability and recovery evidence. Neither request is a claimed coaching result; no model job was added.

Still open: four missing meaningful container healthchecks; reference-aware historical-job cleanup; service and critical-monitoring coverage gaps; scoped Gen23 compatibility/signing/publication; and the real whole-PC power-off/restart recovery check. Core remains DEGRADED and the critical-issue total UNKNOWN when coverage is incomplete. Readiness is 0 confirmed/21 unconfirmed at the recorded observation. Preserve the no-deletion and no-fabricated-health rules.

The Owner's latest direction is to notify them only after end-to-end completion so they can perform the PC shutdown. This safe save is not that completion notice.
## Fabric-to-agent wiring check — 27 October 2026, 07:05 UTC

The versioned source registry defines 36 fabrics, but this does **not** establish that all 36 are wired and functionally verified for the registered agents. Current source test `test_old_catalog_receipts_cannot_self_certify_current_runtime` requires 0 VERIFIED without fresh runtime receipts; the collective operation endpoint reports one selected fabric for an operation. The current verified count is therefore **0/36**, and all-fabrics-to-agents wiring is **UNVERIFIED**. Build an explicit agent-capability-to-fabric map and obtain source-bound functional receipts before claiming wiring. This remains open and does not block unrelated deployment work.
## Requested component status audit — 27 October 2026

Current evidence: Agent Factory is source-present but has no verified live production route or end-to-end generation/registration receipt; generated candidates are advisory-only. Academy HTTPS endpoint responds, but its cohort record is STALE (20 READY, 1 WAITING, 21 baseline, no assessment passes/certification). Fabric catalog has 36 entries, with 0/36 currently verified and agent wiring unverified. PIF source engineering checks exist, but the current verified HTTPS status path returned 404, so production flow is unverified. MLP has historical live-activation records, but both current HTTPS status paths probed returned 404, so present production availability is unverified. A 404 describes the tested path and does not by itself establish that source implementation is broken. See CODEX handover and remaining-blockers table for exact paths and next evidence needed.

## Inference coverage — 27 October 2026

**All inference paths working: NOT VERIFIED.** ORQEVIA has multiple inference components and paths; the checks recorded here are not a full inventory or end-to-end test of every request/model/fabric/agent integration. PIF’s current HTTPS status probe returned 404; MLP’s two current HTTPS status probes returned 404; the live Academy response is fixture curriculum/cohort state, not evidence of production predictive inference. No global inference-availability or accuracy claim is supported. Enumerate every deployed inference route and verify authenticated request → intended model/fabric → provenance/evidence persistence → response and restart recovery before marking all inference working.
