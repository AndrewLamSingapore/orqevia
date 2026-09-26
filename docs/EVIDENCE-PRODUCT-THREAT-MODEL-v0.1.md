# Evidence Product v0.1 Threat Model

Protected properties: authoritative metadata separation, claim/evidence binding, artifact byte integrity, append history, namespace isolation, explicit verification and safe rendering.

Threats include model-authored IDs/timestamps/authority; forged references; digest substitution; ledger row rewriting; broken supersession; prompt injection inside evidence; cross-tenant reads; replay/idempotency collision; prediction presented as fact; polished narrative concealing failure; secret leakage.

Controls: trusted host adapters, canonical serialization, named digests, hash-linked append events, unique idempotency keys, namespace-bound queries, deterministic validator, inert text rendering, non-color status labels and fail-closed verification gates.

Limitations: SHA-256 integrity is not signer identity; local SQLite does not resist an administrator who rewrites both data and all hashes; the validator cannot observe external reality; clocks and identity sources remain host responsibilities; v0.1 has no PKI, distributed consensus, hosted tenancy, compliance certification or market validation.
