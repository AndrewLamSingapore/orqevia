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

Source traces, original per-role metadata and service evidence: operations/observability-recovery-20261027/agents/. See ORQEVIA_HANDOVER_CODEX_DEEPSEEK.md for exact ownership, paths, contract and next actions.
