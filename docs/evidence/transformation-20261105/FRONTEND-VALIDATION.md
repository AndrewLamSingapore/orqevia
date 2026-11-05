# Frontend source validation — final 5 November 2026

The replacement source is ready for the parent's batched release. This report
does not claim a deployment, live financial capability, model-quality gain or
completed foundational research mission.

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Existing portable frontend/unit/security checks | 114 passed, 0 failed | frontend-unit-final.log |
| Main browser suite, Chromium | 34 passed | browser-chromium-final.log |
| Main browser suite, Firefox and WebKit | 34 passed each, 68 total | browser-cross-engine-final.log |
| New Projects failure/recovery regression | 1 passed per engine | browser-projects-final.log |
| New mobile metric-label clipping regression | 1 passed per engine | browser-mobile-metric-final.log |
| Later depot manifest-ID integration checks | 6 Chromium cases passed | browser-final-integration.log; the initially incorrect new Projects assertion was then corrected and verified separately in all engines |
| Desktop/mobile source visual inspection | 30 captures, 0 document/body overflow, 0 JS exceptions; no clipped metric labels | VISUAL-ROUTE-RECEIPT.json |
| Source syntax/whitespace | Node syntax and git diff checks passed during implementation | parent final gates remain authoritative |

All browser checks used the existing trusted certificate with verified HTTPS at
the temporary loopback source-preview origin. No certificate bypass was used.
The test helper was stopped after capture; no permanent service was added.

The browser suite exercised mission submission, model/memory projection and
plan handoff, owner/member separation, no-token
transport, private-state clearing, delayed old-session responses, independent
fabric discovery/execution and receipt readback, malformed inputs, PNG/WAV
integrity, explicit audio playback, offline shell installation, canonical routes,
responsive navigation, and accessible labels. New tests also covered fixed
evolution experiments/history, read-only wallet/depot truth, explicit Evidence
Lens capture and Projects outage recovery. Portable tests preserve the task
continuation/revision contracts; this is not a new live continuation receipt.

## Corrected observed failures

- Adapted old navigation-only fixtures to the new canonical surfaces while
  preserving their security/functional assertions.
- Fixed direct Console initialization so a deep link stays visible.
- Fixed Intelligence's observation request selection after route consolidation.
- Preserved long coaching labels and source strings on compact screens.
- Matched depot capability links to the actual manifest IDs.
- Caught Projects' previously unhandled startup rejection and made Refresh clear
  the outage state on success. A real browser regression verifies this behavior.
- Corrected metric heading wrapping/size after visual inspection showed
  `UNAVAILABLE` extending beyond its card despite a clean document-width check.
  The regression now compares each element's scrollWidth and clientWidth.
- Grouped the footer identity and preserved its Chinese/punctuation via HTML
  entities. Original frontend evidence remains outside the served asset tree.

## Visual evidence and comparison

`screenshots/` covers the 12 canonical views plus Projects and the public page at
1440px and 390px, with additional owner Evidence Lens closeups. Every image is
labelled **SOURCE PREVIEW / API FIXTURES / NOT LIVE**. The Lens example explicitly
states NOT_RUN/NOT_ASSESSED and performs an explicit read, not evidence recording.

The upstream source dashboard image was inspected beside the replacement. The
ivory/olive palette, centered original mark, simple line icons, geometric tile
grid and compact headings follow that source. Exact comparison to the
Owner-selected screenshot is not possible because it was not attached here.
Physical iPhone/PWA installation and installed-client update adoption remain
separate live acceptance work.

## Measured scope of simplification

`STYLE-PAYLOAD-FINAL.json` records seven linked application stylesheets becoming
two, with source CSS bytes changing from 44,777 to 21,984 (separately gzipped:
13,106 to 5,582 bytes). This is a deterministic source-payload comparison, not a
claim of measured network latency, useful model output or cognitive improvement.
No frontend framework or application package dependency was added.

## Release boundary

`FRONTEND-SOURCE-RECEIPT-FINAL.json` fingerprints all 48 changed/new client files,
including staged and unstaged changes in the parent's shared batch. Parent owns
the final local Python/lint gates, single PR/CI/merge, image alignment, production
deployment, HTTPS live tests, rollback receipt and canonical handoff. Ensure the
latest CSS, footer, Projects controller/tests and clipping regression are staged.

Supply Depot does not yet provide arbitrary application installation/removal;
those actions use the supported host release pathway. No Kiwix/Qdrant duplicate,
new wallet, financial account, transaction, paid provider activation or
unrestricted container control was introduced.

## Qualification after the parent's first local full suite

`BRANDING-PUBLIC-QUALIFICATION.json` and
`python-branding-public-targeted.log` record **11/11 targeted Python tests
passing** across branding, the independent candidate verifier and Interface
Server tests. The three edited Python files also pass targeted Ruff/format and
whitespace checks. No full Python/CI run was launched by this subtask.

The superseded expectations were the v1 install-image pins/prefix and the public
"Under your authority" copy. Their replacements positively require the complete
current v2 manifest, seven frozen PNG dimensions/digests, the original geometric
SVG pin, exact cached icon set and functioning canonical workspace entry. The
public root remains separate from private controls, and unauthenticated identity
access still returns 401 under closed posture.

The service-worker mismatch was an actual source defect, not an obsolete test:
parent replaced the retired official-v1 precache entry with the current v2
maskable512. This is distinct from the Projects startup/recovery bug and the
metric-label clipping correction described above. Parent's fresh Linux full
qualification and final CI remain the release authority.
