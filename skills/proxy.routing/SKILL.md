---
id: proxy.routing
name: Model and tool proxy routing
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a15, a16]
dependencies: [tools.discovery]
---

# Model and tool proxy routing

Route model and tool requests through governed proxies that enforce tier
eligibility and an allow-list, and log the routing decision.

## Interface

- Inputs: request, tier eligibility, allow-list.
- Outputs: routing decision, backend, policy result.
- Errors: deny unknown agents, unknown tools, and off-list destinations.

## Qualification

Tests must cover deny-by-default, eligibility, and deterministic routing.
