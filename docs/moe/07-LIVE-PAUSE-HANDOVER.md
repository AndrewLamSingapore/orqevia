# Current engineering handover - 28 October 2026

## Latest checkpoint / shutdown preparation

The Owner requested save, clear status and a pause for later continuation.
Read [the unified mission](../MASTER-P0-ENGINEERING-MISSION.md),
[the five-lane pathway](../MULTI-LANE-EXECUTION-PATHWAY.md) and the permanent
[Intelligent Efficiency Doctrine](../INTELLIGENT_EFFICIENCY_DOCTRINE.md).
Do not confuse a completed shutdown checkpoint with production acceptance.

Phase2 ran bounded authorized tests without releasing production:6schema-based
1Bclassification trials passed,1embedding batch passed, and1deep scheduling
reasoning trial failed its independent correctness oracle. The initial1Btest
without a schema also failed output shape. All original receipts are retained;
no quality requirement was weakened or failed result relabeled successful.

Monitoring root cause:6of9services have complete declared probes. The integration
gateway and both Cloudflare connectors lack verified HTTPS functional probes;
the gateway currently listens on privateHTTP8080. Canary liveness recency and
deployment-attestation warnings are mixed into the legacy aggregate. The new
source separates service functionality from verification;32targeted tests passed.
The API/UI repair and missing probe coverage are not deployed or complete.

The observed4confirmed executions meant latest completed jobs within1hour and
current model availability (a21/a26/a28/a29 at09:19UTC), not four functional agents.
Later authorized a19tests changed this count. Completion does not establish
semantic quality, and inactivity under Owner pause is not a failed agent.

At09:39UTC there were no queued/running/held jobs and neither Ollama instance had
a loaded model. Docker Ollama was0%CPU/~1.112GiB after the qualification runs;
do not reuse the earlier58MiB snapshot as the latest value or call this a leak.
The durable pause remained generation0. No Docker service restart occurred.

455SQLite backups passed quick_check and host-copySHA256 verification. Checkpoint:
`C:/Users/Admin/AppData/Local/ORQEVIA/checkpoints/pre-shutdown-20261028T093947Z/`.
These are per-database consistent backups, not a distributed or off-machine backup.
All model assets remain in their original persistent storage.

Safe idle-app updates:uv0.13.6 and MicrosoftTeams26225.1806.5074.1452 installed.
AWSCLI/Git/GitHubCLI require administrator installation; Docker/Ollama/ChatGPT
updates affect live software and remain pending. No driver or firmware change.

Read [the standing Owner policy](../HOME-ECO-OPERATING-POLICY.md) first. It
supersedes conflicting earlier operating directions. Source, tests, deployment
and observed runtime acceptance remain separate evidence.

## Preserve the recovered state

Production background admissions are **PAUSED**, generation0, in the existing
`/data/compute-queue.db`, table `compute_background_admission`. The installed
`compute_owner_background_admission` trigger refuses queued/held-to-running
transitions below interactive priority50. It does not cancel active work,
clear waiting jobs or change completed results. Missing state fails closed.
There is no expiry or automatic resume. Explicit Owner resume is required.

The Windows coaching supervisor used to archive `/data/coaching.pause` every
30seconds under an older always-on instruction. Its deployed script now reads
the durable state and preserves the compatibility marker. Only the Windows
supervisor task was reloaded. **No Docker container or Ollama was restarted.**
Tracked source copy: `deploy/windows/Coaching-Supervisor.ps1`.

Owner CLI: `python scripts/background_admission.py status`. `verify` tests the
installed trigger inside a rolled-back transaction without inference. Resume
requires explicit Owner instruction and the observed generation. Do not resume
to run a benchmark or clear a warning.

## Measured observations

- Last active application inference completed at08:48:05UTC.
- No new background application job started after pause activation08:46:20UTC
  through the08:55UTC compliance check. Nine containers and21identities remained.
-12B unloaded naturally by08:50:15UTC with unchanged2minute retention.
- Active baseline:18samples/171seconds, mean787.42%CPU, peak814.34%, peak cgroup
  memory13.77GiB, low Linux headroom and measured swap activity.
- Twelve post-unload intervals/120seconds averaged1.20%cgroup CPU, including
  diagnostic exec overhead. Separate Docker idle samples were0.00%.
- Docker memory fell from13.65GiB to58.57MiB. Final cgroup memory was67.5MiB;
  Linux available memory was14.07GiB. The counters account for cache differently.
- This compares active work with idle deferral. It is not equivalent-work
  throughput, energy savings or CPU-thread efficiency evidence.

Both originally identified baselines completed before the cancellation request:
a02 `0cd4aa5c-cee8-46da-8a61-3915b6c9ab43`, a28
`29da6645-1fb4-47da-9d23-80680f45360b`. Their results remain intact.
Successors a02 `495e8c58-dcdf-4221-b455-7583fd08e3b9` and a04
`a8e1954e-38a2-4020-b7e6-3ef0c9141c3d` failed at old300second deadlines.
a28 successor `74a98e06-4f9a-4b40-a38e-32216f09c3c1` and final a29
`ba84d7ad-21d0-4e82-922d-f2209959632b` completed. No job was cancelled here.

## Capability status

| Capability | Actual evidence |
|---|---|
| Persistent background pause | Installed/enforced in running DB; live rollback-only probe passed |
| Supervisor preserves pause | Local script deployed; repeated PAUSED records after task reload |
| Model/provider choice | Active guidance superseded; candidate removes coaching model-name restrictions |
| Existing routing | Live deterministic selector chooses1B for narrow classification,12B for planning; embeddings configured |
| Patient shared inference | Candidate tested; running backend remains `direct` / `balanced` |
| HOME_ECO / ULTRA_ECO profiles | Complete profiles not deployed or qualified |
| Global single-flight/shared evidence | Pending; no globally enforced cache/dedup claim |
|21agent real end-to-end quality | Not retested during pause; registration/history do not prove it |
| CPU-thread/model-quality tests | Phase2 pending; bounded isolated testing authorized |

## Hardware and model custody

Ryzen7PRO8840HS:8cores/16logical processors,32GBhostRAM,15.29GiBDocker VM.
Radeon780M integrated graphics, driver32.0.31035.1003. Windows reports512MiB
adapter allocation; the total shared GPU budget was not measured. WSL has
`/dev/dxg`; the Ollama container has no GPU mapping and reports CPU execution.
Radeon780M is absent from the documented Windows ROCm list; Docker Desktop's
documented Windows GPU passthrough uses NVIDIA. Native Vulkan feasibility is
untested. Do not install drivers or change host settings.

Preserve all5copies: Docker1B/12B/EmbeddingGemma and Windows1B/4B. The separate
Windows Ollama knowledge-service dependency remains intact.

## Source, tests and next actions

Initial scheduling candidate:137tests plus73subtests passed. Later targeted
admission/coaching/API/observer run:36tests plus63subtests passed. Status history
and authority:17passed. Runs overlap; do not sum them as unique tests.

PR467 is a draft candidate. Production backend remainsf37673b4, interface60c5c11a,
coachingb360da9. DB pause enforcement is separately installed. Canonical main
was rechecked atf37673b4. Do not claim the new source was deployed.

Continue Phase2 with isolated, explicitly authorized lightweight, embedding and
deep tests while production background stays paused. Benchmark threads4/6/8
sequentially; measure CPU-seconds, quality and responsiveness. Qualify actual
ECO settings before rollout. Do not automatically resume unrelated producers.

Local WIP `app/single_flight.py` and the `cancel_in_connection` helper are
saved, unintegrated and untested as a combined feature. Preserve/review
them before use. They are not deployed global deduplication.

## Evidence and rollback

Local folder: `C:/Users/Admin/Documents/ABEX/reports/infrastructure-optimization/20261028T071443Z/`.
Read `runtime-compliance-after-pause.json`, `active-to-idle-comparison.json`,
`live-admission-enforcement-probe.json`, `live-background-admission-change.json`
and both finite time-series files. No prompts or credential values are exported.
Previous active guidance and supervisor are backed up there.

Preserve the pause when reverting candidate source: its additive DB control is
compatible with legacy dispatchers. Do not restore automatic pause clearing or
drop the trigger as routine rollback. No data/model restoration is needed.
Connection reconstruction and Windows supervisor reload passed; an actual
Docker-container restart acceptance test was not performed.
