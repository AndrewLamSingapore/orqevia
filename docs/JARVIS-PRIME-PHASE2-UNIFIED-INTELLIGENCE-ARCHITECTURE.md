# JARVIS PRIME Phase 2 Unified Intelligence Architecture

Status: `CANDIDATE / NOT DEPLOYED`

Parent: `jarvis-prime-golden-gen1-20260926`
Production mutation: prohibited by this artifact.

## Purpose

Phase 2 adds one durable control plane to PRIME Architecture v1. It does not add a second PRIME, a new production authority, or an agent that can grant itself capabilities. The control plane binds objective continuity, scoped context, problem-solving evidence, qualified lessons, and shadow predictions to server-owned records.

## Invariants

- Golden Gen 1 remains the rollback and production baseline until a governed promotion completes.
- Owner pause, stop, cancel, and scope decisions are enforced before work continues.
- Objective controls use state/version compare-and-set; a delayed completion cannot overwrite an Owner stop. Completion validates anchored event/evidence integrity, rechecks bound evidence, changes state and appends the completion event inside one immediate database transaction.
- Member context and objectives never inherit Owner authority.
- Model output, retrieved text, lessons, hypotheses, and forecasts grant no authority.
- Consequential effects require externally verified receipts and stable operation IDs.
- Completion requires evidence references for every declared success criterion.
- Repeated equivalent attempts without new evidence force replanning.
- Predictions are immutable, time-bounded shadow records with a baseline and explicit uncertainty.
- No candidate record may be represented as production evidence.
- External evidence becomes verified only through a stable, host-supplied verifier bound to canonical issuer policy. The kernel default is deny; model or caller assertions cannot substitute for host verification.
- Verified attestations bind their identity and expiry inside the host-verified body, are expiring and one-time. Consequential effects bind the exact verified payload digest and cannot reuse evidence across different effects; the primary effect ledger independently preserves this invariant if an auxiliary use index is lost or altered.

## Unified state model

`phase2_objectives` stores the original objective, criteria, constraints, authority envelope, durable checkpoint, next admissible action, version and integrity digest. Events, attempts, effects, context, hypotheses, lessons and predictions are separate append-oriented records.

The checkpoint carries facts, unknowns, a problem graph, plan, completed work, failed approaches, artifacts, dependencies, verification references and the next admissible action. Optimistic version checks reject stale writers. A restart reopens the same SQLite state without reconstructing intent from model prose.

The host owns verifier configuration and durable key/issuer identity. Phase 2 stores the validated attestation identity in the hashed primary evidence record and in the hash-chained objective event history as well as its use index. Evidence and effect rows reconcile to that anchored event history, so mutation or coordinated row/index deletion is detected and cannot permit replay. Effect records are wholly integrity-bound, and a verified effect requires a host-verified observation. Phase 2 does not generate an ephemeral trust root or expose a public self-attestation path. A host that supplies no verifier fails closed.

## Context Fabric

Context is classified by scope (`OWNER_PRIVATE`, `MEMBER_PRIVATE`, `APPLICATION`, `SYSTEM`, `GLOBAL`), epistemic class, temporal state, source/version, source authority, verification reference and supersession. Compilation:

1. enforces caller and objective scope;
2. removes superseded/retired records;
3. ranks relevance, verified status and recency;
4. marks stale or future observations;
5. surfaces unresolved contradictions;
6. treats retrieved instructions as data and explicitly grants them no authority.

## Problem solving and learning

Hypotheses remain `OPEN`, `SUPPORTED`, `REJECTED`, or `UNKNOWN` based on recorded support and contradiction. Sunk cost cannot preserve a contradicted hypothesis. Lessons remain hypotheses unless they reference at least three distinct host-verified `OUTCOME` records from independent objectives whose hashes and anchored events validate, with applicability limits and counterexample checks. Qualification additionally requires a single-use host receipt bound to the exact lesson digest, applicability, outcome IDs and counterexample result; authentic but irrelevant evidence cannot qualify arbitrary or contradictory lessons. Caller-supplied booleans or provenance strings are not verification. Qualified lessons still grant no authority.

## Predictive core

Predictions are shadow-only in Phase 2. Each binds an as-of time, target, horizon, method, evidence IDs/times, feature snapshot, forecast, uncertainty, assumptions, scenario, simple baseline, calibration version and integrity digest. Future-data leakage, absent baselines, premature resolution and post-hoc mutation fail closed. Predictions cannot trigger production actions.

Prediction creation and resolution are full-record integrity-bound and anchored to the objective event chain. Snapshot and completion reconcile prediction rows to creation/resolution events, so alteration or deletion fails closed, including after restart.

## Reused Golden capabilities

Phase 2 reuses canonical identity/authority, 21-agent registry, governed memory/RAG, offline queues, workflow engine, provenance separation, local inference, PWA and recovery topology. It introduces no new agent role and no database migration to the commissioned production volume.

## Qualification and promotion

Candidate qualification requires focused, held-out, adversarial, mutation, restart, context-loss, authority, privacy, idempotency, prediction and full canonical regression evidence. A frozen candidate must bind source SHA, artifacts, tests, security evidence, migration requirements and rollback. Production promotion additionally requires a governed change decision, immutable image, runtime receipt, independent verification, read-back acceptance and only the minimum physical requalification justified by changed dependencies.

Wuhan/mainland-China remains `PHYSICAL_VERIFICATION_PENDING`; VELYQUA physical telemetry remains `PARKED`. Neither can be converted into synthetic evidence.
