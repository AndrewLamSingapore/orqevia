# Codex DeepSeek handover - ABEX / ORQEVIA - 27 October 2026

**READ FIRST. Saving the handover does not complete the engineering mission.**

Owner asked for this packet because Codex allowance was below 25%, has Codex DeepSeek available, and intends to shut down the ABEX PC after the save is complete. This is a continuation checkpoint, not a production acceptance receipt. No automatic PC shutdown, service stop, alert disablement or deployment was performed for this handover. Three explicitly authorized parallel Codex agents finished and handed back their files; none has more work running.

## 1. The next action

Read `C:/Users/Admin/Documents/ABEX/AGENTS.md`, the worktree's `AGENTS.md`, this handover and the six `ORQEVIA_*.md` mission files. After reboot, obtain fresh actual host/container/HTTPS evidence before changing anything. Existing observations below are dated, not live health claims. Continue safe, reversible work without another routine permission request.

Canonical repository: https://github.com/AndrewLamSingapore/orqevia

- Worktree: `C:/Users/Admin/Documents/ABEX/work/orqevia-observability-20261027`.
- Candidate branch: `codex/observability-recovery-20261027`.
- Starting canonical main: `b360da98641a1332856c8fdeb2063d36312b7669`.
- Exact saved candidate commit, remote push status, bundle hashes and file custody are recorded separately in `C:/Users/Admin/Documents/ABEX/operations/observability-recovery-20261027/handover/CUSTODY.json` to avoid a self-referencing commit hash.
- Check for subsequent remote main changes; preserve the candidate and reconcile normally. Do not hard-reset, force-push or deploy this incomplete candidate.

## 2. Standing boundaries

Use **https://localhost:8443/pwa/** with CA and hostname verification. LAN origin is `https://192.168.1.23:8443`. Public CA: `C:/Users/Admin/Documents/ABEX/LOCAL-SECRETS-OPEN/tls-orqevia-epoch-20261016/ca.crt`. Never print private keys, environment files, cookies, tokens, model prompts/results or full Docker Config/Env. Python SSL with that CA works; Windows curl Schannel previously failed local revocation checking. Do not bypass TLS. Port 8081 remains retired.

No queue guard, queue lock, deployment hold or invented approval gate. Preserve existing private Docker/loopback transports until a coordinated TLS migration; replacing URL strings would break inference. Preserve authentication, certificates, sessions, databases, volumes, independent research/message boards and rollback resources. The new P0 mission does not authorize weakening security. REA and MiroFish are excluded; do not repair/integrate them. A prior REA deletion was policy-rejected; do not bypass or claim deletion. Dell-origin testing was explicitly parked by Owner and is not an active blocker. Cloud migration, provisioning, paid API usage and new spending remain on hold.

Conserve allowance and host capacity: no extra agents are needed. Run heavy tests, benchmarks and real inference sequentially. Reasoning and assessment remain `gemma3:12b`; one resident model, one parallel inference, 8192 context and two-minute keep-alive. Do not downgrade models for speed. Registry roles are on-demand logical roles, not 21 dedicated worker processes. A recent job is not a heartbeat or role certification.

Source, focused tests, required CI, merge, build, deployment and runtime acceptance are separate milestones. Only Owner changes STATUS Verified sections. The project pins historical STATUS sections byte-for-byte; the new candidate checkpoint is separately admitted by an exact section hash without changing older checks.

## 3. Actual saved progress

**SOURCE IMPLEMENTED, NOT DEPLOYED:**

1. `scripts/collect-host-metrics.ps1`: compatible v1 receipt plus real CPU/memory/disk/network detail, original timestamps/sources/failure causes, bounded atomic write, same-boot counter-delta rates. First/reset rate stays unavailable. Optional fixed sibling hook `C:/ProgramData/ABEX/PrimeHostMetrics/collect-operational-health.ps1` runs with no args after a successful host write; failure preserves the host receipt. Hook implementation is still absent.
2. `app/host_metrics.py`: bounded reader, host identity checks, original per-field times, 150-second freshness at observed roughly 60-second cadence, specific missing/stale/invalid/permission reasons, detail groups and legacy scalar compatibility. Writer provenance is correctly `NOT_ATTESTED`.
3. `app/interface_telemetry.py`: separates historical activity, fresh activity and recent successful execution; failed/cancelled/running activity cannot count as confirmed ready. Keeps all 21 roles, real job/task identity and original dates, lifecycle/config/model dependencies and last success/failure. Role heartbeat is null/NOT_COLLECTED. Readiness scope explicitly excludes role competence. Includes host and operational-health aggregate.
4. `app/observability_health.py`: reads a future host operational receipt, classifies nine services, preserves check times, reconciles deduplicated operational incidents/recoveries into `$ORQEVIA_DATA_DIR/operational-health.db`, retains open incidents and bounded resolved history. Missing/stale/invalid coverage or SQLite errors produce null authoritative critical count. A known count is separate. It makes no network/model calls and runs no daemon.

Focused combined run actually executed: **68 passed**, one upstream Starlette/AnyIO deprecation warning. A separate STATUS preservation run passed **53 tests in4.31s**. `ruff check` on the changed Python files passed using the installed CLI; `python -m ruff` was unavailable and is not the successful lint command. PowerShell AST parse and `git diff --check` passed. JUnit and log: `operations/observability-recovery-20261027/handover/integrated-tests.{xml,log}` and `status-preservation.{xml,log}` under ABEX, with copies in the candidate. These are source/fixture tests, not live deployment acceptance.

Agents' original metadata/table/response sample are under the candidate's `operations/observability-recovery-20261027/agents/`. Host and service evidence originally saved under ABEX operations is copied there for coherent handover. Sample readiness JSON is an explicitly dated replay, not current runtime data.

## 4. Verified root causes

- The Windows host collector was already writing fresh receipts. Actual host is **DESKTOP-27LKJ2V**, not the browser or a Docker container. Initial boot ID was `2026-10-27T00:15:26.5000000Z`; re-read it after reboot, never reuse this as current boot identity.
- Installed script: `C:/ProgramData/ABEX/PrimeHostMetrics/collect-host-metrics.ps1`; actual receipt: `C:/ProgramData/ABEX/PrimeHostMetrics/receipt/host-metrics.json`.
- Interface bind `/run/orqevia-host-metrics` instead points read-only to `runtime/orqevia-epoch-20261016/deploy/unconfigured-host-metrics`, an empty placeholder. `ORQEVIA_HOST_METRICS_DIR` was unset. That is the delivery fault; do not replace the functioning collector with a duplicate.
- Old reader/API discarded original field timestamps/reasons/detail. A fresh API snapshot could conceal stale child values. PWA lacks per-field validation/details.
- `ORQEVIA_INTERFACE_HOST_ID` is blank, producing source.instance UNKNOWN. Set it to the real verified host ID and configure `ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID` coherently.
- Installed collector/receipt ACLs grant BUILTIN\Users FullControl. Reading was not denied, but protected writer provenance is unverified. Preserve original SDDL before any scoped least-privilege repair; retain actual SYSTEM writer and Docker Desktop reader. No ACL repair has occurred yet.
- Protected SYSTEM task registration is invisible to the ordinary task context (`System32/Tasks` AccessDenied). Actual receipt updates prove liveness, not the task's exact identity. Fix watchdog false TASK_MISSING classification from fresh same-boot evidence; do not invent scheduler identity or broaden privileges merely to see it.
- Old readiness selected MAX(rowid), treated updated_at as heartbeat and counted recent failures as ready. All 21 are active on-demand roles sharing the executor; stale activity is UNCONFIRMED, not proof of OFFLINE.
- Core services HTML is a static UNKNOWN; dashboard JS resets critical-count to UNKNOWN. There was no authoritative operational incident store/feed. Existing geospatial alerts are unrelated and must not be repurposed.
- Full-stack canary runs every **10 minutes** (actual PT10M); source comments/install defaults saying five are not the live schedule. Its old expected runtime and published Golden gen22 still bind db22290 while the actual runtime is b360da9. Deployment-identity therefore correctly fails; it is not proof of a service outage. Preserve it until a new accepted source-bound manifest exists.

## 5. Exact remaining work, in order

**A. Complete the existing collector path.** Implement `scripts/collect-operational-health.ps1` and a small bounded native producer (stdlib Python is suitable) for the already implemented helper contract. Install it as the fixed sibling hook; use the existing scheduled host sampler, not a new daemon/task. Whitelist Docker inspect metadata in memory, bounded timeouts, no credential output, no model warmups. Embed actual original canary timestamps and history, not poll times. Publish atomically. After writing, issue one strict HTTPS telemetry GET to continuously reconcile incidents even without a browser. Observe bounded retry/backoff and telemetry retention.

**Operational receipt contract:** config `ORQEVIA_OPERATIONAL_HEALTH_RECEIPT` absolute path, intended `/run/orqevia-host-metrics/operational-health.json`; schema_version `orqevia.operational-observation.v1`; host_id, boot_id, observed_at timezone ISO, cadence_seconds actual integer1..600, exactly nine services, collector_checks, unmodified original canary (`orqevia.full-stack-canary.v1`), optional canary_check_history keyed by check ID with actual last_success_at/first_failure_at. Import the exact `SERVICE_SPECS`, `COLLECTOR_CHECKS`, `CANARY_CHECKS` from `app/observability_health.py`; do not guess its schema.

Service rows: service_id, container_name, observed_at, process_state, docker_health, health_observed_at, health_last_success_at, checks. Each check needs check_id, kind, status PASS/FAIL/UNKNOWN/NOT_CONFIGURED, original observed_at, last_success_at, optional first_failure_at, safe reason/source/scope. HTTPS PASS requires `certificate_verified: true` and a credential/query-free HTTPS source URL. An actually failed TLS check is FAIL; missing configuration/evidence is UNKNOWN/NOT_CONFIGURED, not fabricated outage.

Required functional observations:

| Service | Required check IDs / kinds |
| --- | --- |
| backend | backend-health / DOCKER_HEALTHCHECK; backend-readiness / DEPENDENCY (actual DB/worker/readiness, not constant READY) |
| interface | interface-https / HTTPS_READINESS |
| ollama | model-inventory / DEPENDENCY (inventory, not inference acceptance) |
| intelligence | intelligence-https / HTTPS_READINESS (real bridge/data path) |
| coaching | controller-heartbeat / DEPENDENCY (original SQLite heartbeat) |
| otel-collector | otel-export / TELEMETRY (recent real exports, correct current backend network namespace) |
| integration-gateway | gateway-https / HTTPS_READINESS |
| cloudflared | tunnel-connection / DEPENDENCY and tunnel-https / HTTPS_READINESS |
| cloudflared-dual | tunnel-connection / DEPENDENCY and tunnel-https / HTTPS_READINESS |

Collector checks are collector-source, host-identity, boot-identity, all CONFIGURATION. Missing current collector trust leaves coverage incomplete; stale/UNKNOWN cannot recover incidents. Receipt TTL=2*actual cadence, canary TTL independently1200s. A Cloudflare Access challenge proves edge/auth behavior, not application readiness. Never bypass Access or TLS to improve the count. Report inaccessible private/public functional checks precisely.

**B. Finish PWA health cards.** Root has made **no frontend changes** in this mission. Files: `clients/pwa/dashboard.mjs`, `index.html`, `dashboard.css`; preserve layout/brand/navigation. Remove forced UNKNOWN only when backed by validated data. Add Core services ID, real state/check details; show critical count only with complete fresh coverage and working incident store, known open count separately. Show each metric's original sample/source/freshness/reason, byte capacities and actual network interface counters/rates/errors. Validate child dates independently of fresh parent snapshot. Stale/offline immediately clears cached healthy data. Agent rows need new readiness reasons and last success/failure, without calling task timestamps heartbeats. Bump shell v42 coherently if assets change. Add focused meaningful JS tests; existing operational-facts/race fixtures need compatibility. Race fixture DOM has textContent/setAttribute/append/replaceChildren, not full browser DOM.

**C. Review/integrate and deploy safely.** Install updated host sampler, preserve SDDL and safely scope writer/read ACLs; verify the next actual scheduled same-boot receipt. Rebind interface read-only mount to the real receipt directory; set real host identity and operational receipt config in actual Compose/env. Never print .env. Test in isolated HTTPS stage first. Publish through branch/PR required CI; no force push. `status-authority` and `quality` are required; browser dependency downloads previously hung, report separately. No new mission PR existed at the start of handover; see custody for saved branch publication.

Deploy helper `operations/system-security-20261025/deploy_https_transport.py` enforces unchanged mounts and narrowly allowed env changes. It CANNOT be used unchanged for this intended bind/config repair. Adapt the allowed diff narrowly and verify every unrelated mount/env/cert/session unchanged. A minimal interface-only deployment may avoid interrupting backend/coaching, but identity manifests must honestly represent component revisions. If updating backend too, update coaching source/notification compatibility deliberately. Do not restart inference reflexively.

**D. Execute real acceptance.** Verify native receipt→mounted reader→verified HTTPS API→desktop/mobile UI. Re-audit all21 roles with original evidence; do not force READY. Test collector stop/stale/reconnect, unavailable service/recovery, API timeout/network loss, expired activity, DB failure, alert dedup/persist/recovery/retention using an isolated stage or controlled test seam first. Live source tests do not qualify these runtime paths. Verify least privilege and absence of leaked credentials. Perform only relevant regressions.

**E. Reconcile runtime identity after acceptance.** New Golden generation23 must be based on genuine source-bound acceptance and retain gen22. Update `operations/permanent-readiness-20261017/EXPECTED-RUNTIME.json` and publisher pointer only after independent proof. Sign with existing key without reading it; preserve verification logic and pin trusted public key. Do not copy the observed image into an expected manifest merely to pass. Old physical mobile/audio evidence must not become new-feature acceptance. Run the canary again and preserve actual failures.

**F. Final six docs and honest closure.** Update the checkpoint docs with commands/results/commits and full acceptance evidence. Until then no production-ready claim. Overall mission verdict must be exactly one of COMPLETE — VERIFIED, PARTIALLY COMPLETE — BLOCKED, FAILED VERIFICATION. Unfinished implementation and unavailable external checks must be distinguished; Dell parked scope is not a blocker.

## 6. Runtime / deployment custody

At handover collection, backend/interface used `orqevia:local-closure-b360da9`, image `sha256:d8cf1f7ed9001c013fe1473414aabd5e8d741b507d98310493f7f58ea5c1f15c`; coaching used `orqevia-coaching:local-closure-b360da9`, image `sha256:73171676cd0904a9bf53502c1c68f578d2a2d996d5d01897802a28901f8121ab`. Five declared Docker health checks were healthy; running-only containers are not functionally verified. Nine persistent containers plus one disposable stage were observed; exact IDs/restart policies/dates are in `handover/runtime-at-handover.json`.

Runtime: `runtime/orqevia-epoch-20261016`; Compose project `orqevia-epoch-20261016`, main `docker-compose.yml` + `docker-compose.otel-collector-20261022.yml`, profile clients. Preserve its private .env and volumes. Disposable stage is `orqevia-local-closure-stage-20261027-linux`, old candidate45eef23, separate volume and strict HTTPS `https://localhost:8444`; it is not a tenth core service or a copy of production acceptance.

Rollback retained: `orqevia:cross-device-db22290`, image `sha256:181d59eaad8a856dd676b297f9f8af7dade0b6f404354c69beef88414adde4b9`. Reuse live data for application rollback; do not blanket-restore DB snapshots over newer work.

Native monitoring: `operations/permanent-readiness-20261017/Invoke-FullStackCanary.ps1`, `LATEST-FULL-STACK-CANARY.json`, EXPECTED-RUNTIME.json. Golden manifest `operations/runtime-attestation/golden-gen22-manifest.json`; installed publisher `C:/ProgramData/ORQEVIA/runtime-attestation/Publish-GoldenRuntimeAttestation.ps1`. Runtime supervision and coaching supervisor remain enabled. `operations/coaching-priority-20261013/supervisor-pin.json` points to b360 coaching; verify after reboot. No controlled current supervisor interruption/recovery test has yet completed for final closure.

## 7. Saved state and shutdown semantics

The live workload continues between snapshots. A running job is not reported as completed. Metadata only is in `handover/persisted-work-at-handover.json`; recheck after reboot and allow the existing executor's source-bound recovery to handle expired leases. Do not delete running rows, resubmit blindly or invent progress. Physical power loss and post-reboot recovery have not been qualified by this handover.

Online SQLite backups use the existing SQLite backup API, each database separately; there is no atomic distributed snapshot and no restore into production. **465 snapshots** passed copied SHA256 verification and host-side PRAGMA quick_check. Private snapshot directory and exact count are in `handover/database-checkpoint-summary.json`; database contents are Owner/SYSTEM/Administrators-only and excluded from Git, zip and the model context. Existing certificates, profiles and trusted-session files were preserved in place, not exported into public handover. No blanket filesystem clone was attempted.

Root handover mirrors: `C:/Users/Admin/Documents/ABEX/CODEX-DEEPSEEK-HANDOVER-20261027.md`, `ABEX_CURRENT.md`, `START-HERE.md`. Candidate files are committed on their branch; a source-only Git bundle and file-hashed portable checkpoint provide an offline fallback. See CUSTODY.json for actual verification/publication, not an assumption of success.

## 8. Earlier authorized work still outstanding (separate from new P0)

- Cleanup itself completed earlier: approximately28.819GB host recovery,3.35GB retired model internally,13 obsolete images/cache removed. Evidence `operations/docker-cleanup-20261027T002314Z/REPORT.md`. Preserve models/volumes/history; no new blanket prune is needed. Disk recovery is not RAM recovery.
- PR461 merged97ef661; PR462 mergedb360da9. Current b360 deployed direct-admission and probabilityv2 changes. Required quality/status checks passed for those PRs; earlier browser download hangs are not a new observability pass.
- First real probabilityv1 learner cycle completed but failed unseen math; no methods retained for that failed assessment. Do not certify learning.
- Actual ordinary probe `1f994723-60de-48fd-8a32-a12c95c9ae48` ran03:30:37–03:38:17 UTC on the older executor, not on the later b360 restart. Strict wrapper failed because calculation length1428 exceeded the grader's1200 cap. Independent diagnostic math was10/14, with conditional/joint/random-variable/Markov errors. Actual result is `operations/autonomous-closure-20261027/calculation-format-resumed-result.json`; diagnostic is `calculation-format-numeric-diagnostic.json`. Earlier queued-only harness grade was invalid and preserved as dated history. Do not repeat the claim that this probe never executed.
- Probabilityv2 is enabled but the current scheduler starts role competency first; its cohort had not been created at initial observability audit. Future work: isolate14 hypotheticals to prevent fact mixing, assess nonsemantic calculation-length cap, allow actual~460s inference against current300s coaching deadline, and execute a genuine new unseen assessment. No v3 patch exists. Do not weaken the numerical oracle or reuse failed assessments as successful training.
- All36 scoped fabric records were effectively verified on97ef661 after a targeted f07 policy recheck, not recertified for b360. 14 actual CLI versions were observed; versions do not prove authenticated accounts, role-tool integration or external effects. Earlier `MISSION-STATE.json` is dated and had stale queued/CI labels; the new handover is the current continuation index.
- Previous isolated stage restart/rollback/session recovery passed within that earlier scope. Final live supervisor recovery, current source-bound attestation and boot acceptance remain undone. Dell remains parked.
- Separate undeployed remote-worker WIP is `work/orqevia-digitalocean-20261027`: modified `app/fabric_runtime.py`, untracked `app/remote_execution.py`, `tests/test_remote_execution.py`,78pass/1fail (duplicate statistics operation). Preserve it without merging into this P0 candidate. Earlier sealed preservation packet `operations/shutdown-resume-20261027-0555/` and historical handoffs remain intact.

## 9. Useful existing tooling, with scope caveats

`operations/autonomous-closure-20261027/`: `build-release.py`, `create-stage.py`, `stage_entry.py`, `stage-recovery.py`, `deploy-coaching.py`, `coaching-progress.py`, `browser-academy.cjs`. Several hardcode the OLD worktree `work/orqevia-local-closure-20261027`; explicitly adapt a copy to this candidate and record the source tree before reuse. Do not run old bootstrap scripts to restart/duplicate existing jobs. `resume-calculation-format.py` regrades the original job, not a new inference.

`operations/docker-cleanup-20261027T002314Z/`: actual strict HTTPS objective/artifact/idempotency and browser smoke tooling. For Playwright use the existing installed `playwright-core@1.63.0`; page.evaluate(fetch) uses browser trust, whereas context.request can use a separate CA store. Never set ignoreHTTPSErrors. Browser desktop1440/mobile390; preserve real loading/offline/error/recovery behavior. Source bundle changes require packaging and service-worker update checks.

Do not spend allowance rediscovering these paths or asking again for routine authorized reversible work. Implement the missing producer/UI, prove actual data flow, then close from evidence.


## Resumed implementation checkpoint

Owner resumed with full approval and clarified full access for configured ORQEVIA agents/services. Nightly shutdown/extended offline recovery is required. The handover above remains the dated initial checkpoint, not a current claim that no frontend or native changes exist.

- Implemented scripts/collect_operational_health.py, scripts/collect-operational-health.ps1, scripts/install-host-observability.ps1 and focused producer tests. Existing native scheduled sampler has run the new source automatically. Original source/ACLs preserved privately; configured writers retain access.
- Native receipt now carries actual capacities/interfaces/rates/error counters. Operational source/host/boot checks PASS. Fixed Docker inspect template nil-health handling; absence of a Docker healthcheck no longer discards four service observations. Corrected producer suite15PASS; existing68 host/API/helper tests passed in the executed81-test combined run before the two added regression cases. No model calls submitted.
- PWA consumes original child timestamps and shows source/reason/capacity/network/service/incident/readiness data. No zero critical total without full fresh coverage and working store.46 frontend tests PASS; shell coherentlyv43. Source helper/new tests formatted for CI; previous b22quality/status/browser CI passed, its new-file format failure was corrected.
- Live new-image deployment/bind/API/browser acceptance and actual prolonged offline/restart qualification are still PENDING. Public functional HTTPS request returned403 with certificate verification, so no authenticated public functional proof is claimed. Idle backend worker heartbeat and private gateway/current tunnel connection evidence remain limitations. Do not classify those as healthy from process presence.
- Evidence: ABEX operations/observability-recovery-20261027/collector-install.json, collector-install-fixed.json, integration-tests.xml. Read exact timestamps; no physical PC shutdown performed for testing yet. The existing source host task remains protected/invisible to ordinary enumeration; actual live samples prove current execution.
