# JARVIS PRIME Operational Baseline v1.0

Status: **CANDIDATE — NOT FROZEN / NOT PRODUCTION-VALIDATED**
Owner: Lam / AndrewLamSingapore

This baseline becomes FROZEN only when deployed reality, canonical SSOT and retained acceptance evidence agree on the same source/image/runtime revision.

## Canonical architecture

- Registry: cognitive identities and scope.
- Compute Profile: measured capacity and routing envelope.
- TAP / Stable Spine: sole positive execution authority (PDP).
- Harness: policy enforcement point (PEP).
- Executor: side-effect boundary.
- Event/Decision Ledger: durable evidence.
- FAILSAFE: independent negative-control/containment boundary.

Invariant: cognitive breadth, compute depth, execution authority and containment authority remain independent.

## Closure gates

### G1 — SSOT freshness and source/deployment alignment
PASS only when `governance/operational-manifest.json` is CURRENT under its freshness rule, source/release/runtime drift is zero or explicitly accepted, and Dell `JARVIS.cmd status` is post-update accepted.

Current assessment: **FAIL — manifest is STALE and verification expired.**

### G2 — Agent Registry reconciliation
PASS only when canonical lowercase registry, legacy migration map, runtime projection and public projection agree; retired identities fail closed; no undocumented agent identity can receive execution authority.

Current assessment: **PARTIAL — registry v1.1 and migration map exist; live runtime/public reconciliation must be re-proven.**

### G3 — TAP / Harness authority boundary
PASS only when valid, expired, revoked, replayed, modified, wrong-scope, wrong-agent, policy-change, restart, ledger-loss and revocation-under-load paths are proven.

Current assessment: **PARTIAL — substantial Harness tests exist; operational/adversarial acceptance remains required.**

### G4 — FAILSAFE
PASS only when FAILSAFE is integrated into every consequential executor path and all frozen FAILSAFE invariants pass on Dell/ABEX.

Current assessment: **FAIL — standalone v0 primitive added; PEP/Executor integration and runtime proof pending.**

### G5 — ABEX Compute Profile v1
PASS only after the frozen benchmark protocol is executed against the actual host/runtime/model/quantization/power/cooling configuration and publishes measured normal ceiling, burst ceiling, memory reserve, thermal limit, tier limits, overflow trigger and fallback.

Current assessment: **FAIL — commissioning measurements pending.**

### G6 — Autonomous restart and observability
PASS only when reboot/startup, health, tunnel/connector where required, ledger recovery and operator status work without manual repair and are evidenced.

Current assessment: **REVERIFY — prior evidence expired.**

### G7 — Release acceptance
PASS only when CI, stable-spine, SSOT-live and release-acceptance gates are green for the exact baseline commit/image and the Dell runtime reports that same accepted release.

Current assessment: **PENDING.**

## Freeze rule

Do not label this baseline `FROZEN`, `PRODUCTION_VALIDATED`, or `COMPLETE` until G1–G7 all PASS. A published container image, green unit tests, or successful process startup alone is insufficient.

## Required final evidence record

Record exact source commit, release/image digest, Dell runtime revision, registry version/count, TAP policy version, FAILSAFE generation/state, benchmark environment metadata/results, CI run IDs, runtime acceptance timestamp, and unresolved exceptions (must be empty or explicitly owner-accepted).
