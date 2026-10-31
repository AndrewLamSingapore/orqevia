# Intelligent Efficiency Doctrine

Owner directive, 28 October 2026. Permanent scope: all agents, missions,
services, workflows, automations, development and production operations.

**Maximum useful output. Minimum necessary resource consumption. Zero avoidable waste.**

ABEX is a patient home mini PC production environment. Correctness, security,
reliability and preservation of completed work come first. Protect Windows
responsiveness, system stability and recoverability. Optimize useful work while
it is running; idle CPU alone is not production acceptance.

## One current direction

This doctrine supersedes conflicting earlier throughput-first, always-on,
exclusive-model, always-largest and automatic-pause-clearing instructions.
Compatible Owner security, HTTPS, data-preservation and authorization rules
remain effective. Earlier reports remain historical evidence. Avoid competing
policy copies: this document is canonical; model policy and runbooks specialize
it and must link here.

## Before computation

Establish necessity, existing completed/in-flight work, authorization and
freshness. Prefer deterministic processing, structured queries and validated
existing evidence before generation. Coalesce only genuinely equivalent eligible
requests. Reuse embeddings and content-addressed intermediates when inputs,
permissions, model/prompt versions and freshness remain compatible. Preserve
independent verification; do not combine distinct authorized missions.

Choose a qualified capability for the task: deterministic software, EmbeddingGemma,
validated lightweight Gemma3 1B, justified deep Gemma3 12B or another approved
capability with demonstrated benefit. No model/provider has exclusive authority.
Keep capabilities available on demand without permanent inference or residency.
An unsupported quality downgrade is not an efficiency improvement.

## Coordinated, patient work

The primary deployment model is multiple purpose-driven service containers,
under the [permanent architecture decision](ARCHITECTURE_V1.md). Preserve service
isolation and independent recovery; one logical coordinator does not mean one
giant application. Additional containers require documented need. Consolidation
requires measured benefit and explicit Owner approval. Preserve21logical agents
on shared infrastructure and keep Ollama independently governed.

Use existing durable admission infrastructure. Maintain fair opportunities,
anti-starvation, staggered background work, bounded retries, cancellation and
recoverable checkpoints where beneficial. Separate queue waiting, loading,
inference, tools and persistence. Do not impose a short background wall deadline
that expires during legitimate waiting or progressing execution.

Keep one heavyweight inference and one resident model initially. Investigate GPU
feasibility and measure CPU-thread, context, residency and memory behavior before
tuning. Resource thresholds must follow actual hardware/workload measurements.
Monitoring must remain lightweight and must not generate inference for readiness.

## Production profiles and pause authority

HOME_ECO becomes the production default **after implementation, qualification,
deployment and runtime verification**. ULTRA_ECO remains selectable for stronger
conservation. Profiles must be observable, persistent and reversible. Do not
equate a label or unit-test pass with enforced production behavior.

The current explicit Owner background pause remains active. No job completion,
successor creation, cleanup, supervisor or restart may clear it. Only a new
explicit Owner resume instruction authorizes normal autonomous production
admissions. Bounded isolated tests are authorized without releasing unrelated
background work. A paused system is a protected baseline, not the final design.

## Acceptance and prevention

For material changes record functional quality, CPU-seconds, RAM/headroom,
model calls/tokens, duplicate work prevented, queue/execution timing, persistence,
recovery, responsiveness, security and useful benefit relative to cost. Compare
equivalent workloads and preserve failures. Do not double-count avoided work,
claim energy/thermal savings without sensors or trade correctness for a graph.

Detect duplicate/repeated work, admission drift, successor storms, starvation,
retry storms, CPU/RAM pressure, untracked inference and failure to unload when
idle. Prefer deferring new nonessential work over killing active missions.
Avoid unnecessary containers, databases, brokers, polling loops and telemetry.

## Safety and evidence

Preserve21agent identities, models, mission records, outputs, secrets, security,
the Windows Ollama knowledge dependency and rollback assets. HTTPS acceptance
uses certificate verification. Retired8081 stays retired; REA/MiroFish excluded.
Do not resume production, restart active services, destroy data, alter host
drivers/firmware or incur new external costs without the required Owner authority.

Report IMPLEMENTED, TESTED, DEPLOYED, ENFORCED and RUNTIME VERIFIED separately.
Current evidence and unfinished work are in [the engineering handover](moe/07-LIVE-PAUSE-HANDOVER.md).
Operational detail: [HOME_ECO runbook](HOME-ECO-OPERATING-POLICY.md),
[model selection](MODEL-SELECTION-POLICY.md).

The [central-coordinator and five-lane pathway](MULTI-LANE-EXECUTION-PATHWAY.md)
adds deterministic task triage, bounded statistical prediction and event-driven
coordinator coaching. These are planned implementation requirements, not claims
of deployed adaptive intelligence. Coaching must preserve Owner constraints and
use tested, versioned changes with rollback.
