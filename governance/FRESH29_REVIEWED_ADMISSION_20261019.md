# Fresh29 initialization evidence batch - 19 October 2026

## Exact candidate

| Item | Value |
|---|---|
| Candidate image | `orqevia:final-naming-candidate` |
| Image content ID | `sha256:67af1345345ab8b89b2195507c3ed8343ac1998de79ec81f8494dcaf49346f37` |
| Candidate source revision | `767f9451d42c65eb905f2c3e5f816536c4e17982` |
| Verifier closure revision | `0c10fca0938eb66280ebb6dedb9008f09f57c8e6` |
| Evidence batch digest | `ce9a3f5a5d5da9180b8b7879a45de180c709a065907d1d76b577b80a153248d1` |

The image label remains the build-time value `candidate-final-naming`; the
source and content IDs above were independently checked. All 46 runtime review
closure files are byte-identical to `767f945`, and all 47 protected verifier
closure files plus the original runtime closure pass `unchanged_reviewer_code`
and `unchanged_runtime_reviewer_code` against the pinned revisions.

## Collection

The candidate was run in a disposable container with no network, no published
ports and a private `/data` directory. The 29 deterministic zero-model
initialization cases were collected by the repository-native operator and event
collector. Each pair contains a real candidate execution, original Objective,
artifact and durable action joins, plus a distinct deterministic registered
review.

Result: **29/29 collected, 0 failed**. The dated plan is
`governance/agent-cert-initialization-proposed-fields-20261019.json`
(SHA-256 `5b283d1b21b9b157f7b6ea8f3a7da8c972cb936c9e454a2e5eb64e9a07866fb7`).
The 58 evidence files occupy 689,851 bytes. The local non-protected oracle audit
passed all 29 cases and returned `CURRENT_VERIFIER_AND_SOURCE_CLOSURE_PASS`
(ABEX receipt SHA-256
`5a7e6efe4d1ce8f9ab03fe96d50f52193c2f6cf07eeaf583231cecebd9cf49e6`).

A first disposable candidate run was rejected before evidence creation because
the isolated environment omitted `ORQEVIA_REGISTRY_V1_ENABLED=1`. That failed
attempt is retained as counterevidence, with stdout SHA-256
`eb6f7518f88ac1cc5a100377dacb692d9c4ca91182ce642590b8b227f4d64179`.
It is not admitted, retried as the same case, or counted as a pass.

## Protected validation

The fixed public-only validator ran once on protected `main` at
`221a413a96329220b85538a941cbc39150a32826`: run `39236815850`, attempt 1,
workflow `orqevia-fresh-initialization-validation-20261019.yml@refs/heads/main`.

It returned 29/29 original oracles PASS with:

- protected boundary `2026-10-19T10:21:09.966142+00:00`;
- fixed expiry `2026-10-20T10:21:09.966142+00:00`;
- proposed manifest SHA-256
  `b99106df4d4e81a325e9cb05528a3086ef7a178e130301a549c740ca54763956`;
- `signature=NOT_PERFORMED`, `l7_awarded=false`, `installed=false`.

The exact proposed manifest is now the active
`governance/agent-cert-reviewed-cases.json`. The prior active manifest is
preserved byte-for-byte as
`governance/agent-cert-reviewed-cases-expired-before-fresh29-20261019.json`.
The complete protected-validation artifact is retained as
`governance/fresh29-20261019-protected-validation.json`.

## Admission boundary

This batch is still **UNSIGNED**. The remaining step is one protected Azure
ES256 signing run over the exact active manifest. No signature, installation or
L7 claim exists at this checkpoint.
