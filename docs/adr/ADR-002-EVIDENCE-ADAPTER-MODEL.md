# ADR-002: Use the adapter model for Evidence Product v0.1

Decision: keep Golden PRIME provenance canonical and map it through `app/prime_evidence_adapter.py` into the portable envelope.

Reason: it preserves the qualified production boundary, makes the portable layer independently usable, and permits semantic-equivalence testing without a risky deep migration. A shared core may be considered only after equivalent identity, authority, timestamps, artifacts, verification, contradictions and history are proven across representative production-safe cases.
