# Fixed fresh29 admission — 2026-10-16 batch, protected validation, no local signatures

The active reviewed-case manifest contains the exact 29 proposed rows emitted by
protected main run 38861038816, attempt 1, workflow
`orqevia-fresh-initialization-validation-20261016.yml@refs/heads/main`, artifact
`initialization-a7eea39dbfb83769-validation-38861038816-attempt-1`.

The committed `governance/agent-cert-reviewed-cases.json` is the canonical
(sorted-key, compact) serialization of that run's `proposed_manifest`; its
sha256 is the artifact's `proposed_manifest_sha256`:

`acf5e44e46123c5548fc2125413e05fd082fc8a6b71df1db712db87e4a543887`

Original artifact digest and every evidence binding were independently checked
on ABEX. The original validation bytes are preserved in
`operations/fresh29-20261016/stage1-output/` (ABEX workspace records).

Fixed validation boundary: 2026-10-16T06:24:52.785415+00:00.
Fixed expiry: 2026-10-17T06:24:52.785415+00:00.
No timestamp renewal, substituted evidence or new execution claim. The existing
source expiry guard (`now < expires_at`) remains untouched: a delayed approval
after expiry cannot sign this batch and cannot add another 24 hours.

The previous active manifest is preserved byte-for-byte in
`agent-cert-reviewed-cases-expired-before-fresh29-20261016.json` and Git
history. Its evidence files, prior signatures and previous signed receipts
remain untouched.

The existing protected Azure OIDC signer and its authorization/key-version
policy are unchanged. Only original initialization case records are admitted;
the unchanged protected reviewer must recheck all code/evidence/currentness
bindings before any signature. No model calls, credential changes or
deployment. Pre-dispatch on ABEX: the protected parser accepted all 29 rows and
a full local dry-run of the signer flow (with only the Azure crypto wrappers
substituted; every review oracle, evidence hash, closure and time-chain check
executed for real) returned `SIGNED_CASE_EVIDENCE` / 29 / `l7 false`.

These are 29 individual partial qualification cases, not complete capability
verification or L7. Even valid signatures must pass native custody and
projection checks; a parent case never certifies a descendant. Preserve all
failures.
