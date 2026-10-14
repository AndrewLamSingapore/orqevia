---
id: reasoning.deductive
name: Deductive reasoning
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a01, a02, a04]
dependencies: []
---

# Deductive reasoning

Apply valid rules from explicit premises to necessary conclusions. Record the
rule, the premises, and the conclusion so an auditor can re-derive the result.

## Interface

- Inputs: premises, applicable rules, constraints.
- Outputs: conclusion, derivation steps, edge cases, uncertainty notes.
- Errors: fail closed on missing premises or conflicting rules; never invent a
  premise.

## Qualification

Tests must cover valid deduction, missing premise, conflicting rule, and
no-execution. Qualification requires passing tests and preserved receipts.
