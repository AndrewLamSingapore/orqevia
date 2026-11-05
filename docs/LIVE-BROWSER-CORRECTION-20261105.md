# Current-session browser compatibility correction

Actual browser acceptance of main9b7166e exposed three cookie selectors that
still recognized only the legacy session name. Newly enrolled ORQEVIA sessions
could use the authenticated mission, depot, experiment and knowledge APIs, but
Projects and Academy returned401; OSIP and Collective returned400 after verified
middleware identity fell through the incorrect compatibility branch.

The correction recognizes both existing cookie names in `workflow_bridge`,
`sovereign_plane_bridge` and `local_knowledge_bridge`. Session validation, OWNER
and account scoping, origin/CSRF checks and caller-identity rejection are retained.
No production configuration or permission is relaxed. No fourth legacy-only
selector was found in the active application audit.

The new compatibility suite enrolls through real pairing and interface session
middleware, exercises all eight affected read paths under current and legacy
cookies, and checks MEMBER, forged-header, invalid/expired/revoked session,
account-mismatch and cross-origin rejection. Focused suites passed85 cases;
the final compatibility module passed14 cases and is included in canonical CI.

Actual saved-run data also exposed a64-character identifier overflowing a mobile
summary. Shared summary wrapping now preserves the complete identifier and full
JSON access without widening the page. The regression reproduced the original
622-pixel document at a320-pixel viewport, then passed at320 and390 pixels across
Chromium, Firefox and WebKit (24 cases). Page and worker caches advance together
to v45; eighteen cache/packaging checks passed without clearing drafts or sessions.

These defects were discovered after the original batch was merged and deployed.
They require one consolidated corrective PR and release. Keep the first release,
its exact receipts and rollback evidence. The already qualified native knowledge
service and independent TLS collector do not require another reload. Final
source, CI, deployment and actual browser acceptance remain separate evidence.
