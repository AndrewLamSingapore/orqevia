# Current canonical source pointer reconciliation

Source-only candidate; no production deployment or runtime acceptance transition.

## Pinned baseline and remote observations

- Base `main`: `0819c515d768af6c4c0189e2bddbb4a4a4a247de`.
- Base tree: `00308c5c3b5ef75584ce97cc4f79c7d88b18fc4f`.
- Direct `git ls-remote` observed both `feat/supreme-integration-20260925` and
  `governance/golden-gen2-20260927` at
  `67b0dd31ba31350333910498b3af0a0c135b1e95`.
- The accepted governance tree and reconciled main tree are identical. Main
  preserves the historical integration commits instead of discarding them.

An initial local remote-tracking observation showed `135ac4a...`. This was stale
cache, not evidence of remote movement: this checkout's fetch refspec tracked
only `main`. Direct remote lookup established the values above; explicit branch
ref mappings refreshed the local tracking refs. No remote branch was rewritten.

Five product consumers and the profile already select PRIME `main`; PRIME's own
active pointer documents still selected the older named integration branch.
The candidate aligns those active pointers with the reconciled main lineage.

## Changed scope

Current SSOT/AGENTS/README/channel references, operational-manifest pointer
fields, pointer validators, and the generated mirror select `main`. The mirror
generator derives its source link and resolution branch from the machine
manifest. Pointer validation rejects disagreement across the active documents.
The README's architecture links now identify accepted non-audio Golden Gen 2
and retain Golden Gen 1 as rollback/reference, consistent with existing STATUS.

Golden manifests, tags, runtime receipts, prior evidence, and STATUS.md were not
modified. Historical production-lineage values remain historical. Existing
candidate-manifest and Independence test fixtures retain their original branch
labels because they do not select the current source. No code under `app`,
production configuration, database, session, identity, or host setting changed.

## Executed qualification

- Pointer and operational-manifest tests: **21 passed**.
- Independent root-agent rerun of the same focused tests: **21 passed**;
  root also reviewed the source-only diff.
- Current SSOT pointer check: PASS.
- Canonical source/generated mirror check: CONSISTENT.
- Generated mirror `--check`: CONSISTENT.
- Offline SSOT/schema/secret-pattern check: PASS, 526 files scanned,
  21 registry agents, zero secret-pattern findings.
- Operational manifest `--allow-stale`: accepted its truthful STALE state with
  zero schema errors. Existing expired/public/physical evidence was not promoted.
- Diff review and `git diff --check`: PASS.
- Diff against base confirms all existing Golden manifests/receipts/evidence
  and STATUS.md remain unchanged.

## Separate unresolved live evidence boundary

Root's read-only `python -B` probe inside accepted `b171253...` production found
canonical runtime identity and agent count available, but governance/architecture
questions abstained with UNVERIFIED/UNAVAILABLE because required governance files
are absent from the image. A stale Gen1 answer from a local checkout is not a
production result. Source also contains historical governance assumptions that
require a separately qualified successor before runtime changes.

No Evidence Lens end-to-end PASS is established by this pointer reconciliation.
The full A–F live objective qualification remains unfinished; static demo tests,
direct function probes and source-pointer checks are distinct evidence scopes.
`docs/evidence/EVIDENCE_LENS_ACCESS_GAP_20260927.md` preserves that diagnosis.
The present change is a clean source/governance checkpoint only.
