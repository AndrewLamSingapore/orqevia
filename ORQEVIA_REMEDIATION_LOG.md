# ORQEVIA remediation log - SOURCE CHECKPOINT ONLY

Baseline b360da98641a1332856c8fdeb2063d36312b7669; branch codex/observability-recovery-20261027. Saved candidate commit is recorded in ABEX operations/observability-recovery-20261027/handover/CUSTODY.json.

| File | Actual change | Validation / deployment |
| --- | --- | --- |
| scripts/collect-host-metrics.ps1 | Native capacities/interfaces/counters/errors/rates and original per-field source/times; optional fixed operational sibling hook |24 host tests, AST parse; not installed |
| app/host_metrics.py | Bounded compatible v1 reader, detailed values, explicit failures/identity/freshness |24 host tests; not deployed |
| app/interface_telemetry.py | Genuine recent-success readiness; explicit on-demand/heartbeat limitation; original task/job/model/host metadata; helper aggregation |23 telemetry tests; not deployed |
| app/observability_health.py | Nine-service validation, separate process/function states, coverage, persistent dedup incident/recovery/retention |21 health tests; not deployed |
| tests/test_host_metrics.py | Realistic fixture failures, stale/partial/malformed/identity/counter-baseline coverage |Included in68-pass combined run |
| tests/test_interface_telemetry.py; tests/test_interface_telemetry_counts.py | Failed/running activity cannot count ready; real state ordering/IDs/dependencies |Included in68-pass combined run |
| tests/test_observability_health.py | Healthy/failure/recovery/dedup/stale/invalid/TLS/inventory/journal tests |Included in68-pass combined run |
| STATUS.md; tests/test_portfolio_reconciliation.py | Exact dated candidate-only checkpoint, older historical/Owner Verified sections preserved |53 preservation tests passed in4.31s |
| ORQEVIA_*.md; operations/observability-recovery-20261027/agents/ | Evidence and explicit DeepSeek handover |Documentation, not a substitute for implementation |

No PWA code, runtime Compose/env/mount, installed collector, scheduler, service configuration, runtime ACL or production alert state was changed for this checkpoint. Readonly HTTPS/runtime observations and online SQLite backups were saved separately. No new model jobs or paid calls were submitted for handover. Private DB contents never enter Git or the public packet.

Three parallel agents have finished; root owns the next implementation. No operational producer hook implementation exists yet. No new mission build/merge/deployment/acceptance has occurred. See ORQEVIA_REMAINING_BLOCKERS.md.


## Resumed implementation checkpoint

Owner resumed with full approval and clarified full access for configured ORQEVIA agents/services. Nightly shutdown/extended offline recovery is required. The handover above remains the dated initial checkpoint, not a current claim that no frontend or native changes exist.

- Implemented scripts/collect_operational_health.py, scripts/collect-operational-health.ps1, scripts/install-host-observability.ps1 and focused producer tests. Existing native scheduled sampler has run the new source automatically. Original source/ACLs preserved privately; configured writers retain access.
- Native receipt now carries actual capacities/interfaces/rates/error counters. Operational source/host/boot checks PASS. Fixed Docker inspect template nil-health handling; absence of a Docker healthcheck no longer discards four service observations. Corrected producer suite15PASS; existing68 host/API/helper tests passed in the executed81-test combined run before the two added regression cases. No model calls submitted.
- PWA consumes original child timestamps and shows source/reason/capacity/network/service/incident/readiness data. No zero critical total without full fresh coverage and working store.46 frontend tests PASS; shell coherentlyv43. Source helper/new tests formatted for CI; previous b22quality/status/browser CI passed, its new-file format failure was corrected.
- Live new-image deployment/bind/API/browser acceptance and actual prolonged offline/restart qualification are still PENDING. Public functional HTTPS request returned403 with certificate verification, so no authenticated public functional proof is claimed. Idle backend worker heartbeat and private gateway/current tunnel connection evidence remain limitations. Do not classify those as healthy from process presence.
- Evidence: ABEX operations/observability-recovery-20261027/collector-install.json, collector-install-fixed.json, integration-tests.xml. Read exact timestamps; no physical PC shutdown performed for testing yet. The existing source host task remains protected/invisible to ordinary enumeration; actual live samples prove current execution.


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
## Component verification snapshot — 27 October 2026

This is a status finding, not a remediation claim. Agent Factory is source-present but production routing/registration is unverified; Academy endpoint responds with a STALE cohort and no recorded assessment passes; 36 fabrics have 0 current VERIFIED receipts; PIF's probed live status path and both probed MLP status paths returned HTTPS 404; and full inference-path coverage remains unverified. Exact observations, caveats and follow-up evidence requirements are in `ORQEVIA_CODEX_HANDOVER.md`, `ORQEVIA_HEALTH_VERIFICATION.md`, and the checkpoint's `evidence/component-status-audit-20261027T071032Z.json`. No code activation, status forcing, or fabricated pass was performed as part of this audit.
