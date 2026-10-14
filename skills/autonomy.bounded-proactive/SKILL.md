---
id: autonomy.bounded-proactive
name: Bounded proactive autonomy
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a15, a16, a17, a19]
dependencies: [research.internet-gateway]
---

# Bounded proactive autonomy

Self-initiated work within declared budgets and the effect-based approval
boundary. Consequential actions always request owner approval.

## Interface

- Inputs: trigger, objective, budget, approval digest.
- Outputs: bounded action plan, executed advisory steps, approval requests.
- Errors: stop and escalate on budget exhaustion or out-of-scope effect.

## Qualification

Tests must cover budget enforcement, approval escalation, and no self-escalation.
