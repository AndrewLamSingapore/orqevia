# Governed Memory/RAG candidate — executed evidence

Classification: **CANDIDATE — NOT DEPLOYED**

Base: production `0ecb5803470bef2a941da31332d87702268648d6`
Branch: `feat/governed-memory-rag-20260925`

## Implemented boundaries

- Memory classes: `FACT`, `PREFERENCE`, `EVENT`, `PROCEDURE`, `INFERENCE`.
- Scopes: `OWNER_PRIVATE`, `MEMBER_PRIVATE`, `HOUSEHOLD_SHARED`, `APPLICATION`, `SYSTEM`.
- Temporal states: `CURRENT`, `HISTORICAL`, `SUPERSEDED`.
- Consequential facts require verification provenance and Owner or verified-policy authority.
- Model output may be durable only as `INFERENCE`; it cannot silently become `FACT` or `PROCEDURE`.
- Owner cannot read Member-private memory; applications cannot read or write other application, household, private or SYSTEM scopes.
- SYSTEM writes require the matching SYSTEM actor.
- Replacement is transactional: a failed insert rolls back the prior record's supersession.
- RAG documents require source, version, authority class and verified SHA-256 content digest.
- Retrieved text is marked `content_is_authority=false` and `instructions_may_execute=false`.

## Preserved verifier rejections and repairs

1. The first baseline invocation omitted isolated `PRIME_DATA_DIR`: 36 passed / 11 harness failures. The same baseline was rerun correctly: 47 passed.
2. Builder implementation supplied 14 SQL values for a 13-column table: focused result 49 passed / 6 failed. Repaired with an explicit 13-column insert: 55 passed.
3. Independent verifier direct execution could not import the repository package. Repaired by adding the repository root only in the verifier entrypoint.
4. Independent verifier then exposed unclosed SQLite handles on Windows. Python's connection context commits but does not close; every new-store connection scope now uses explicit `closing(...)`. The verifier and focused suite then passed.

These failures remain evidence that verification was independent and capable of rejecting the Builder.

## Independent verifier

Executable: `scripts/verify_governed_knowledge.py`

Result: **PASS, 5/5**

- Member-private denied to Owner.
- Application-to-SYSTEM write denied.
- Model-to-FACT promotion denied.
- Retrieval injection remains data without execution authority.
- Member-private RAG content denied to Owner.

Production touched: `false`.

## Promotion boundary

This candidate uses only isolated temporary SQLite databases. It has no migration against production, no runtime wiring, and no deployment authorization. Production memory, identities, sessions and databases remain unchanged.
