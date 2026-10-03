# Isolated cockpit checkpoint

Discovery conclusion: **NO RECOVERABLE IMPLEMENTATION FOUND** after bounded inspection of ABEX repositories/worktrees, branches, stashes, recent commits, source/build paths, and Docker image names for cockpit/Brain identifiers. Existing `clients/pwa` is the accepted mobile workspace, not the requested multi-surface cockpit.

Source base: cached verified `origin/main` `4806694afd2729761fa108c9d64a48d8a47f54f9`. Branch: `feature/jarvis-prime-cockpit`. Worktree: `C:/Users/Admin/Documents/ABEX/worktrees/jarvis-prime-cockpit`. Initial checkout clean. Production remains image `sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5` and `/pwa/` untouched.

Boundary: ABEX host stability UNQUALIFIED. This branch is isolated source work only. No production routing, service restart, network interruption, or promotion. Real offline, restart, and physical mobile acceptance are deferred. Test harnesses must not be called production evidence.

## Owner-requested pause, 2026-09-30

Current isolated WIP: `clients/cockpit/` has a static navigation shell, an existing-Interface-contract client, and a Brain graph projection over retrieved task/job/agent/artifact records. It is **not** integrated, deployed, or production-qualified. It has no new backend graph/retrieval API, no proven dev same-origin authentication path, and no full test suite. Missing source classes are explicitly UNAVAILABLE. The live accepted `/pwa/` was not changed.

Executed safe checks before pause: `node --check clients/cockpit/app.mjs`, `node --check clients/cockpit/brain.mjs`, and `node clients/cockpit/brain-tests.mjs` (8 passing assertions). These are syntax/unit checks only, not an E2E result. Known WIP defect: the Ask flow does not yet prepare a durable retry key before submitting, so do not use it for real objectives or call it accepted. Other unimplemented gates include actual backend graph data, governed memory/search, registry truth, responsive browser testing, security review, safe E2E, offline/restart/mobile qualification, and promotion.

Resume from this branch and this file. First inspect `git status`, then repair the Ask durable-retry path and test it using isolated fixtures, not live production. Continue with the existing PWA authority boundary; never bypass session/cookie/origin controls to make a localhost preview appear connected. No automatic engineering resume from the quiet health monitor.

## Branch-only Ask retry repair — 2026-10-03 SGT

The Ask path now computes the existing PWA submission digest and awaits the
strict IndexedDB retry-journal preparation before its first POST. Exact-text
uncertain retries reuse the pending idempotency key; a changed objective is
blocked until the pending attempt is reconciled. Acknowledgment storage errors
are no longer discarded, and a later status-refresh failure is distinguished
from an unconfirmed submission. The cockpit continues to use the existing
same-origin Interface contract and stores neither objective text nor secrets.

Isolated fixture evidence: five Ask regression tests passed, including
prepare-before-POST, uncertain replay, storage failure before POST, and failed
acknowledgment replay. The combined Ask/PWA Node suite passed 49/49; Brain
assertions passed 8/8; `node --check` passed for the cockpit app and Ask helper;
`git diff --check` passed. These checks do **not** establish browser,
same-origin session, production, offline/restart, or physical-device acceptance.
The preceding 30 September defect statement is retained as historical WIP;
only this isolated branch repair supersedes that specific source defect.
All other cockpit qualification gates above remain open. No production
deployment, service restart, identity change, or Golden image change occurred.
