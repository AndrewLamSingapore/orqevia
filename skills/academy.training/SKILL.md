---
id: academy.training
name: Intelligence Academy training-room interfaces
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a26, a28]
dependencies: []
---

# Intelligence Academy training-room interfaces

Ten bounded training rooms with curriculum, simulation scenarios, coaching
feedback and retention tests. Training and assessment data stay separate.

## Interface

- Inputs: room, agent, scenario, budget.
- Outputs: attempt record, feedback, retention schedule.
- Errors: enforce room eligibility and resource budgets; fail closed otherwise.

## Qualification

Tests must cover all ten rooms, agent coverage, budget enforcement and separation.
