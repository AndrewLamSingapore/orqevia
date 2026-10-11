# Fixed fresh29 admission — protected validation, no local signatures

The active reviewed-case manifest contains the exact 29 proposed rows emitted by
protected main run 38116584735, attempt 1, source afb88bad51340263c2b45b1dba966aaf2fe7d446.
Original artifact digest and every evidence binding were independently checked
on ABEX. Original validation bytes are preserved in
fresh29-protected-validation-38116584735.json.

Fixed validation boundary: 2026-10-11T05:59:52.750557+00:00.
Fixed expiry: 2026-10-12T05:59:52.750557+00:00.
No timestamp renewal, substituted evidence or new execution claim.

The previous expired active manifest is preserved byte-for-byte in
agent-cert-reviewed-cases-expired-before-fresh29-20261011.json and Git history.
Its evidence files and previous signed receipts remain untouched.

The existing protected Azure OIDC signer and its authorization/key-version
policy are unchanged. Only original initialization case records are admitted;
the unchanged protected reviewer must recheck all code/evidence/currentness
bindings before any signature. No model calls, credential changes or deployment.
Owner authorized autonomous certification on 11 October 2026.

These are 29 individual partial qualification cases, not complete capability
verification or L7. Even valid signatures must pass native custody and projection
checks; a parent case never certifies a descendant. Preserve all failures.
