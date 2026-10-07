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

## Optional local Observatory projection

The candidate image copies only the reviewed public file
`governance/agent-cert-verifier-azure-pins.json`. The Observatory route uses it
only when `PRIME_AGENT_CERT_AZURE_ES256_ENABLED=1`; its SHA-256 is fixed in the
runtime source. The source pin uses the LF Git blob hash, with CRLF normalized
for an existing Windows checkout; mounted overrides use exact raw-file hashes.
A missing file, a changed digest, or a malformed JWK reports
`UNCONFIGURED` and projects every case as unproven. The verifier rereads the pin
on each request; a changed file fails its digest check. Disable the feature or
restart with a reviewed new mount to revoke or rotate a bind-mounted pin. No
private key or Key Vault bearer is present in the image; the route never
invokes a signing operation.

For a reviewed rotation, set the absolute host path and SHA-256 of one public
`{"key_id": "...", "jwk": {"kty": "EC", "crv": "P-256", "x": "...", "y": "..."}}`
file and apply `deploy/observatory-verifier-pin.override.yml` with
`docker-compose.yml`. The override mounts that single file read-only at
`/run/prime-cert-verifier-pin.json`; it refuses to create a missing host path.
Both override variables must be present. An incomplete or invalid override
does not fall back to the baked pin. Store it outside `PRIME_DATA_DIR`; the
runtime refuses a pin inside the agent-writable data root. Do not put signing
credentials or private key fields in this public file.

`GET /control/api/agent-capabilities` requires a loopback peer, local Host,
and exact `Authorization: Bearer <PRIME_SPINE_TOKEN>`. It returns only a
configured/unconfigured verifier state and the per-agent projection, never
JWK coordinates or the key ID. A valid signature alone cannot create L7:
the registry separately checks exact runtime source, fresh timestamps, owned
capability, independent reviewer, authority, and both execution and review
artifact digests. Runtime activation, quality, autonomy, latency, and cost
remain unverified or unknown in this view.

References: [Key Vault sign REST contract](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/sign/sign?view=rest-keyvault-keys-2025-07-01),
[Key Vault ES256 key details](https://learn.microsoft.com/en-us/azure/key-vault/keys/about-keys-details),
and [RFC 7518 section 3.4](https://www.rfc-editor.org/rfc/rfc7518.html#section-3.4)
for the 64-byte R||S signature encoding.
