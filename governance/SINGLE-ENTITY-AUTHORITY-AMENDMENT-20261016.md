# Single-entity operating authority amendment — 16 October 2026

Owner authorization: Lam approved this amendment on 16 October 2026, replacing
the dual-writer build authority with a single shared operating authority. This
document is the dated, reversible record of that decision.

## One boundary, exact scope

Dell, ABEX and the Owner are one shared ORQEVIA operating authority with equal
build, merge, deployment and operational authority. No principal is a higher
administration over the others. Each principal may branch, commit, push, open
and merge pull requests, and may deploy or operate ORQEVIA where that principal
holds actual host access and credentials.

## Deliberately unchanged

These are machine-safety and audit-integrity controls, not lines between
people, and remain in force regardless of which principal operates:

- Fail-closed runtime gates: Stable Spine, Action Harness v0, host guard,
  FAILSAFE containment, the WASM execution sandbox, and the advisory-only skill
  router.
- Evidence and audit integrity: hash-pinned records, frozen golden manifests,
  the byte-pinned operational manifest, and the OIDC verifier/signer identity
  binding. No historical receipt or hash is rewritten.
- STATUS.md "Verified" still requires the Owner's personal check. "Auditable
  always" needs a human witness for a Verified claim; this is the one retained
  check so an agent cannot self-certify.

## Physical boundary

Equal authority does not create host access or credentials. A principal can
deploy only where it already holds runtime access and credentials; none are
transferred, shared or created by this amendment. ABEX's existing runtime
remains the active deployment until a deployment is actually performed through
the shared-authority channel.

## Supersedes

This supersedes governance/DUAL-WRITER-AMENDMENT-20261016.md and any
single-writer wording. Living documents updated to match: AGENTS.md,
governance/CHANNEL_CONTRACT.md item 3, docs/TOTAL-INTEGRATION-ARCHITECTURE.md
and docs/INTERFACE-ACCESS-STANDARD.md.
