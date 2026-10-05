# Independent agent certification verifier (candidate)

The separately provisioned verifier identity is `svc.cert-verifier.independent`. It is a
service principal, separate from every registered agent, reviewer, and worker.
The legacy Ed25519 public-key pin set is
`governance/agent-cert-verifier-pins.json`. Its empty `keys` object deliberately
rejects every Ed25519 attestation. This repository does not contain a private
key, active Azure public-key pin, or live certification claim. The approved
verifier key is the non-exportable Azure Key Vault P-256 key documented in
`AGENT_CERT_AZURE_ES256_CANDIDATE.md`; do not create an additional exportable
Ed25519 key for this deployment.

For the selected Azure path, the protected reviewer must remain inaccessible to
executing agents. It uses the exact versioned Key Vault key ID and independently
reviewed P-256 public JWK as a trusted pin, never a key supplied by an agent
record or fetched opportunistically during verification. The protected-main
GitHub OIDC principal has key-scoped sign-only access; that setup alone proves
neither a successful token exchange nor a signed certification result. Review
pin changes with the corresponding Key Vault key version and remove revoked
versions from the trusted pin map. An empty map must keep certification at L0.

The Ed25519 signer and pin loader remain isolated legacy candidate code; their
in-process key-generation procedure is not the provisioning route for the
approved Azure verifier.

The protected verifier process independently inspects the exact case challenge,
runtime identity, worker result, case-specific oracle, and artifact bytes. For
Azure it approves the SHA-256 of `azure_es256_signed_bytes(row,
service_identity, key_id)` only after deciding PASS. `ProtectedAzureES256Signer`
checks that exact approval, source revision, timestamps and artifact digest
before invoking the injected Key Vault `sign(ES256, digest)` operation. It
checks the returned versioned key ID and independently verifies the signature
against the pinned P-256 public key. Workers and agents must have no access to
that operation. A digest supplied by a worker is not an independent review
decision.

`AzureES256CertificationVerifier` is the public-only callback for registry
projection when supplied with a trusted exact-version pin map. Both an empty
map and an unavailable verifier callback leave certification at L0. A real
independent review of every missing case, signed evidence, and a clean-room
audit are still required for L7; synthetic tests cannot establish those facts.

## Selected Azure Key Vault ES256 path

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
