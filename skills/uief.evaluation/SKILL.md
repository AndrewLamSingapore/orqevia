---
id: uief.evaluation
name: Universal Intelligence Evaluation Framework
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a18, a26, a28]
dependencies: [academy.training]
---

# Universal Intelligence Evaluation Framework

Fifteen-dimensional, versioned evaluation with uncertainty reporting and
security hard gates. Scorecards are computed only from measured samples.

## Interface

- Inputs: measurements for all 15 dimensions, dataset id, evaluator.
- Outputs: scorecard, hard-gate status, evidence export.
- Errors: refuse to score missing dimensions or out-of-range values.

## Qualification

Tests must cover the 15 dimensions, hard gates, uncertainty, and no-fabrication.
