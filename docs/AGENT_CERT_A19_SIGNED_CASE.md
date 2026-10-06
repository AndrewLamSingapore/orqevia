# A19 role:normal signed-case path (candidate)

This source path has not signed a protected-main A19 case until a successful
`PRIME independent verifier OIDC preflight` dispatch and retained signed artifact
are observed. A feature-branch test, including a genuine off-host A19 PASS,
cannot substitute for that run. One signed `role:normal` record is not an L7
level, production deployment, agent authority change, or owner verification.

After the A19, A26, independent-review, and verifier workflows all land on
protected `main`, run these workflows in order on the **same exact main SHA**:

1. `A19 off-host role observation` via `workflow_dispatch`. Retain its successful
   run ID and `a19-offhost-observation-<run_id>` artifact ID.
2. `A26 independent A19 observation`, passing those two A19 IDs. Retain its
   successful run and `a26-a19-observation-<run_id>` artifact IDs.
3. `Protected independent A19 review artifact`, passing both exact run/artifact
   pairs. Retain its successful run and `a19-a26-unsigned-review-<run_id>`
   artifact IDs. This run produces an unsigned review, not an attestation.
4. `PRIME independent verifier OIDC preflight`, passing all six IDs. The existing
   reusable signer downloads all three artifacts, authenticates GitHub run and
   artifact metadata, recomputes the exact A19 role oracle and A26 review,
   compares the separate review artifact byte-for-byte, and only then requests
   Azure OIDC and Key Vault ES256 signing. It verifies the pinned public key and
   rejects tampered signed fields before uploading the evidence package.

No-input verifier dispatches retain the earlier non-certifying canaries. Partial
IDs fail before artifact retrieval. Every source artifact must still exist and
be unexpired; the upstream workflows currently retain theirs for seven days.
The signed package contains the A19 execution receipt, measured profile, A26
receipt, independent review, and one `a19/certification.json` case record. The
package is retained by Actions for 90 days, but the record expires six days
after signing. An expired record remains historical evidence, not a current
certification. No central manifest, status authority, or runtime is mutated.

The signer remains the existing `prime-verifier-oidc.yml` →
`prime-verifier-signer.yml` protected-main caller/reusable-job pair and the same
versioned Azure Key Vault pin. This candidate adds no Azure federated identity
or key permission. The caller supplies only immutable run/artifact IDs, never
code, a signing payload, or an asserted verdict.
