# Independent agent certification verifier (candidate)

The proposed verifier identity is `svc.cert-verifier.independent`. It is a
service principal, separate from every registered agent, reviewer, and worker.
The public-key pin set is `governance/agent-cert-verifier-pins.json`. Its empty
`keys` object deliberately rejects every attestation. This repository does not
contain a private key, active public-key pin, or live certification claim.

To activate this design, an operator must first establish a separate verifier
principal on a confirmed host or isolation boundary that executing agents
cannot access. Generate an Ed25519 key under that principal, retain its private
half in that principal's protected key store outside PRIME, and give the agent
runtime only the 32-byte raw public key. Record a unique key ID, raw public key
hex, and SHA-256 of those raw bytes in the pin file. The repository change and
host key custody must be reviewed together; a fingerprint in the same file does
not authenticate a malicious replacement of that file. Remove revoked keys
from the deployed pin set and restart the verifier when rotating keys.

The protected verifier process independently inspects the exact case challenge,
runtime identity, worker result, case-specific oracle, and artifact bytes. It
computes the SHA-256 of `_signed_bytes(row, service_identity, key_id)` only after
deciding PASS and passes that digest to `ProtectedCertificationSigner.sign` in
the same protected process. The signer checks the record revision, result,
artifact path and bytes, review digest, timestamps, and public verification
contract before returning a signature. Workers and agents must have no access
to the private key or the signer process. A digest supplied by a worker is not
an independent review decision.

`verifier_from_pin_file` loads the public pins for registry projection. Both an
empty pin set and an unavailable verifier callback leave certification at L0.
Only a real independent review of every missing case, a signed evidence record,
and a current registry projection can support an L7 claim. Candidate tests use
synthetic in-memory keys and cannot establish live verifier custody.

## Azure Key Vault ES256 option

`ProtectedAzureES256Signer` is an alternative protected-process boundary for
the separately provisioned non-exportable P-256 Key Vault key. It consumes the
same versioned key ID and pinned public JWK as
`AzureES256CertificationVerifier`; no private key or cloud credential is stored
in PRIME. Its injected operation must call Key Vault `sign(ES256, digest)` only
after the protected reviewer has independently approved the exact record and
artifact. The returned Key Vault key ID and 64-byte R||S signature are checked
against the pin before a record can be returned. No agent-facing or PRIME
runtime endpoint for the signer is supplied here. Synthetic tests are contract
proof, not live Azure signing or L7 certification.
