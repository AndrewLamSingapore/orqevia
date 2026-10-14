# PLAN.md — ORQEVIA continuous skills-update orchestration

`PLAN.md` is the plan and control specification. It is not a substitute for
executable orchestration; the executable work is carried out by the modules it
references (`app/skill_router.py`, `app/academy.py`, `app/uief.py`,
`app/engineering_loop.py`, `app/action_harness.py`, `app/host_guard.py`).

## Authority and approval checkpoints

1. Advisory and read-only steps run autonomously within their budgets.
2. Consequential steps require owner approval through the existing effect-based
   path (`app/host_guard.py`, `app/routing_policy.py`).
3. Merging to `main`, deployment, cloud provisioning, and certification are
   separately gated and are never implied by local orchestration.

## Prioritised backlog

1. Reconcile the local clone with GitHub `main` (coaching PRs #285/#286 are
   merged remotely but absent from local `main`).
2. Qualify the existing coaching components in `app/agent_coaching.py` and
   `app/coaching_observation.py` (reuse, do not duplicate).
3. Wire the 15-dimension UIEF (`app/uief.py`) to existing evaluation and
   coaching state.
4. Wire the 10 training rooms (`app/academy.py`) to the coaching store.
5. Add the shared deductive/inductive/abductive reasoning interfaces.
   (In progress: `app/hyper_inference/` delivers the engine/channel/proxy/matrix
   registries and the adaptive router; `tests/test_hyper_inference.py` is green
   but the fabric is still `DRAFT_CANDIDATE`, not Gate A/B qualified.)
6. Add the controlled internet research gateway.
7. Add bounded proactive execution and technical tool discovery.
8. Qualify multi-matrix evidence and multi-proxy routing.
9. Prepare DigitalOcean readiness (runtime, storage, secrets, monitoring).
10. Prepare the independent Azure L7 evidence-export surface.

## Dependency-aware execution order

reasoning interfaces → evidence matrices → tool discovery → proxy routing →
internet gateway → bounded autonomy → Academy → UIEF → skills governance →
orchestration → operational readiness. Each item is scheduled only when its
listed prerequisites are qualified.

## Hyper-Inference Fabric next actions

1. Qualify `hyper-inference.fabric` through Gate A (interfaces, negative and
   security tests, error handling) and Gate B (integration and recovery).
2. Wire the fabric into `app/cognitive_orchestrator.py` and `app/skill_router.py`
   as an advisory selection layer without bypassing `app/routing_policy.py`.
3. Add the remaining Section 77 engine/channel specialisations (tree and graph
   search over persistent evidence, retrieval and simulation hooks) only where
   measured benefit justifies them.
4. Publish the versioned capability and evaluation records and request owner
   activation; activation remains a separate, owner-approved change.

## Agent assignment methodology

- Assign work to the registered owner agents declared in
  `skills/manifest.json` and `config/agent_registry.json`.
- Advisory roles default to proposal-only; restricted roles (a16, a17, a29)
  keep their required-for-execution flag.
- Never bind execution authority from the registry alone.

## Training and evaluation scheduling

- Academy training runs in the 10 rooms on the declared `retention_days` cadence.
- UIEF evaluation runs only on unseen scenarios; training and assessment data
  stay in separate stores.
- A scorecard requires a measured sample for every one of the 15 dimensions.

## Durable workflow state

- Persist attempt, feedback, assessment, and scorecard records with UTC
  timestamps and version identifiers.
- Preserve historical records additively; do not rewrite failed receipts.

## Retry, recovery, regression and rollback

- Retry only idempotent, budget-bounded steps; no unbounded loops.
- On failure, preserve the receipt, isolate the affected component, and run the
  relevant regression tests before retrying.
- Rollback restores the prior qualified manifest and `SKILL.md` versions and
  references preserved before/after evidence.

## Resource budgets

- Academy rooms enforce per-room attempt, token, and wall-clock budgets.
- Orchestration uses no unbounded parallelism; safe parallelism is used only
  for independent work with deterministic integration.

## Owner-visible progress reporting

Each milestone reports completed work, verified tests, failed tests, blockers,
current phase, remaining work, and next authorised actions. Planning is never
reported as implementation, and local tests are never reported as production
validation.
