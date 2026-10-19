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

## Protected signing

The independent OIDC signer ran once on protected `main` at
`3e498389e7c2aed9bdd8a02ffdfa792902d1e7ab`: run `39237401371`, attempt 1.
The artifact
`prime-independent-signed-cases-3e498389e7c2aed9bdd8a02ffdfa792902d1e7ab-39237401371`
contains 29 signed cases with `state=SIGNED_CASE_EVIDENCE` and
`l7_awarded=false`.

- artifact ZIP SHA-256
  `375152b193abf394e03b777a0bd5ff50bc42b10fd6e6f1d4682a1e1ecec6acdd`;
- signed-cases SHA-256
  `192ced6249dd32218a0f89b1f70b3db22e4f32c776a9fab77265a51b968bfb50`;
- local public-key re-verification: 29/29 signatures valid;
- each signed row exactly matches the admitted record fields and evidence
  digests, with the same fixed expiry.

The exact artifact is retained as
`governance/fresh29-20261019-signed-cases-39237401371.json`.

## Boundary after signing

This is **29 individual initialization cases**, still not an L7 award,
installation, runtime activation or deployment. The fixed signatures expire at
`2026-10-20T10:21:09.966142+00:00`.

The seven compatibility files remain byte-identical in this exact signed
candidate. A later change to any of those files invalidates that runtime closure
binding, so final legacy-name retirement remains a separate code migration with
its own fresh evidence and closure cycle.

## Deployed

The Owner approved deployment on 19 October 2026. Backend and interface now run
the exact signed image; post-deploy acceptance recorded all nine expected
containers, Owner authentication, gateway health and denial, 21/21 queue
liveness, and Higgsfield readiness. Runtime attestation is `VERIFIED` under
Golden `orqevia-golden-gen7-20261019` for source/image `767f945` /
`sha256:67af1345…`.
