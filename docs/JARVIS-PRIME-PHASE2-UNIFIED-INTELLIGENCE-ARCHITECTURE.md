# JARVIS PRIME Phase 2 Unified Intelligence Architecture

Status: `CANDIDATE / NOT DEPLOYED`

Parent: `jarvis-prime-golden-gen1-20260926`
Production mutation: prohibited by this artifact.

## Purpose

Phase 2 adds one durable control plane to PRIME Architecture v1. It does not add a second PRIME, a new production authority, or an agent that can grant itself capabilities. The control plane binds objective continuity, scoped context, problem-solving evidence, qualified lessons, and shadow predictions to server-owned records.

## Invariants

- Golden Gen 1 remains the rollback and production baseline until a governed promotion completes.
- Owner pause, stop, cancel, and scope decisions are enforced before work continues.
- Member context and objectives never inherit Owner authority.
- Model output, retrieved text, lessons, hypotheses, and forecasts grant no authority.
- Consequential effects require externally verified receipts and stable operation IDs.
- Completion requires evidence references for every declared success criterion.
- Repeated equivalent attempts without new evidence force replanning.
- Predictions are immutable, time-bounded shadow records with a baseline and explicit uncertainty.
- No candidate record may be represented as production evidence.

## Unified state model

`phase2_objectives` stores the original objective, criteria, constraints, authority envelope, durable checkpoint, next admissible action, version and integrity digest. Events, attempts, effects, context, hypotheses, lessons and predictions are separate append-oriented records.

The checkpoint carries facts, unknowns, a problem graph, plan, completed work, failed approaches, artifacts, dependencies, verification references and the next admissible action. Optimistic version checks reject stale writers. A restart reopens the same SQLite state without reconstructing intent from model prose.

## Context Fabric

Context is classified by scope (`OWNER_PRIVATE`, `MEMBER_PRIVATE`, `APPLICATION`, `SYSTEM`, `GLOBAL`), epistemic class, temporal state, source/version, source authority, verification reference and supersession. Compilation:

1. enforces caller and objective scope;
2. removes superseded/retired records;
3. ranks relevance, verified status and recency;
4. marks stale or future observations;
5. surfaces unresolved contradictions;
6. treats retrieved instructions as data and explicitly grants them no authority.

## Problem solving and learning

Hypotheses remain `OPEN`, `SUPPORTED`, `REJECTED`, or `UNKNOWN` based on recorded support and contradiction. Sunk cost cannot preserve a contradicted hypothesis. Lessons remain hypotheses unless they have repeated verified outcomes, provenance, applicability limits and counterexample checks. Qualified lessons still grant no authority.

## Predictive core

Predictions are shadow-only in Phase 2. Each binds an as-of time, target, horizon, method, evidence IDs/times, feature snapshot, forecast, uncertainty, assumptions, scenario, simple baseline, calibration version and integrity digest. Future-data leakage, absent baselines, premature resolution and post-hoc mutation fail closed. Predictions cannot trigger production actions.

## Reused Golden capabilities

Phase 2 reuses canonical identity/authority, 21-agent registry, governed memory/RAG, offline queues, workflow engine, provenance separation, local inference, PWA and recovery topology. It introduces no new agent role and no database migration to the commissioned production volume.

## Qualification and promotion

Candidate qualification requires focused, held-out, adversarial, mutation, restart, context-loss, authority, privacy, idempotency, prediction and full canonical regression evidence. A frozen candidate must bind source SHA, artifacts, tests, security evidence, migration requirements and rollback. Production promotion additionally requires a governed change decision, immutable image, runtime receipt, independent verification, read-back acceptance and only the minimum physical requalification justified by changed dependencies.

Wuhan/mainland-China remains `PHYSICAL_VERIFICATION_PENDING`; VELYQUA physical telemetry remains `PARKED`. Neither can be converted into synthetic evidence.
