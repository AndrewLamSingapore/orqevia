---
id: orchestration.plan
name: Continuous skills-update orchestration
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a01, a02, a15, a26]
dependencies: [skills.governance, uief.evaluation]
---

# Continuous skills-update orchestration

Coordinate the skills backlog with dependency-aware execution, scheduling,
approval checkpoints, retry, recovery and rollback as specified in PLAN.md.

## Interface

- Inputs: backlog, dependency graph, budgets.
- Outputs: scheduled work, approval checkpoints, progress report.
- Errors: do not schedule work with unqualified prerequisites.

## Qualification

Tests must cover dependency ordering, approval gating, and bounded retry.
