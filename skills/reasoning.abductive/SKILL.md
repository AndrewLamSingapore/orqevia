---
id: reasoning.abductive
name: Abductive reasoning
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a02, a04, a19]
dependencies: [reasoning.deductive, reasoning.inductive]
---

# Abductive reasoning

Propose the best available explanation for an observation, rank alternatives,
and state what evidence would discriminate between them.

## Interface

- Inputs: observation, candidate explanations, prior evidence.
- Outputs: ranked explanations, likelihood notes, discriminating tests.
- Errors: never present the highest-ranked explanation as confirmed fact.

## Qualification

Tests must cover ranking, alternative preservation, and no-fabrication.
