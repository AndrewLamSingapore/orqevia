---
id: skills.governance
name: Skills registry governance and versioning
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a26, a29]
dependencies: []
---

# Skills registry governance and versioning

Govern the skills registry with versioning, approval and rollback. A skill is
not qualified merely because instructions are present.

## Interface

- Inputs: manifest, skill packages, change request.
- Outputs: versioned change, qualification state, rollback reference.
- Errors: reject duplicate ids, cyclic dependencies, and self-granted activation.

## Qualification

Tests must cover manifest integrity, dependency resolution, and qualification state.
