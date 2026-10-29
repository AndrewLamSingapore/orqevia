# ABEX Resource Guardian - proposed implementation and budget

29 October 2026. Authority: the Owner's Resource Guardian mission and
[Intelligent Efficiency Doctrine](../INTELLIGENT_EFFICIENCY_DOCTRINE.md).
This candidate extends PR 467's saved coordinator work. Production remains
unchanged and ordinary background inference remains paused, generation 0.

## Measured starting point

The read-only audit found an AMD Ryzen 7 PRO 8840HS (8 cores, 16 logical CPUs),
32 GiB installed DDR5-5600, 31.33 GiB Windows usable RAM, and a 15.29 GiB Docker
VM exposing 16 CPUs. The Radeon 780M reports a 512 MiB dedicated allocation;
its total shared memory budget and compute acceleration were not established.
The inference container has no GPU mapping. The 1 TB NVMe reports Healthy;
approximately 653 GiB is free. Detailed SSD reliability and temperature sensors
are unavailable to this session. Unknown sensors must remain unknown.

Sixteen half-second samples observed 23.03% mean / 45.7% peak CPU, at least
16.63 GiB available Windows memory, and about 21 MiB pagefile use. This short
sample is not a saturation or thermal qualification. Five certificate-verified
HTTPS health requests returned READY in approximately 2.11-2.16 seconds; that
latency has not been attributed to computation.

There are nine running service containers and 21 logical agent identities.
Existing telemetry already samples Windows once per minute. Existing durable
compute state already supplies atomic claims, priorities, leases, idempotency,
per-agent concurrency, cloud authorization, costs, retries and cancellation.
GitHub Actions runs on remote runners unless a workflow explicitly selects a
self-hosted runner. Local browser/build/test commands still consume this PC.

Raw audit evidence is retained locally under
`reports/resource-guardian-20261029/` in the ABEX workspace. No software was
installed and no host configuration changed during the audit.

## Components and authority

1. Extend the existing host sampler with optional GPU, pagefile/commit, disk and
   thermal observations. Keep the same scheduled invocation and receipt. Never
   invent zero for unavailable sensors or require additional monitoring software.
2. A small deterministic policy module combines that fresh host receipt with an
   immediate Linux memory observation, the measured hardware envelope and the
   selected mode. It returns admission/defer decisions and uncertainty.
3. The existing `JobQueue` evaluates those decisions inside its existing SQLite
   claim transaction, before any local inference dispatch. Both named/direct
   and worker claims use the same decision. Cloud selection, classification,
   authorization and spending ceilings retain their existing authority.
4. A local command wrapper can use the same database and policy for expressly
   registered build/test/tool processes. It reserves capacity atomically, starts
   only its own child, supports finite timeout/cancellation, and releases its
   reservation after the child exits. It creates no competing scheduler or queue.
5. Mode selection and aggregate outcome estimates persist in additive tables in
   the existing database. No prompts, private source, credentials or raw model
   outputs enter the resource journal. Estimates describe observations and do
   not automatically grant permissions or increase qualified concurrency.

No new service container, daemon, database, broker or deployment queue guard is
needed. Existing unregistered Windows programs and remote runners are observed;
they are not silently suspended, terminated or enrolled in a new control plane.

## Operating modes and initial limits

The configuration explicitly records actual CPU/RAM capacity, evidence,
freshness, capacity reserves and **qualified** concurrency. Eco maps to HOME_ECO;
ULTRA_ECO remains a selectable stronger variant. Neither becomes a production
default merely because a configuration file or test exists.

| Mode | Initial policy |
|---|---|
| Eco / HOME_ECO | One heavy inference; conservative registered tool concurrency |
| Balanced | One heavy inference; independent measured tool work may progress |
| Performance | Uses the qualified ceiling, never automatically all CPU threads |
| Mission | Same physical envelope; 21 identities share bounded capacity |
| Recovery | Defers new nonessential work; preserves running work and checkpoints |
| ULTRA_ECO | One registered background tool at a time and stronger CPU reserve |

The existing one-heavy-inference / one-resident-model policy remains the
qualified ceiling. Start with one CPU-heavy build and at most two inexpensive
tool tasks in isolated tests. This is a conservative test envelope, not proof
that two arbitrary builds or 21 model processes are safe.

Provisional reserves are explicit fractions of measured capacity, with their
derivation and qualification status in the profile. They are resource-safety
policies, not request-rate limits or blanket execution restrictions. CPU busy
observations defer *new* nonessential work; memory pressure and observed thermal
limits cannot be overridden by a priority label. Unknown GPU/thermal information
does not become an invented GPU budget or an overheating-prevention claim.

The Owner background pause is read from its existing authoritative table and
can never be cleared by a mode change, completion, retry or recovery. Safe
deterministic/tool work is independent of paused background inference. Queued
waiting does not consume an execution deadline. Capacity recovery wakes the
existing work path; it does not resubmit or delete accepted work.

## Resource budget and validation

Target no additional resident process, no inference for readiness, bounded
receipts below 128 KiB, and sub-millisecond policy evaluation apart from existing
sampling/SQLite overhead. Measure actual overhead before claiming these targets.
Reuse one-minute telemetry, immediate cheap memory checks, and change-only
decision events. Do not multiply observers by the number of agent identities.

Validate deterministic pressure/unknown-sensor/stale-data cases, concurrent
claims from independent connections, pause persistence, per-agent isolation,
tool process timeout and cancellation, duplicate execution prevention, mode
persistence, conservative recovery, and existing queue regressions. Then run
small, progressively bounded local tool workloads sequentially and compare
CPU seconds, peak RAM, throughput and HTTPS responsiveness against baseline.
Do not perform uncontrolled stress, 21 heavyweight generations, driver changes,
firmware changes or paid remote delegation.

## Deployment, permissions and rollback

Implementation and isolated tests need ordinary workspace access and installed
Python dependencies. Changing the protected SYSTEM sampler or restarting a
production component requires a concrete release decision and any necessary
Windows administrator action. Prepare exact files, checksums, tests and rollback
first. This document does not authorize a production restart or pause release.

The feature is optional and off when no resource profile is configured. Rollback
removes that opt-in and restores the prior source/collector files. Additive
observations remain retained; never remove the durable Owner pause trigger,
delete queues, restore stale databases, or discard outputs to roll back policy.

Report IMPLEMENTED, TESTED, DEPLOYED, ENFORCED and RUNTIME VERIFIED separately.
Broad production validation, thermal protection with unavailable sensors, and
control of unregistered applications cannot be inferred from a candidate test.
