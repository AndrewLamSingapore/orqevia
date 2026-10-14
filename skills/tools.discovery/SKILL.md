---
id: tools.discovery
name: Technical tool discovery and orchestration
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a15, a16, a17]
dependencies: []
---

# Technical tool discovery and orchestration

Discover and describe available technical tools through a registry, without
granting execution rights. Discovery is descriptive until a tool is qualified.

## Interface

- Inputs: capability need, eligible tool set.
- Outputs: candidate tools, eligibility, qualification status.
- Errors: never execute or grant a tool merely because it was discovered.

## Qualification

Tests must cover registry integrity, eligibility, and no-tool-grant on discovery.
