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
- Authenticated PRIME evidence bridge repaired and deployed from `main` `5b962fcab2c770e0c31fb80094939317b81791d4` (PRs #102 and #103) — reported by Codex from ABEX, 22 Sep 2026 — deployed image label and interface environment both reported that exact revision; PRIME, interface and Ollama containers were healthy; all five active SQLite stores returned `quick_check = ok`; an authenticated aggregate-only contract probe returned READY, 21 canonical agent identities, 29 separately labelled historical responsibilities, 10 objectives, 3 completed compute jobs, 3 stored/non-revoked PWA sessions (0 currently active because all were expired), 9 artifacts and 26 action records, with `read_only=true`, `physical_actuation=false`, and no record contents or credentials. Not yet spot-checked by Lam.
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

- **Portal private PRIME surface now exists, is deployed and fails closed** - the earlier "does not exist yet / 404 in production" note is superseded. Re-confirmed directly against https://the-portal-ten.vercel.app on 22 Sep 2026: `/prime` 200, `/reports` 200, `/api/prime` 401, `/api/prime/report` 401, `/api/meta?route=prime` 401, and anonymous REST reads of `prime_identities` and `prime_reports` return 200 with no rows. The private surface was added by the-portal PRs #67 to #71 and repaired by PR #74, canonical `main` `92026791f32636e523a68f9613b0f58fc56784c5`. Recorded by Codex, not yet independently checked by Lam.

- **Ambiguous PRIME external agent count and legacy zero counters resolved in the authenticated bridge** — deployed `main` `5b962fcab2c770e0c31fb80094939317b81791d4`, 22 Sep 2026. `/interface/v1/health` now exposes `canonical_agent_count=21`, labels the 29 migrated items as `historical_responsibility_count`, queries aggregate-only evidence from `objectives.db`, `compute-queue.db`, `pwa-sessions.db`, the artifact store and action ledger, and classifies retired `app.main` metrics as `REPLACED` or `NOT_APPLICABLE` rather than fabricated zeroes. Reported by Codex; not yet independently checked by Lam.
- **PWA session-count ambiguity found during deployment verification and repaired** — the first bridge revision could truthfully report zero active sessions while hiding three preserved expired session records. PR #103 split the metric into `stored_count`, `non_revoked_count`, and `active_count`; deployed evidence reported 3, 3, and 0 respectively. Reported by Codex, 22 Sep 2026; not yet independently checked by Lam.

---

## Portfolio products — production deployment (22 September 2026)

### Verified (only Lam may promote an item here)

- (nothing promoted by an agent; each item below still needs Lam's own spot-check)

### Claimed, not independently checked

- **PRIME password-recovery submit repaired, deployed and verified against production (22 Sep 2026).** Reported by Codex, not yet spot-checked by Lam and NOT owner-verified. Defect: on Lam's fresh Supabase recovery link, `/prime` correctly showed "Set a new password" and consumed the fragment, but tapping "Save password and continue" did nothing at all. Cause: the deployment sends `connect-src 'self'` on every route, the browser refused the direct Supabase Auth `PUT /auth/v1/user` before it left the page, `fetch` rejected with a bare `TypeError`, and the async submit listener had no `catch`, so the rejection was swallowed. Reproduced against the deployed build before any change at 1280x900 and 390x844 (`states: ['recovery'] -> ['recovery']`, console CSP violation, `pageerror: Failed to fetch`). Repair shipped through the-portal PR #74, canonical `main` `92026791f32636e523a68f9613b0f58fc56784c5`: the identity origin is allowed in `connect-src`; every recovery submit now ends in exactly one of two visible outcomes - continuation into private operations, or a plain-language actionable message for a mismatch, a short password, a rejected password, an unusable link, an unreachable identity service, a failed private read or an unexpected failure; passwords are no longer cleared until the update succeeds; an expired session is cleared; Sign out is bound per state (three sections each declared `id="signOut"`, so the signed-in button was dead and its handler also threw on a missing `#reportDetail`); a recovery link opened on `/reports` hands the session to `/prime`; query-string recovery material PRIME cannot consume (`?code=`, `?error_description=`) is explained and stripped from the address bar; and `scripts/page-csp-contract.mjs` now fails if any shipped client script fetches an origin the deployed policy blocks. Evidence: production `/prime` sends the corrected policy and serves `prime.js` byte-identical (SHA-256 `93C53D7D8653011D4C68A2C6F18AA64F87AC3C98B46815E5BEBD418FC76EF3FF`) to canonical main; `npm run prime:recovery` passes 24/24 checks against the live site at 1280x900 and 390x844, while the same suite failed 19 of 22 against the pre-repair production build, including the silent no-op itself; production smoke asserted revision `92026791f32636e523a68f9613b0f58fc56784c5` exactly and the browser smoke reported 20 cards, 12 graph nodes, `ARCHIVE ONLINE 6.5.0`; `/`, `/card`, `/v2`, `/living`, `/inhabitants` and `/evidence-lab` remain 200 with the public Portal unchanged; anonymous REST reads of `prime_identities` and `prime_reports` with only the publishable key return 200 with no rows, so RLS still denies anonymous private data; `/api/prime` and `/api/prime/report` return 401 without a token, with a garbage token, and before any parameter validation; no service-role credential exists in the repository or in any browser bundle. CI: PR checks `verify`, `ssot` and `verify-v2` passed, and the post-merge Quality run's `production-smoke` job ran "Verify the deployed PRIME recovery submit path" successfully against production. Still outstanding and unclaimed, each requiring one real owner authentication: Owner mapping, Member mapping, unmapped-user denial, Owner and Member authorization, Member-to-Owner escalation denial, cross-user isolation, IDOR on the private tables, session restore, expiry, logout and post-logout denial with a real identity, cache isolation, PWA/mobile acceptance and the authenticated production red-team. The single genuine human boundary is Lam opening one fresh recovery link and performing one owner password reset; no password, token or recovery URL was requested, printed or persisted at any point.

- **Authority Engine V2 is in production** at https://authority-engine-app.vercel.app from `main` `71fcc69ab0d75ccd7a52f47fb2bbc458a606f424` (PR #75). Reported by Codex from the Dell, 22 Sep 2026 — acceptance run 56/56 (routes, 320–1440 px overflow, theme switching, Talk tablist keyboard navigation, evidence filters with no scroll jump, reduced motion, self-hosted fonts) with axe-core reporting no serious or critical violations in light and dark, plus a passing `/api/health` smoke. Not yet spot-checked by Lam.
- **Living Worlds is in production** at https://game-platform-wine-nine.vercel.app from `main` `3450bf88a4805025a0be47cf23860c28129688fb` (PRs #28, #29). Reported by Codex from the Dell, 22 Sep 2026 — the production smoke reported that exact revision and a live guest journey (The Ashen Gate) resolved exactly one authoritative turn in about eight seconds with fresh choices, an advanced world clock, no stranded choice buttons, the outcome announced through a live region, no console errors and no horizontal overflow at 390 px (17/17 checks). The turn reported `reasoner: adaptive-gm`, so the live model path executed rather than the deterministic fallback. Not yet spot-checked by Lam.
- **The Portal is in production** at https://the-portal-ten.vercel.app from `main` `2d78c516b901f46375aa21149008ff0a2c2d7448` (PRs #60, #61, #62, #59, plus the `/v2` CSP repair and the page-icon repair). Reported by Codex from the Dell, 22 Sep 2026 — production smoke reported that exact revision, the card journey passed 14/14 against the live site, and a six-route production crawl (`/`, `/v2`, `/living`, `/inhabitants`, `/evidence-lab`, `/card/unknown-card-id`) reported zero console errors and zero failed requests. Not yet spot-checked by Lam.
- **Two Portal defects found by crawling production and repaired (22 Sep 2026).** The `/v2` "Evidence & Ancestry" page carried its entire behaviour in an inline script and `@import`-ed Google Fonts, while the deployment sends `script-src 'self'` and `style-src 'self'`: both were blocked, so the page rendered its shell with no data, no grid and no drawer. Behaviour now lives in same-origin `/v2.js` and the blocked font import is gone; production now renders 20 cards with the drawer working and zero console errors. Separately, four of five pages declared no icon, so every visit logged a `/favicon.ico` 404; all pages now declare `favicon.svg`. A new `scripts/page-csp-contract.mjs`, wired into `npm run verify`, fails the build if any page reintroduces an inline script, an external stylesheet or a missing icon. Not yet spot-checked by Lam.
- **Living Worlds double-submission verified in production (22 Sep 2026).** Two choice activations dispatched back-to-back in the same task produced exactly one `gm-turn` call (HTTP 200), transcript 1 → 3 turns, a fresh set of three choices, the outcome notice "Turn 1 advanced · Day 1." and zero console errors. This verifies the deployed client guard; it does NOT cover the server-side concurrency path, which still needs the unapplied migration and the redeployed functions (see below). Not yet spot-checked by Lam.
- **Living Worlds physical acceptance correction and redesign deployment (22 Sep 2026).** Lam physically inspected the preceding Game Platform UI on iPhone and reported that it still looked old; that physical result superseded the earlier machine pass and is recorded as **FAIL / PENDING RECHECK**. Root cause was concrete: `authority-family.css` loaded before the legacy inline and atmosphere styles, and the overlay itself was too small to materially change world discovery or active story. PR #34 moved the material redesign after all legacy CSS and introduced visibly distinct editorial discovery, cinematic world cards, active-story panels and numbered decision controls. Production `/api/health` now reports revision `2ae2223e647a0a5da2c78f984208dd436d6ce83e`, equal to canonical `main`; the full repository suite passes, fresh browser checks at desktop and 390×844 show the redesign stylesheet last, 544 px mobile world cards, 88 px decision targets, no horizontal overflow and no console warnings/errors. Physical reacceptance remains pending; Codex does not claim it on Lam's behalf.
- **Portal mobile collision repaired and deployed (22 Sep 2026).** The requested cross-surface bug hunt found the mobile cinematic controls colliding with identity/status chrome at 390×844 and one target below 44 px. PR #75 places the three controls in a dedicated collision-free row, hides duplicate archive status on narrow screens and locks each target to 44 px or more. The complete Portal verification chain and production browser check pass with no horizontal overflow or console warnings/errors. Production `/api/health` reports revision `e8b93faa71a56ec8f7560798eb2290d1863a872e`, equal to canonical `main`.
- **Sky Tablet rechecked after the UI acceptance request (22 Sep 2026).** Canonical `main` revision `121f5ec18ad2b095140b753e4bfdcec7a7990967` has a successful GitHub production deployment receipt for `https://sky-tablet.vercel.app`. All 15 scene, camera, portrait framing, texture/lifecycle and layout tests pass; a fresh 390×844 production render has zero horizontal overflow, a 44 px sound target and no console warnings/errors. No new Sky Tablet defect was reproduced in this pass.
- **STATUS.md authority migration completed across the portfolio (22 Sep 2026).** authority-engine (#77), game-platform (#30), the-portal (#66), prime (#95, #97), sky-tablet (#8) and velyqua (#72) now each begin `AGENTS.md` with STATUS.md as the single status and evidence authority and state that the retired SSOT/reconciler apparatus must not be resurrected and that SSOT must never be maintained in parallel with STATUS.md. `SSOT.json` holds exactly one explicit `status_authority` pointer plus its "component pointer only" note, and `scripts/check_ssot_pointer.py` now fails if that pointer is lost or if the file regains status semantics (keys `status`, `current_status`, `verification`, `verified`). velyqua's `SSOT.md` was demoted to the same wording. No repository holds a competing status authority. Not yet spot-checked by Lam.
- **Canonical STATUS.md pointer is live** in the SSOT of authority-engine, the-portal, sky-tablet and velyqua (PRs #74, #59, #7, #71). Reported by Codex, 22 Sep 2026.

### Known broken / open

- **Living Worlds server-side hardening is committed but NOT deployed.** Migration `20260922090000_turn_integrity_hardening.sql` is unapplied and the `gm-turn`, `game-action` and `join-campaign` functions still run pre-hardening code in production, so production still serves wildcard CORS on those functions and the old check-then-act idempotency ordering against a concurrent duplicate. Deploying needs Supabase credentials and CLI access that are not present on the Dell (no `supabase`/`vercel` CLI, no access token, no environment file). Recorded 22 Sep 2026.
- **ABEX runtime remains unverified from the Dell** — `/api/jarvis-status` reports `prime.state = unverified`, `runtime_revision = null`, `runtime_host = ABEX`, `verified_at = null` (22 Sep 2026). Independent host evidence is still required.
- **The profile repository pointer PR is blocked** — andrewlamsingapore PR #18 cannot merge: the base branch policy prohibits it and auto-merge is disabled for that repository. Bypassing protection with administrator privileges was not used. Recorded 22 Sep 2026.
- **Stale dependency PRs remain open and unreviewed** — authority-engine #65/#66/#71/#72/#73 and velyqua #67/#68/#69/#70 (Dependabot bumps). Deliberately not merged: none is required for current work and unreviewed upgrades are the risk the operating rules warn about. velyqua #64 ("bounded PRIME session transport adapter") is a draft whose own body states the authenticated relay and production authority admission are still prerequisites. Recorded 22 Sep 2026.
- **Living Worlds server hardening is DEPLOYED and runtime-verified in production (22 Sep 2026).** Supabase authentication was established on the Dell and the `game-platform` repository was linked to the existing production project `vtrfgckzpjgtmqsnumur` ("Game Platform", `ap-southeast-1`, ACTIVE_HEALTHY) — matched independently against `app.js` and `README.md`, not guessed. Reported by Codex, 22 Sep 2026, not yet spot-checked by Lam:
  - `gm-turn`, `game-action` and `join-campaign` were redeployed from the hardened source (`npx supabase functions deploy`, project `vtrfgckzpjgtmqsnumur`). JWT verification remains enabled on all three.
  - `ALLOWED_ORIGIN=https://game-platform-wine-nine.vercel.app` is set as a project secret.
  - CORS runtime evidence: preflight from the canonical origin returns `Access-Control-Allow-Origin: https://game-platform-wine-nine.vercel.app` with `Vary: Origin`; preflight from an arbitrary origin returns `Access-Control-Allow-Origin: null`; an unauthenticated POST returns `401`. The gateway-generated 401 still carries `Access-Control-Allow-Origin: *` (it is produced before function code runs and contains no data); every function-generated response now carries the restricted origin. Left as-is deliberately: disabling `verify_jwt` to restyle a gateway 401 would weaken authentication.
  - Server-side idempotency/concurrency, exercised directly against the production function: two identical concurrent `gm-turn` requests sharing one `client_request_id` returned `200` and `409` — exactly one authoritative turn (`turn:2`), the duplicate rejected as `turn_in_flight`, and the hardened response reported `diagnostics.audit = "recorded"` with `narration_lint` present. An ordinary turn resolved exactly once alongside it.
  - Runtime RLS, exercised through the production REST API with the publishable key: anonymous campaign read returns `[]`; the owning user can create and read back their campaign (`201`); a **different authenticated user** receives `[]` for that campaign id and cannot modify it (PATCH leaves the title unchanged); anonymous read by id returns `[]`.
  - **Migration note (not applied, not needed for production):** `20260922090000_turn_integrity_hardening.sql` cannot be pushed by the CLI because the production history records the project's migrations under different version names than the repository files, and `supabase db push` refuses rather than risk re-running old migrations. Rewriting that history was deliberately not done. The migration's own purpose — reconciling the audit columns on a rebuilt database — is already satisfied in production, proven by the hardened function's successful write to `execution_status` / `verification_status` / `outcome_status` / `decision_record` (it returned `audit: "recorded"`). The repository keeps the migration as the fix for a fresh database.
- **Portal private PRIME remains unbuilt (22 Sep 2026).** `/prime`, `/api/prime` and `/reports` still return 404 and therefore fail closed. Supabase Auth + RLS is now technically available for it, but the surface itself (identity mapping to the existing Owner/Member semantics, RLS policies, private API and reports routes, session lifecycle, adversarial tests) has not been implemented. Recorded as known-open rather than claimed.
- **Portal private PRIME: private data plane deployed and runtime-verified; identity mapping and routes outstanding (22 Sep 2026).** Reported by Codex, not yet spot-checked by Lam. (1) Identity model: prime/app/client_auth.py authenticates a single Owner client by comparing a bearer credential with PRIME_SPINE_TOKEN using hmac.compare_digest, so there is no Owner/Member user directory to map into; the Portal schema holds exhibition and relay tables only; the only RLS-backed role model in the estate is game-platform campaign_members with OWNER/GM/PLAYER/SPECTATOR. (2) Migration-history drift solved WITHOUT rewriting history: a scratch workdir with the three matching migration files plus placeholders for the 31 recorded-but-unnamed remote versions reduced the plan to one migration; the dry run printed Would push these migrations: 20260922120000_prime_private_surface.sql before applying anything; production history was not repaired, renamed or rewritten. (3) Applied the-portal/migrations/20260922120000_prime_private_surface.sql (additive only): public.prime_identities maps a Supabase auth user to an immutable person_key plus role OWNER/MEMBER plus authority; public.prime_reports holds reports with OWNER/MEMBER visibility; public.prime_identity() resolves the caller; policies grant a caller only its own mapping row and a report only to a mapped OWNER, or to a MEMBER when the report is member-visible; both tables FORCE ROW LEVEL SECURITY; confirmed in a read-only production schema dump. (4) Runtime RLS evidence: anonymous REST reads return 200 with an empty array for both new tables, identical to the control table campaigns. An earlier probe that appeared to 404 was a quoting defect in my own test command, not a schema or cache problem; it was corrected with URL-encoded queries plus a control before any conclusion was drawn. (5) Outstanding, and why this is not complete: /prime, /api/prime and /reports do not exist yet and return 404; no Owner or Member identity row exists, so unmapped-user, Owner and Member authorization cannot be demonstrated; no adversarial matrix has been run against a private surface. Remaining work is ordinary implementation in the-portal (server-side Supabase Auth validation, Owner/Member mapping, private API and reports routes, session lifecycle, adversarial, cache and mobile tests). The one genuine external action is Lam first real sign-in (magic link or email/password) in Supabase project vtrfgckzpjgtmqsnumur, which creates the auth user that the Owner mapping depends on; no secret needs to be pasted into Codex and the mapping row is inserted server-side afterwards.
- **Private PRIME recovery flow repaired and verified in production (22 Sep 2026), later pass.** Reported by Codex. Defect: a Supabase password-recovery link reached /prime with the implicit-flow material in the URL fragment, but the client only read localStorage, so the token was ignored, the ordinary sign-in form rendered, and the fragment stayed visible in the address bar. Repaired: the client parses the fragment on load and on hashchange, stores the session, strips authentication material from the URL immediately via history.replaceState, and renders a dedicated Set a new password state that updates the password through Supabase Auth before continuing. Verified against production at 390x844 with a synthetic fragment: only the recovery state visible, URL hash empty, set-password form present, no request carrying the token, zero console errors; a normal visit still shows the sign-in state. The recovery panel had also been nested inside the sign-in section by my first attempt, which would have hidden it; that was fixed. Production revision 90d69f5de8 plus the preceding PRs: /prime 200, /reports 200, /api/prime 401, /api/prime/report 401, public routes (/, card, /v2, /living, /evidence-lab) all 200. Still outstanding and unclaimed: Owner and Member mapping, unmapped-user denial with a real identity, Member-to-Owner escalation, cross-user and IDOR on the private tables, session restore/expiry/logout, cache isolation between identities, PWA acceptance and the authenticated red-team - all require Lam to complete one real authentication.
- **Private PRIME is LIVE in production and fail-closed (22 Sep 2026).** Reported by Codex, not yet spot-checked by Lam. Production revision 449ede734b1f5b702c06170d5c6bd2738bf5dc42 equals canonical main. Observed directly against https://the-portal-ten.vercel.app: /prime 200, /reports 200, /api/prime 401, /api/prime/report 401 with and without an id, the direct function path /api/meta?route=prime 401, a garbage bearer token 401, and POST 401 (authentication is decided before method or parameters). Headers on /api/prime: Cache-Control private, no-store, max-age=0; Vary: Authorization; X-Robots-Tag: noindex, nofollow; CSP unchanged. Public Portal regression: /, /card/PTL-1929-5B5B27B097, /v2, /living, /inhabitants, /evidence-lab all 200 with no login wall. Direct anonymous REST reads of prime_identities and prime_reports return 200 with no rows (RLS), matching the control table. Two genuine defects were found and repaired during this pass: (1) the production deployment failed because Vercel counts every function file and this project is capped at 12 - asserted by the repository own deployment contract - so the two nested private function files took it to 14 and the build failed, leaving production on an older revision; the endpoints now live in the consolidated api/meta.js router reached by rewrites, and the deployment succeeds at 12/12; (2) /api/prime/report answered 400 before authenticating, so parameter validation preceded the authorization boundary; authentication is now decided first. NOT yet verified, because it needs a real authenticated identity: unmapped-user denial, Owner mapping, Member mapping, Member-to-Owner escalation, cross-user and IDOR behaviour on the new tables, session restore/expiry/logout, cache isolation between identities, and mobile/PWA acceptance of the private pages. Those remain outstanding and are not claimed.
