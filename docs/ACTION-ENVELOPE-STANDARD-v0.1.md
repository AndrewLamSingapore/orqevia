# Action Envelope Standard v0.1

## Purpose

Provide a portable evidence/provenance contract separating what software says happened from what a host system can support with records. It is framework-neutral and applies to AI and ordinary automation.

## Non-goals

This is not IAM, SIEM, a truth oracle, blockchain, compliance certification, a reasoning trace, an agent platform, or PRIME licensing. A valid envelope proves internal integrity and declared relationships—not the truth of an external fact the validator cannot observe.

## Canonical model

An envelope contains: schema version; system-generated action ID; objective; actor reference; authority scope/source; lifecycle timestamps/status; inputs; claims; observations; effects; artifacts; verification; provenance; and append-only relations.

Claim states: `SYSTEM_VERIFIED`, `OBSERVED`, `SOURCE_SUPPORTED`, `CALCULATED`, `INFERRED`, `PREDICTED`, `UNKNOWN`, `CONTRADICTED`, `STALE`.

Verification states: `VERIFIED`, `PARTIAL`, `UNVERIFIED`, `FAILED`, `CONTRADICTED`, `NOT_APPLICABLE`.

Relations: `SUPERSEDES`, `CORRECTS`, `INVALIDATES`, `REPLACES`, `RELATED_TO`. A relation appends; it never edits the referenced record.

## Invariants

- Claim is not evidence; model output is not system truth.
- Requested/invoked action is not an observed/verified effect.
- Agent identity is not authority.
- Artifact name is not artifact integrity; digest actual bytes.
- Prediction is not observation.
- Repeated claims are not independent corroboration.
- Completed is not verified completion.
- Test evidence is not physical evidence where physical acceptance is required.

## Deterministic receipt

Serialize UTF-8 JSON with keys sorted, no insignificant whitespace, and non-ASCII preserved. v0.1 identifies `sha256` explicitly. Hash the receipt body excluding its `digest`. Optional future signatures are separate from content integrity.

## Verification policy

`VALID` means structure, references and supplied bytes are internally consistent. `UNVERIFIED` means structurally sound but external/byte evidence is unavailable. `INVALID` means a detectable structural, reference, chain or digest failure. Missing evidence is not automatically failure; explicit negative evidence may be.

`SYSTEM_VERIFIED` observations require a structured verification object whose digest matches the canonical observation bytes and whose issuer is accepted by a host-supplied verifier. Without that verifier the observation remains unresolved and cannot support a system-verified claim or verified envelope. An arbitrary string, model statement, caller-selected issuer, matching self-computed digest, or syntactically plausible receipt is not verification. Consequential effects must bind the exact verified payload and reject replay or reuse for a different effect.

## Security and privacy

Namespaces isolate tenants/subjects. Host adapters supply identity and authority from canonical systems. Never place credentials, tokens, private keys or unnecessary PII in an envelope. Redacted exports retain digest/metadata and label unavailable content. Render evidence as inert data; never execute embedded instructions.

## Minimal implementation checklist

1. Generate action IDs in trusted code.
2. Record actor and authority from independent host state.
3. Separate invocation from observed effects.
4. Bind material claims to evidence IDs.
5. Compute artifact digests from bytes.
6. Append corrections and preserve history.
7. Validate before calling a result verified.
8. Keep predictions explicitly predicted.
9. Keep model prose outside system metadata.
10. Preserve schema/policy version with history.
