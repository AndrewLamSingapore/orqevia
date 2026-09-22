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
- Read-only DeepSeek handoff for code review/inspection questions: `scripts/read-only-deepseek.ps1` (documented in `docs/READ_ONLY_DEEPSEEK.md`).

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
