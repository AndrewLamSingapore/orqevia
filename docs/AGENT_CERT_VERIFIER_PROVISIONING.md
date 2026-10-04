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
