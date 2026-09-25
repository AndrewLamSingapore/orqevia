# Supreme Integration Candidate — 2026-09-25

Status: **CANDIDATE ONLY — NOT DEPLOYED**

Lineage combines the remotely verified Supreme router/intelligence, governed-memory/RAG, and governed structured-output candidates in an isolated worktree. Commissioned production was not modified.

## Contract

- Trusted envelopes carry actor identity, role, scope, schema version, trace/request IDs, expiry, idempotency key, and explicit permissions.
- Models, retrieved documents, OCR/vision content, and intermediate components cannot add permissions or change role.
- Model output is untrusted until deterministic parse, schema validation, and optional semantic verification pass.
- Duplicate idempotency keys return the first recorded result.
- Expired sessions and stale requests deny; version/database ambiguity fails closed; unavailable dependencies defer rather than fabricate success.

## Negative evidence

- Member-to-Owner elevation through a model claim is denied.
- Application memory permission does not imply Owner memory permission.
- Retrieved instructions cannot grant authority.
- Malformed, extra-field, wrong-type, invalid-enum, and semantically fabricated output remains `VERIFY_REQUIRED`.
- An unverified model capability remains unavailable and cannot fall through to a tool action.

## Change-risk fingerprint

`INTEGRATION`, `MODEL`, `ROUTER`, `MEMORY`, `AUTHORITY`, `SECURITY`; no production database migration, host change, or UI deployment.

Physical Owner/Member requalification is not required because this candidate is not deployed.

