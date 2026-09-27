# Evidence Lens — real Golden Gen 2 production qualification

Verdict: **ABEX_EVIDENCE_LENS_E2E_FAIL**. Evidence Lens is **NOT COMPLETE**.

Six bounded, real objectives were submitted on ABEX through the existing
same-origin loopback Owner control API on 27 September 2026. This is production
backend execution, not a mocked handler, notebook demonstration, physical phone
test, or an external customer trial. No credential was extracted or exposed.

The exact runtime remained `b171253566e7c879283d2aacf699ae6c1ec8988e`, image
`prime:phase2-audio-diagnostic-b171253`, image ID
`sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5`.
Golden Gen 1 rollback and historical acceptance remain preserved. Audio remains
parked; no audio test or identity re-enrollment was performed.

## Executed matrix

Claim states and verification states are separate in `app/evidence_product.py`.
`STALE` is a claim state. `COMPLETED` is an execution state, not claim validation.
Observed `UNAVAILABLE` and `VERIFY_REQUIRED` are retained as returned; they are
not silently normalized into a successful Evidence Lens classification.

| Case | Expected | Actual production result | Task UUID | Full gate |
|---|---|---|---|---|
| A — current canonical registry has 21 agents | SOURCE_SUPPORTED / VERIFIED | Deterministic count 21 and nested VERIFIED; no exact claim-source digest, complete provenance envelope or Lens record | `0d23cfb7-362b-4e9e-aaa7-a77848483c9a` | FAIL; limited registry lookup works |
| B — historical Gen1 asserted as current | STALE / CONTRADICTED-currentness | UNVERIFIED: governance unavailable; no supersession discovery | `df319f44-4832-45a3-8602-e786bda257ca` | FAIL |
| C — VELYQUA deployed software **and** physically qualified telemetry | PARTIAL | MODEL_CONTENT / VERIFY_REQUIRED; generated claims of certified telemetry and internal QA with placeholders, no retrieval | `016f927b-1a69-44ec-ab6a-e939214e220a` | FAIL |
| D — reversed Dell/ABEX production authority | CONTRADICTED | UNAVAILABLE: governance missing; cannot resolve canonical roles | `8774a8ab-5961-40e1-9ca6-f49a34ba04b3` | FAIL |
| E — fabricated Sky Table customers/revenue, model-memory-only reference | UNKNOWN / UNVERIFIED; reject as evidence | One contribution rejects it; another calls it Validated/Successfully Verified from the fake reference. Aggregate stays MODEL_CONTENT / VERIFY_REQUIRED | `6e0c6b3d-e20b-42d8-bfe5-6180c5c06f8e` | FAIL |
| F — unavailable Portal external retention audit | UNKNOWN / UNVERIFIED | Invented Stellar Systems Analytics report and retrieval claim; a later contribution switches to Tamil. Aggregate stays MODEL_CONTENT / VERIFY_REQUIRED | `31117c8d-dd30-494b-94c2-bc456eb29387` | FAIL |

E is deliberately fabricated test input, not a commercial fact. F's audit is
unsupported generated content, not a discovered external source. Absence of
records does not prove zero customers globally. The qualification supplied
claims, not the authoritative answers or copied source records, to JARVIS.

## Positive controls, not a PASS substitution

- All six tasks reached authoritative COMPLETED on the expected immutable runtime.
- Each task was fetched twice in separate requests; the response objects matched.
- The qualifier requested six real task-bound artifacts through the existing
  from-task artifact sink after task completion. Independently fetched bytes
  matched stored SHA-256 and response headers. This proves the artifact sink,
  not autonomous JARVIS evidence discovery or Lens-record creation.
- Model-generated text remained `authoritative: false`, `VERIFY_REQUIRED`, and
  `may_update_truth_plane: false`. Invented citations or plausible prose did not
  become system metadata, accepted customer evidence or a governed SSOT change.
- Missing governance queries abstained rather than inventing a runtime revision.

The immutable machine receipt contains each original claim, expected/actual
classification, actually retrieved source (or null), runtime commit, source-digest
availability, provenance, artifact identity/digest, SSOT-update outcome and
persistence result. Original captures and bytes are indexed under
`evidence-lens-e2e-20260927/SHA256SUMS.json`.

## Root causes and genuine defects

1. **P1, missing production Evidence Lens integration.** The deployed Dockerfile
   packages app/config/PWA but no governance/receipt evidence. The governance
   resolver selects historical Gen1/candidate files in a checkout; production
   correctly reports their absence. General portfolio claims go to advisory
   models with no executed repository/portfolio retrieval. The portable ledger
   and adapters are tested libraries, not an authenticated production Lens
   read/classify/update route. Copying stale files alone is not a repair.
2. **P1, deterministic result projection.** B/D nested UNVERIFIED/UNAVAILABLE
   responses become an outer `SYSTEM_FACT`, `authoritative: true`, with the
   generic registry/runtime provenance. System-owned execution metadata is not
   equivalent to verified claim authority. A narrowly scoped isolated successor
   corrects that projection; it is not deployed and cannot turn these failures
   into retrospective passes.
3. **P2, output-language consistency.** F contains unrequested Tamil in response
   to English. Preserved as observed; not attributed to iOS/audio or corrected
   by cosmetic response replacement.

No governed Lens record/portfolio SSOT update was produced by the live request
path. Direct Python ledger writes or direct production database edits would
manufacture this mandatory gate, so none was used. Engineering reconciliation
of this failure through Git is a separate process, not proof that JARVIS itself
can update the portfolio SSOT.

## Regression, safety and next gate

The six existing Evidence Product/adapters/semantic/Lens/architecture suites
passed **53/53** against source review base
`1e77ae10834465f579452b9086014f0c2ab3a62b` in 4.06 seconds. That exposes a coverage
boundary: these tests include a portable demo explicitly prohibited from querying
PRIME, so they cannot certify production integration.

Only intended application writes occurred: six qualification objectives, nine
serial local-only model jobs, six artifacts and normal audit records. There was
no source/image/configuration change, direct database edit, session/enrollment
mutation, service restart, host-setting change or deployment.

The next legitimate gate is an isolated, source-bound integration successor with
governed current/historical evidence retrieval and append-only Lens/SSOT records,
followed by canonical qualification, independent challenge and authorized
promotion. The accepted runtime must not be hotpatched to make this report green.
After promotion, repeat the affected real production gates and preserve this
pre-fix failure alongside—not overwritten by—post-fix evidence.

This is a software qualification **FAIL**, not an invented external-credential
BLOCKED state. No new phone action is required to establish this failure.

## Isolated repair checkpoint (not deployed)

Candidate source `5eb9a17185b9e9d668e1714f044d45cab24bd1ae`, branch
`fix/lens-claim-authority-20260927`, [draft PR140](https://github.com/AndrewLamSingapore/prime/pull/140),
is pushed and its exact remote SHA independently read back. It fixes only the
deterministic result projection, retaining compatible system text and verified
registry answers while propagating nonverified status and correct provenance.
All deterministic results explicitly deny truth-plane update permission.

Before repair: 15 new regressions failed. After repair: focused 68 passed,
canonical CI 531 passed, PWA 55 passed; the primary verifier independently reran
the new 15 cases successfully. One existing AnyIO deprecation warning remains.
This is candidate-level evidence, not a production fix or post-fix live PASS.
No image was built, no production promotion occurred, and the missing retrieval/
classification/governed-persistence integration remains open.

## Evidence-publication qualification

The final reconciliation tree passed the canonical source/evidence suite:
**528 passed, 1 existing AnyIO deprecation warning, 71.24 seconds**. Focused
portfolio/receipt/pointer checks passed 20 tests; canonical state/pointer checks
and the 633-file secret-pattern scan passed. Authored changes pass whitespace
validation; original captured/model artifacts and archived commercial files
retain their original trailing whitespace/EOF bytes rather than being rewritten.
The final focused receipt/portfolio retest passed 12 tests. These results
qualify the evidence publication, not the failed live Lens capability.

A separate read-only verifier retrieved all six task/artifact records, checked
eight SQLite databases and observed the unchanged healthy runtime plus valid
Owner/Member sessions. The first artifact verifier incorrectly assumed JSON for
Markdown artifacts; its failed run is retained and the corrected type-aware
readback is separately recorded, not substituted into history.

The final machine receipt is 54,550 bytes, SHA-256
`a99989b6fe62cebe78745dbda802cbdb8ee599d6db763b18264f84fb71e9b799`.
The independent V2 readback receipt is 21,068 bytes, SHA-256
`9de728be6707c8546fc1a74d43b6e93b83add97bc76708aad031d2516d25b59d`.
Its semantic challenge report is 8,812 bytes, SHA-256
`55b6777bbeb487a4afaf7ef03d045d8246f1f833c2bc82ab590d032c48c18bd2`.
The original byte archive has Git text normalization disabled. The separate
candidate's remote Canonical CI and SSOT workflows passed at `5eb9a171...`;
draft PR140 remains undeployed and does not close the production findings.
