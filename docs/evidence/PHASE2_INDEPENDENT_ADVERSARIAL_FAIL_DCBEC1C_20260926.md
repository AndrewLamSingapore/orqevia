# Phase 2 Independent Adversarial Verification — Frozen `dcbec1c`

Verdict: **FAIL — P1 verification provenance and replay integrity**

Independent review reproduced three material defects: attestation identity and expiry were not included in the host-verified body; deletion of an auxiliary evidence-use row allowed a second consequential effect to reuse evidence; and a portable observation could claim `SYSTEM_VERIFIED` with an arbitrary well-shaped digest without canonical-byte or host verification.

The frozen candidate remains prohibited from image build or promotion. Repairs bind attestation identity and expiry, enforce evidence uniqueness from the primary effect ledger, recompute observation digests, and require a host-supplied verifier for portable system-verification claims. Golden Gen 1 production was not modified.
