# STATUS.md — Single source of truth

Last updated: 22 September 2026

**This file replaces and supersedes every previous SSOT document — technical, course-study, and job-search alike.** Any older SSOT file (on ABEX, in a repo, or elsewhere) is now historical only. Do not treat any prior SSOT document as current once this file exists. Archive or delete the old ones once this file is confirmed good — do not maintain both in parallel.

## How to use this file

One rule governs everything below:

**An item only belongs in "Verified" if Lam personally checked the evidence himself.**

Examples:

- commit hash personally checked on GitHub;
- URL personally opened;
- command personally run;
- physical device personally watched;
- email personally received;
- interview personally attended.

A confident agent report is never sufficient on its own.

If you are an AI agent updating this file:

- You may add items to "Claimed, not independently checked" or "Known broken / open".
- You may NOT move an item into "Verified".
- Only Lam may do that after personally checking evidence.
- Never delete a line from "Known broken / open".
- When a problem is fixed, move it to "Resolved" with date and evidence.
- When uncertain, understate confidence.
- Update this file on real events, not on a schedule.
- Commit and push every legitimate update.

---

## PRIME / VELYQUA / ABEX

### Verified (Lam personally confirmed the evidence)

- [item] — [exact evidence checked] — [date confirmed]

### Claimed, not independently checked

- New ABEX trust epoch: PRIME commissioning reported passing (Docker, identity, registry, Ollama gates) — reported by Codex, 19 Sep 2026 — not yet spot-checked by Lam
- Wife Member physical acceptance: last known result COMPLETED_WITH_FAILURES / stale UUID reuse — root cause fix reported in progress — not yet retested physically
- "JARVIS Codex" desktop launcher created on the Dell — shortcut `C:\Users\User\OneDrive\Desktop\JARVIS Codex.lnk` targeting `C:\Users\User\AppData\Roaming\npm\codex.cmd` with working directory `C:\Users\User\Documents\JARVIS`, no administrator flag, no embedded credentials — launch observed by Codex starting `codex.exe`, 22 Sep 2026 — not yet launched by Lam

### Known broken / open

- Original Kingsand SSD: unrecoverable, permanently unavailable — confirmed by ABEX repair technician, 19 Sep 2026
- Agent registry identity mapping (A12/A13 vs A17/A18): unresolved discrepancy between frozen design and deployed reality as of 15 Sep forensic audit — not yet re-verified against the new epoch
- Direct Codex -> DeepSeek API path: configured with official DeepSeek Codex setup; provider-side usage evidence still pending Lam verification
- "JARVIS Codex" launcher cannot be pinned to the taskbar by automation: Windows 11 (build 26200) exposes no supported "Pin to taskbar" shell verb, so one manual pin action by Lam is still outstanding — observed 22 Sep 2026

### Notes

- W3-01 (Web3 governance design) preserved independently at authority-engine repo, commit 4681521e74b9a1d45161889a49fa57eb612c6d45 — design reference, not deployed capability.
- VELYQUA source preserved independently at commit 4ecf65eec8dca0926fe01c3e9c34488e80764470 (full hash confirmed on the Dell clone, 22 Sep 2026).
- This file is the only current status authority. The former machine SSOT `governance/operational-manifest.json` and the generated `governance/JARVIS_Resume_Checkpoint.generated.md` remain as machine component references only; status claims in them are superseded here as of 22 Sep 2026.
- Read-only DeepSeek handoff for code review/inspection questions: `scripts/read-only-deepseek.ps1` (documented in `docs/READ_ONLY_DEEPSEEK.md`). Exercised 22 Sep 2026 against `https://api.deepseek.com` with model `deepseek-flash`, which returned an answer from the repository content. Provider-side usage evidence is still Lam's to confirm.
- Agent registry identity mapping evidence (22 Sep 2026, source only): `config/agent_registry.json` declares `named_operating_roles` as `{"A12 Builder":"a17","A13 Test Engineer":"a18"}`, `app/agent_registry.py` refuses to load a registry that changes that mapping, and `app/engineering_api.py` accepts only those two design role labels and maps them to a17/a18. This shows the A12/A13-versus-A17/A18 relationship is an intentional, code-enforced bridge in the current source; it does not verify the deployed ABEX runtime.
- Stale result/revision evidence (22 Sep 2026, source only): `clients/pwa/revision-tests.mjs` pins revision-scoped presentation — current-only results, no previous-answer leakage on completion, and previous results labelled and shown only for the same task and revision.
- Spoken agent-label leakage fixed in source (22 Sep 2026): the PWA "read result" button spoke the raw internal agent id (for example "a13"). Read-aloud now uses a label-free `spokenText()` while the screen keeps the label, with a regression test in `clients/pwa/revision-tests.mjs`. Source-level fix only; not yet deployed to ABEX.

---

## Course study

### BCG RISE Business Data Analytics

#### Verified

- Enrolled in BCG RISE Business Data Analytics course — [confirm evidence: enrollment confirmation email/portal]

#### Claimed, not independently checked

- Graduation date: 9 October 2026 — as stated by Lam; not tied to a specific confirmation document here yet

#### Known broken / open

- (none logged yet)

### Generation Singapore — SCTP Cloud Support & DevOps Engineer

(with Microsoft & Temasek Polytechnic)

#### Verified

- Learner Particulars step completed — WhatsApp confirmation from Generation Singapore, screenshot dated Monday (prior week)
- Learner Email Address obtained — same confirmation

#### Claimed, not independently checked

- Trainee Agreement Form submitted — stage shown as pending internal review
- Registration under Temasek Polytechnic's STEP portal — Generation Singapore states details will be sent by email; not yet received/confirmed

#### Known broken / open

- SkillsFuture registration/confirmation not visible in portal — Lam asked Generation Singapore directly at 12:35 PM (prior week) whether he needs to register for SkillsFuture himself; reply did not directly answer this — still open as of 20 Sep 2026

---

## Job search — analytics-enabled supply chain / consulting roles

### Verified

- Interview attended: S.F. Express (Singapore) Pte Ltd — interviewer Shawn, Operations Management Manager — held Wednesday, 9 Sep 2026, 2:00 PM, at 7 Changi South Street 2, Xilin Districentre #03-03, Singapore 486415 — evidence: WhatsApp scheduling thread and Lam personally attended

### Claimed, not independently checked

- (log applications here as they go out, with company, role, date and current stage)
- Outcome of S.F. Express interview — not yet known/logged

### Known broken / open

- (none logged yet)

---

## Resolved

Move items here from "Known broken / open" only after the underlying fix exists.

Do not convert an item to Verified yourself.

---

## Portfolio products — production deployment (22 September 2026)

### Verified (only Lam may promote an item here)

- (nothing promoted by an agent; each item below still needs Lam's own spot-check)

### Claimed, not independently checked

- **Authority Engine V2 is in production** at https://authority-engine-app.vercel.app from `main` `71fcc69ab0d75ccd7a52f47fb2bbc458a606f424` (PR #75). Reported by Codex from the Dell, 22 Sep 2026 — acceptance run 56/56 (routes, 320–1440 px overflow, theme switching, Talk tablist keyboard navigation, evidence filters with no scroll jump, reduced motion, self-hosted fonts) with axe-core reporting no serious or critical violations in light and dark, plus a passing `/api/health` smoke. Not yet spot-checked by Lam.
- **Living Worlds is in production** at https://game-platform-wine-nine.vercel.app from `main` `3450bf88a4805025a0be47cf23860c28129688fb` (PRs #28, #29). Reported by Codex from the Dell, 22 Sep 2026 — the production smoke reported that exact revision and a live guest journey (The Ashen Gate) resolved exactly one authoritative turn in about eight seconds with fresh choices, an advanced world clock, no stranded choice buttons, the outcome announced through a live region, no console errors and no horizontal overflow at 390 px (17/17 checks). The turn reported `reasoner: adaptive-gm`, so the live model path executed rather than the deterministic fallback. Not yet spot-checked by Lam.
- **The Portal is in production** at https://the-portal-ten.vercel.app from `main` `2d78c516b901f46375aa21149008ff0a2c2d7448` (PRs #60, #61, #62, #59, plus the `/v2` CSP repair and the page-icon repair). Reported by Codex from the Dell, 22 Sep 2026 — production smoke reported that exact revision, the card journey passed 14/14 against the live site, and a six-route production crawl (`/`, `/v2`, `/living`, `/inhabitants`, `/evidence-lab`, `/card/unknown-card-id`) reported zero console errors and zero failed requests. Not yet spot-checked by Lam.
- **Two Portal defects found by crawling production and repaired (22 Sep 2026).** The `/v2` "Evidence & Ancestry" page carried its entire behaviour in an inline script and `@import`-ed Google Fonts, while the deployment sends `script-src 'self'` and `style-src 'self'`: both were blocked, so the page rendered its shell with no data, no grid and no drawer. Behaviour now lives in same-origin `/v2.js` and the blocked font import is gone; production now renders 20 cards with the drawer working and zero console errors. Separately, four of five pages declared no icon, so every visit logged a `/favicon.ico` 404; all pages now declare `favicon.svg`. A new `scripts/page-csp-contract.mjs`, wired into `npm run verify`, fails the build if any page reintroduces an inline script, an external stylesheet or a missing icon. Not yet spot-checked by Lam.
- **Living Worlds double-submission verified in production (22 Sep 2026).** Two choice activations dispatched back-to-back in the same task produced exactly one `gm-turn` call (HTTP 200), transcript 1 → 3 turns, a fresh set of three choices, the outcome notice "Turn 1 advanced · Day 1." and zero console errors. This verifies the deployed client guard; it does NOT cover the server-side concurrency path, which still needs the unapplied migration and the redeployed functions (see below). Not yet spot-checked by Lam.
- **STATUS.md authority migration completed across the portfolio (22 Sep 2026).** authority-engine (#77), game-platform (#30), the-portal (#66), prime (#95, #97), sky-tablet (#8) and velyqua (#72) now each begin `AGENTS.md` with STATUS.md as the single status and evidence authority and state that the retired SSOT/reconciler apparatus must not be resurrected and that SSOT must never be maintained in parallel with STATUS.md. `SSOT.json` holds exactly one explicit `status_authority` pointer plus its "component pointer only" note, and `scripts/check_ssot_pointer.py` now fails if that pointer is lost or if the file regains status semantics (keys `status`, `current_status`, `verification`, `verified`). velyqua's `SSOT.md` was demoted to the same wording. No repository holds a competing status authority. Not yet spot-checked by Lam.
- **Canonical STATUS.md pointer is live** in the SSOT of authority-engine, the-portal, sky-tablet and velyqua (PRs #74, #59, #7, #71). Reported by Codex, 22 Sep 2026.

### Known broken / open

- **Living Worlds server-side hardening is committed but NOT deployed.** Migration `20260922090000_turn_integrity_hardening.sql` is unapplied and the `gm-turn`, `game-action` and `join-campaign` functions still run pre-hardening code in production, so production still serves wildcard CORS on those functions and the old check-then-act idempotency ordering against a concurrent duplicate. Deploying needs Supabase credentials and CLI access that are not present on the Dell (no `supabase`/`vercel` CLI, no access token, no environment file). Recorded 22 Sep 2026.
- **Portal private PRIME surface does not exist yet** — `/prime`, `/api/prime` and `/reports` all return 404 in production (checked 22 Sep 2026), so nothing private can leak, and nothing private can be read either. Authentication decision required; see `the-portal/docs/PRIME_PRIVATE_DOMAIN_DECISION.md`.
- **ABEX runtime remains unverified from the Dell** — `/api/jarvis-status` reports `prime.state = unverified`, `runtime_revision = null`, `runtime_host = ABEX`, `verified_at = null` (22 Sep 2026). Independent host evidence is still required.
- **The profile repository pointer PR is blocked** — andrewlamsingapore PR #18 cannot merge: the base branch policy prohibits it and auto-merge is disabled for that repository. Bypassing protection with administrator privileges was not used. Recorded 22 Sep 2026.
- **Stale dependency PRs remain open and unreviewed** — authority-engine #65/#66/#71/#72/#73 and velyqua #67/#68/#69/#70 (Dependabot bumps). Deliberately not merged: none is required for current work and unreviewed upgrades are the risk the operating rules warn about. velyqua #64 ("bounded PRIME session transport adapter") is a draft whose own body states the authenticated relay and production authority admission are still prerequisites. Recorded 22 Sep 2026.
- **Supabase production work is blocked by one missing credential on this Dell (probed 22 Sep 2026).** The Supabase CLI itself is available (`npx supabase@latest` reports 2.117.0), but it cannot authenticate: `supabase projects list` returns `LegacyPlatformAuthRequiredError: Access token not provided`. `SUPABASE_ACCESS_TOKEN` is absent from both the User and Machine environment scopes, `~/.supabase/access-token` does not exist, there is no Supabase entry in Windows Credential Manager, no Supabase or Vercel secret exists in any repository's Actions secrets or environments, and the browser-automation session is unavailable ("Codex auth token is unavailable"). Consequently these remain unperformed and NOT verified: migration `20260922090000_turn_integrity_hardening.sql` application; deployment of `gm-turn`, `game-action`, `join-campaign`; `ALLOWED_ORIGIN` configuration; runtime RLS verification; server-side concurrency/idempotency proof; and the Portal private PRIME surface (`/prime`, `/api/prime`, `/reports` all still return 404 and therefore fail closed). Required: run `supabase login` on this Dell, or provide `SUPABASE_ACCESS_TOKEN` (plus the project's database password for migrations). No secret value may be written here.
