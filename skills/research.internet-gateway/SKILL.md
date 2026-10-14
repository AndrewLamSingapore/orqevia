---
id: research.internet-gateway
name: Controlled internet research gateway
version: 1.0.0
status: DRAFT_CANDIDATE
qualified: false
activation: advisory_only
owner_agents: [a06, a07, a09]
dependencies: []
---

# Controlled internet research gateway

Agent-initiated research through an allow-listed gateway. Every request is
classified, logged, and subject to the denial policy before leaving the host.

## Interface

- Inputs: bounded research question, allow-list, classification.
- Outputs: retrieved evidence with source labels and retrieval metadata.
- Errors: fail closed on unclassified or non-allow-listed destinations.

## Qualification

Tests must cover allow-list enforcement, denial, logging, and secret hygiene.
