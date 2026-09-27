# Golden Gen 2 live runtime attestation

Status: ACTIVE, READ-ONLY, LAN-ONLY

The ABEX host publishes a detached Ed25519-signed machine-readable attestation at:

- `https://192.168.1.23:8443/pwa/runtime-attestation.json`
- signature: `https://192.168.1.23:8443/pwa/runtime-attestation.json.sig`

The pinned verifier key is `governance/keys/abex-runtime-attestation-ed25519.pub` with fingerprint:

`SHA256:qtAf3agqYCAAcBk6n4Tf4fqqAJ3t444NEKD7sxr+QPA`

Run `scripts/verify_live_runtime_attestation.ps1` from a checkout pinned to the canonical governance commit. The verifier requires the existing trusted LAN HTTPS path and needs no credential. If a verifier intentionally lacks the ABEX private CA while still using the approved LAN path, `-AllowUntrustedTransportCertificate` may be used: authenticity still fails closed on the independently pinned Ed25519 signature and key fingerprint.

The host generator reads Docker's live container and image inspection records. It emits `VERIFIED` only when the running PRIME and Interface image IDs, OCI source revisions, health state, canonical Golden manifest, runtime-receipt digest, and explicit audio exclusion agree. A copied manifest with a changed expected source produced `UNVERIFIED` / `live_image_source_mismatch`; static metadata alone cannot establish the live binding.

All write methods tested against the published URL returned HTTP 403. The endpoint exposes no environment variables, token, password, Docker control, filesystem operation, shell, or mutation route. SSH and Docker control remain unexposed.

The host signing key is stored outside the repository under an ACL restricted to the ABEX administrator, local Administrators, and SYSTEM. Only its public key is committed. A bounded user task republishes the attestation every five minutes so an Interface container replacement cannot silently leave a stale or missing file; inability to inspect or sign fails the publisher rather than fabricating `VERIFIED`.

Read Aloud/iOS audio remains `PARKED_PHYSICAL_FAIL_NOT_ACCEPTED`. This mechanism does not change that status.
