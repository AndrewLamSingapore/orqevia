# ORQEVIA on desktop

Use the verified ABEX HTTPS origin with `/pwa/` on desktop and mobile. Existing
trusted sessions and the HTTPS profile continue to apply. There is one current
workspace; this package no longer serves its former independent renderer.

The optional local API relay retains its pinned upstream identity, HTTPS,
loopback binding, scoped client credential and idempotency checks. Current
settings use ORQEVIA_* names. Historical JARVIS_* settings remain readable for
migration; conflicting aliases fail closed. Credentials are never placed in the
workspace URL. The relay root redirects to the configured HTTPS PWA even when
the separate API credential has not been provisioned.

See PACKAGING.md for deterministic source packaging. Original renderer bytes
are retained in docs/history/desktop-retirement-20261106 and Git history.
Actual Dell hardware and off-device connectivity require their own verification.
