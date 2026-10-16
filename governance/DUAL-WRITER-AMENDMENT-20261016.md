> Superseded 16 October 2026 by
> [governance/SINGLE-ENTITY-AUTHORITY-AMENDMENT-20261016.md](SINGLE-ENTITY-AUTHORITY-AMENDMENT-20261016.md).

# Dual-writer build authority amendment - 16 October 2026

Owner authorization: Lam approved this amendment on 16 October 2026, converting
ORQEVIA from ABEX single-writer to dual-writer build authority. This document is
the dated record of that decision.

## What changed

- Dell is promoted from read-only reviewer to co-writer for ORQEVIA
  implementation and merge. Dell may branch, commit, push, open and merge pull
  requests.
- ABEX remains the sole deployer and operator, and remains the runtime
  acceptance and production authority unless the Owner separately amends that.
- Only Lam may move an item into STATUS.md "Verified" sections.

Living documents updated to match:

- governance/CHANNEL_CONTRACT.md item 3
- AGENTS.md (three clauses plus the amendment notice)
- docs/TOTAL-INTEGRATION-ARCHITECTURE.md
- docs/INTERFACE-ACCESS-STANDARD.md

## What is deliberately unchanged

- The fail-closed runtime gates are intact: Stable Spine, Action Harness v0,
  host guard, FAILSAFE containment, WASM execution sandbox, and the advisory-only
  skill router.
- The frozen golden manifests (golden-gen1-manifest.json and
  golden-gen2-manifest.json) are not edited. Their frozen authority fields remain
  historical records.
- governance/operational-manifest.json is not edited; its byte-pinned authority
  prose and evidence hashes are preserved.
- The OIDC verifier/signer identity binding is unchanged; it governs signing, not
  push access.
- No historical evidence, receipt, hash, STATUS.md section or prior record was
  rewritten.

## GitHub write access

The repository AndrewLamSingapore/orqevia is private with a single collaborator,
AndrewLamSingapore. There is no separate Dell GitHub account to add. Dell gains
push capability by authenticating on the Dell host under the Owner account (for
example `gh auth login` or a fine-grained personal access token scoped to this
repository). No collaborator addition is required or was performed.

## Addendum - 16 October 2026 (night), owner order

Owner order "delete anything before gen4" superseded the untouched-frozen-baseline
clause above for the golden manifests only: `governance/golden-gen1-manifest.json`
and `governance/golden-gen2-manifest.json` were removed (recoverable from Git
history) and re-issued as `governance/golden-gen4-manifest.json` binding the
ORQEVIA epoch runtime per role (backend `48648edd`, interface build `891e3adf`),
with updated verifier pins. `governance/operational-manifest.json` received the
matching golden_architecture block update, admitted by the pinned reconciliation
test. All other clauses remain in force.

## Status record

A dated, non-Verified STATUS.md entry should follow through the normal
single-status-authority flow, preserving its byte-pinned history.
