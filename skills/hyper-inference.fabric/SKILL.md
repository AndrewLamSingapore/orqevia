---
id: hyper-inference.fabric
name: Hyper-Inference Fabric
version: 0.1.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a01, a02, a04, a15, a16, a18, a26]
dependencies: [reasoning.deductive, reasoning.inductive, reasoning.abductive, matrix.multi-evidence, proxy.routing, uief.evaluation]
---

# Hyper-Inference Fabric

Advisory-only coordination of reasoning engines, inference channels, model/tool
proxies, intelligence matrices and the adaptive inference router. It never
grants tools, spending, release or execution authority, and it performs no
external calls.

## Interface

- Inputs: objective, agent identity, permissions, evidence, hypotheses,
  complexity class.
- Outputs: traceable route, selected channels, verification, contradictions,
  evidence requests and escalation disposition.
- Errors: fail closed on unknown engines/channels/tools, unauthorized access and
  unsatisfied constraints.

## Qualification

Tests must cover registry identity, deterministic engine/channel behaviour,
access control, contradiction detection, escalation and the twelve unseen
Academy exercises. Qualification requires passing tests and preserved receipts.
