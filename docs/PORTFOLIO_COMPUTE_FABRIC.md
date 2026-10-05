> Portfolio status is recorded in [STATUS.md](../STATUS.md). This document describes this repository only; current runtime and deployment claims require evidence from their owning domains.

# PRIME Portfolio Compute Fabric

PRIME is the cognitive consumer/coordinator for the shared Portfolio Event v1 contract. Its durable event inbox is idempotent by `event_id`; event receipt never grants execution authority.

The fabric connects Portal knowledge, VELYQUA observations, Game Platform simulation evidence and Authority Engine publication evidence while preserving source ownership and evidence maturity.

Next runtime adapters should translate accepted events into bounded cognitive plans, semantic graph updates and governed memory candidates. Those derived artifacts must retain source `event_id`, correlation and provenance.
