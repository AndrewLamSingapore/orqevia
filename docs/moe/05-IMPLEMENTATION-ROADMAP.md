# Implementation roadmap and rollback

Status: UNDER IMPLEMENTATION; production acceptance outstanding.

| Priority | Work | Status | Benefit and risk |
|---|---|---|---|
| P0 | Existing-queue shared admission, ownership and timing | SOURCE IMPLEMENTED; isolated tests | Prevent submission overlap from becoming overlapping local occupancy; additive schema/recovery needs staged deployment |
| P0 | Patient coaching and stalled-progress watchdog | SOURCE IMPLEMENTED; isolated tests | Remove deployed300s coaching mismatch while keeping finite safety budgets; validate real latency and cleanup |
| P0 | Runtime compliance observer | SOURCE IMPLEMENTED; live read-only observation | Distinguish requested versus actual profile; uninstrumented counters stay unknown |
| P1 | Exact authorized single-flight and content-addressed reuse | NOT IMPLEMENTED | Avoid duplicate work; isolation, freshness and independent cancellation are mandatory |
| P1 | Agent selection evaluation and conditional delegation | Existing default-one selector; extension NOT IMPLEMENTED | Reduce unnecessary repeated contributions; avoid skipping required expertise |
| P1 | Narrow1B versus12B quality benchmark | PLAN ONLY | Possible lower-cost classification; switching overhead and errors may erase savings |
| P2 | Optional cloud reasoning escalation | Existing adapters; new route NOT IMPLEMENTED | Higher capability for selected tasks; disclosure, pricing and quality require verification |
| P3 | Native MoE test | NOT AUTHORIZED/NOT RUN | Optional measured comparison, no memory/quality benefit assumed |

Initial source policy: `ORQEVIA_OUTPUT_QUEUE_MODE=home_eco` opts into the existing
pool with one shared slot. Default waiting capacity64 is configurable through
`ORQEVIA_MAX_WAITING_JOBS`. Queued jobs have no short inference deadline.
Coaching uses configurable1800s active safety budget (60..7200); first-progress,
stalled-progress, persistence and total safeguards are separately represented.
These are candidate settings, not thermal or power benchmarks.

`ORQEVIA_HOME_ECO_MIN_AVAILABLE_MIB` must be calibrated before enabling the RAM
reserve. No guessed universal threshold is enabled. CPU/thermal adaptive pacing,
ULTRA_ECO/BALANCED policy comparison, model switching and caching are not delivered
by the first source milestone.

## Proposed deployment, not executed

1. Review source/CI and stage the exact commit. Record backend/coaching/collector
   image IDs, data mounts, configuration fingerprints and current active jobs.
2. Prepare a current SQLite online backup and validate its integrity without
   restoring old data over new missions.
3. Obtain specific Owner approval for controlled producer draining and the brief
   backend/coaching service transition. Broad access does not erase the explicit
   instruction against interrupting active work without that approval.
4. Finish or safely checkpoint current work. Do not cancel it merely to deploy.
5. Deploy pinned candidate backend/coaching through existing procedures; retain
   Ollama. Rebind/recreate the collector only as required by the backend namespace.
6. Verify actual requested/active mode, exact images, one physical slot, patient
   deadlines, all nine services, persistence, HTTPS and representative workloads.
7. Accept only demonstrated reliability/resource results; otherwise roll back.

Rollback: return the backend/coaching image pins and scheduling mode to their
recorded pre-change values through the same approved transition. Retain current
live data. Added nullable metadata columns are compatible with the old code;
do not drop columns or restore older databases to roll back application code.
Remove/revert the optional compliance script only if its observation is unwanted;
it makes no Docker or runtime mutations.

No deployment, production restart, model installation, driver change, cloud spend
or actual performance improvement is claimed by a source commit or test pass.
