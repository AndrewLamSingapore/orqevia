# Azure Key Vault ES256 verifier adapter (candidate)

`AzureES256CertificationVerifier` is a public-only `verify_record` callback for
`AgentCertificationRegistry`. It accepts a trusted map of service identity to
exact, versioned Key Vault key ID to P-256 public JWK. No key is fetched from a
record or from Azure at verification time. An empty map denies all rows.

The protected review service first decides an exact case independently. It
passes `azure_es256_signing_digest(row, service_identity, key_id)` to Key Vault
`sign` with algorithm `ES256`, then places the returned 64-byte R||S signature
in lowercase hex under the record's `attestation.signature`. The response's
`key_id` must equal the pinned versioned ID. This is a digest signing operation;
the service must not hash the digest again before asking Key Vault to sign it.
The record binds agent, case, reviewer, executor, evidence digest, timestamps,
source revision, authority scope, service identity, algorithm, and exact key ID.

The adapter is independent of the Azure SDK and has no cloud credentials.
Provisioning a vault/key and granting a separate review principal `keys/sign`
access are external operations, not performed by this candidate. Private key
custody, reviewer separation, and the actual case verdict must be established
before producing any live certification record. The existing empty Ed25519 pin
set and L0 projection are unchanged.

References: [Key Vault sign REST contract](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/sign/sign?view=rest-keyvault-keys-2025-07-01),
[Key Vault ES256 key details](https://learn.microsoft.com/en-us/azure/key-vault/keys/about-keys-details),
and [RFC 7518 section 3.4](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.4)
for the 64-byte R||S signature encoding.
