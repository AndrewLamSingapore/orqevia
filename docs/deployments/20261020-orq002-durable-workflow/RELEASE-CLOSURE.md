# ORQEVIA durable workflow release closure — 20 October 2026

## Release

- Branch: `codex/orqevia-mit-memory-20261020`
- PR: #414
- CI-verified source: `66829d3fcd675b9985790fea199b2d7189503683`
- CI result: 9/9 checks successful
- Evidence PRs #416 and #417 are merged.
- Final main: `4fb0fc6eec83d3ff8dbeb8458a61b23815cf16b9`
- Evidence PR #419 merged the final deployment sweep.
- Published release: `orqevia-release-20261020`
- Post-merge CI: 7/7 successful
- Local full regression: **6,088 passed, 20 skipped, 3 deselected,
  102 subtests passed**
- PWA unit tests: **81 passed, 0 failed**

The merged main source is now the live deployment identity.

## Live deployment

- Source: `d4e2479bd16f77e669af10df1409cce989ae661c`
- Image: `orqevia:release-d4e2479-20261020`
- Image digest:
  `sha256:632d3db51fbd810c49fd09f105c0ede0653bc8f8ba6c44f1ccd7dae76bfa110d`
- Backend and interface: healthy
- Rollback image: `orqevia:orq002-workflow-20261020`
- Rollback digest:
  `sha256:d2de24102ba34642deb726b88b3d1e1cee18a1767fb1d4b0333e282de1177ebe`
- Secondary rollback: `orqevia:final-naming-candidate`
- Public PWA: `https://jarvis.lamjarvis.com/pwa/projects.html`
- LAN PWA: `https://192.168.1.23:8443/pwa/projects.html`

The post-deployment registry dispatch returned HTTP 202 and completed job
`73445356-a783-4382-962f-f9b5e2a6f565` through `a01` with a non-empty result.
A fresh 21/21 lightweight queue cohort also completed without failure.

The rollback drill restored source `cb01d50`, verified both services healthy,
preserved the completed workflow, 21 agent notebooks, 6 artifacts and queue
history, and then restored the final release.

## PWA workflow benchmark

Authenticated run `e6578320-8f3c-46d7-94e5-cbb6687742d2` completed at the live
source with 21/21 agents, 21/21 handoffs, zero failed tasks, 6/6 artifacts,
successful mid-run recovery and post-completion restart checks. Runtime was
39.55 minutes with 31,211 input and 5,451 output tokens at USD 0.00 local
monetary cost.

All 21 notebook APIs passed creation, read, private-access denial, keyword and
semantic search, update and version-history checks. Post-restart retrieval was
21/21, backup integrity was `ok`, and 21 notebooks plus 63 records restored
from the verified backup.

## Procurement assessment

The original cohort remains unchanged at **97.33/100 PARTIAL**. A separate
fresh cohort used `qwen2.5:14b-instruct-q4_K_M` for all 42 reviews and the
fence-tolerant strict JSON contract:

- Valid structured verdicts: 42/42
- PASS / FAIL verdicts: 37 / 5
- Agent execution: 21/21 substantive
- Acceptance checks: 29/30
- Fresh verdict: **98.33/100 PARTIAL**
- Manifest: 67/67 files verified

The five reviewer FAIL outcomes remain findings rather than being converted to
PASS. The deterministic business checks all pass; the peer-review PASS gate
therefore remains open.

## Public browser acceptance

The public endpoint is protected by Cloudflare Access. An unauthenticated
request redirects to the Access sign-in page. Automated Edge navigation in the
existing Owner profile returned `net::ERR_BLOCKED_BY_CLIENT` before the
ORQEVIA page loaded. A transient 503 was reported during the cutover; current
checks show the Access login page returning 200 and the origin returning 200
with the public Host header. Post-login browser acceptance is still unclaimed.

The authenticated LAN equivalent passed the Projects page, Owner session,
hybrid notebook search, and artifact download. Public Owner interaction remains
an open acceptance item; no browser or authentication boundary was disabled.

## Evidence

- `C:\Users\Admin\Documents\ABEX\operations\orq001-workflow-deployment-20261020`
- `C:\Users\Admin\Documents\ABEX\operations\orq002-pwa-benchmark-20261020`
- `C:\Users\Admin\Documents\ABEX\operations\orqevia-release-d4e2479-20261020`
- `C:\Users\Admin\Documents\ABEX\assessments\ORQ-002-Procurement-20261020`
- `C:\Users\Admin\Documents\ABEX\assessments\ORQ-002-Procurement-20261020-Fresh14B`
- `C:\Users\Admin\Documents\ABEX\operations\orq002-fresh14b-independent-verification.json`
