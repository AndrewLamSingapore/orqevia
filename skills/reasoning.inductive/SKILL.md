---
id: reasoning.inductive
name: Inductive reasoning
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a06, a07, a12, a13]
dependencies: [reasoning.deductive]
---

# Inductive reasoning

Generalise from labelled samples while preserving sample size, coverage and
counter-evidence. Every generalisation carries an explicit uncertainty.

## Interface

- Inputs: labelled samples, coverage statement, confidence target.
- Outputs: generalisation, supporting/contradicting samples, uncertainty.
- Errors: refuse to generalise from an empty or unlabelled sample set.

## Qualification

Tests must cover generalisation, small-sample refusal, and uncertainty bounds.
