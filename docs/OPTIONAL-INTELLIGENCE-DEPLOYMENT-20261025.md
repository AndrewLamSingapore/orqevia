# Optional intelligence integration and release

PIF and MEL are separate packages, routers, feature flags and storage tables.
They share existing registry SQLite and the established owner-scoped interface.
Neither changes the compute worker, provider routing, agent responsibility or
execution authorization. No new microservice, cloud service or mandatory model
runtime is installed. REA and MiroFish are excluded by Owner instruction; their
audit findings do not authorize repairs or integration.

The interface gateway exposes only explicit `intelligence/pif/*` and
`intelligence/mel/*` routes. Backend requests retain service authentication and
bound owner/tenant checks. The board's feature flag is independent from either
capability. Health stays available for a disabled capability. Model evidence
never grants action authority. Existing tracing captures route latency without
prompt, prediction or corpus text in telemetry.

The operations page provides explicit availability, observed-history fit,
state forecast, seeded simulation and efficiency-evidence actions. It adds no
background poller and sends one request at a time. All user-facing traffic uses
verified HTTPS. Existing private transports remain a coordinated migration
scope; this release does not claim every private hop is already TLS.

## Configure and verify

Defaults are `ORQEVIA_PIF_ENABLED=0`, `ORQEVIA_MEL_ENABLED=0`. In an existing
Compose deployment, pass each flag into the backend's environment. Enable PIF
only as `SHADOW_ONLY`; its responses retain unvalidated reliability and explicit
insufficient-data states. Enable MEL for inventory and experiment evidence;
the INT8 experiment is a controlled benchmark, so retain the current FP32 model.

1. Run mathematical, experiment, API auth/isolation and existing core tests.
2. Stage the exact image and source. Check both-disabled, PIF-only, MEL-only,
   combined and unavailable-storage cases against actual core functionality.
3. Run one observed queue fit. Check excluded-history diagnostics, chronological
   evaluation, exact model version, forecast distribution and evidence readback.
4. Import the actual benchmark's `evidence` object through the bound-owner MEL
   endpoint. Read the stored experiment and retain-baseline recommendation.
5. Test the real HTTPS operations page, trusted session refresh, fabric execution
   and receipt recovery. Record actual revision, image, timestamps and receipt
   hashes separately from source/CI success.

Use existing Compose and immutable images. Retain private configuration copies,
SQLite backup/restoration receipts, TLS mounts, models and all production writes.
Do not add queue inspection locks, deployment holds or queue guards. Spread
heavy verification and benchmarks to preserve production capacity.

## Independent rollback and monitoring

Set either capability's flag to0 and recreate only the backend through existing
Compose. Its requests return DISABLED while the other capability/core continues.
PIF's shadow model version selection is independently reversible through its
rollback API; it never changes an agent/provider assignment. MEL has no automatic
promotion, so disabling it leaves the original inference path and index intact.
Full application rollback uses the retained prior image and private environment,
recreating the collector after the backend network namespace changes. Never
restore an old database over new live writes merely to roll back application code.

Observe authenticated PIF/MEL status separately, gateway latency/errors, registry
storage availability and existing core health. PIF model metadata retains
chronological Brier/log-loss/baseline/calibration/drift diagnostics. These remain
diagnostics until representative prospective data validates operational quality.
MEL records artifact/workload hashes, CPU/wall time, peak process memory and cold/
warm repeat variability. Dollars/energy were not measured. Do not claim an end-
to-end production speedup, zero accuracy loss, or compatible NVIDIA sparse kernels.

Deletion cleanup is separately BLOCKED by automatic approval review ("blocked
by policy"). The unused REA package is inactive, not integrated, and not deleted.
