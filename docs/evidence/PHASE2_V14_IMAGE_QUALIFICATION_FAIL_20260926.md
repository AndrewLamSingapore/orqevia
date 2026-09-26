# Phase 2 v14 immutable image qualification

Verdict: **FAIL — malformed-envelope validator exception**

The image `prime:phase2-ba2a275` was built only from frozen tag `jarvis-prime-phase2-candidate-v14-20260926` and has image digest `sha256:5544ca2ecc0da5e4a7659a375c892f5c53af03aab53eec7f9e444c1bfbfd3c56`. It was not deployed.

An isolated, network-disabled, read-only smoke run showed that `validate_envelope({'schema_version':'bad'})` raised `KeyError('action_id')` instead of returning `INVALID`. Candidate v14 and this image remain preserved but are prohibited from promotion. Golden Gen 1 production was not modified.
