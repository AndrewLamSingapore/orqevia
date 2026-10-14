---
id: hyper-inference.fabric
name: Hyper-Inference Fabric
version: 0.1.0
status: QUALIFIED
qualified: true
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

Qualified on 2026-10-14 by owner approval after the ORQEVIA v1 CI quality check
passed for pull request #312. Evidence: 31 deterministic fabric unit and
integration tests, the 4-test fast 21-agent acceptance gate, the 15-dimension
UIEF benchmark over the twelve unseen Academy exercises, and the passing
`quality`, `isolated-verifier`, and `status-authority` checks. Activation
remains `advisory_only`: this skill still grants no tools, spending, release or
execution authority.
