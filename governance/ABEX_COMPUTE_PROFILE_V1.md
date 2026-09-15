> Portfolio authority: [one current JARVIS SSOT](https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json). This document describes this repository only; it cannot override the canonical architecture or establish live deployment status.

# ABEX Compute Profile v1 — Commissioning Record

Status: **PENDING MEASUREMENT**
Protocol baseline: `jarvis.compute-profile.benchmark-protocol.v1`

This record must be populated from the actual ABEX host. No capacity number may be inferred from architecture or prior provisional concurrency.

## Environment metadata required

CPU; RAM; storage; GPU/NPU; OS/build; drivers; runtime; model names/versions; quantization; power mode; cooling configuration; ambient temperature; date/time/operator; source commit; container/image digest.

## Phases

0. Environment baseline and explicit pass/fail bounds.
1. Single-worker characterization across nano/mini/flagship-equivalent local tiers.
2. Scaling curve: 1 worker upward until degradation boundary.
3. Sustained load and thermal stability.
4. Mixed workload realism using fixed `workload-corpus.v1`.
5. Scheduler pressure: preemption, starvation, failure/recovery, overflow trigger, TAP revocation under load, FAILSAFE freeze under load, overflow failure modes.

## Metrics

For every phase retain latency distribution, output tokens/s, success/error rate, RAM/VRAM reserve, CPU/GPU utilization, temperature, throttling evidence, queue wait, cancellation/revocation latency and recovery behavior.

## Publication fields

- normal_concurrency_ceiling: PENDING
- burst_concurrency_ceiling: PENDING
- minimum_memory_reserve: PENDING
- thermal_limit: PENDING
- nano_tier_limit: PENDING
- mini_tier_limit: PENDING
- flagship_tier_limit: PENDING
- cloud_overflow_trigger: PENDING
- scheduler_fallback: PENDING
- failsafe_freeze_latency_under_load: PENDING
- tap_revocation_latency_under_load: PENDING

## Acceptance rule

Publish Compute Profile v1 only after all phases have retained evidence and the normal ceiling includes safety margin below the observed degradation boundary. Material changes to models/quantization/runtime/RAM/GPU-NPU/drivers/cooling/power mode require rebenchmark or documented impact assessment according to the frozen protocol.
