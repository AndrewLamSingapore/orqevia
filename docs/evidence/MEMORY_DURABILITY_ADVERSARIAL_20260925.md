# Governed Memory/RAG Durability — Adversarial Evidence

Status: **CANDIDATE — isolated only, not deployed**

## Genuine verifier rejection preserved

The first duplicate-write implementation treated every byte-identical write as an automatic replay. Existing supersession tests rejected it because separate intentional writes must remain separate historical events. Root cause: idempotency was inferred from content instead of supplied by the request boundary.

The repair adds an explicit unique `write_request_id`. Only retries carrying the same identifier deduplicate; separate writes retain supersession history.

## Hardened boundaries

- Memory records carry an integrity digest covering value, provenance, temporal state, scope and write-request identity.
- Reopen validates enum, JSON and digest integrity before returning or ranking a record.
- RAG retrieval recomputes content digests and fails closed on tampering.
- Optional retrieval age bounds exclude stale documents.
- `BEGIN IMMEDIATE` plus compare-and-swap `expected_current_id` serializes concurrent replacements and rejects stale writers.
- Failed or rejected writes preserve the prior CURRENT record.
- Retrieved content remains non-authoritative and non-executable.

No production database, identity, memory or runtime was accessed or modified.
