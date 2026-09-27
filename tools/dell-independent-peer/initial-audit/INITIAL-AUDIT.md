# Dell peer initial audit — 27 September 2026

**Verdict: FAIL. Native Dell commissioning remains incomplete.**

The exact published source was independently acquired and checked. Tests ran in a cloud Linux workspace, not on native Dell. Passing software assertions are PROVEN_BY_AUTOMATION. ABEX production and the candidate were not modified.

**CANDIDATE SHA:** 091e2f919edb1711b5a9e88404818095fa32b537

**IMAGE:** UNPROVEN: no independently acquired immutable successor image/digest bound to this SHA

**SOURCE INTEGRITY:** PASS / PROVEN_BY_AUTOMATION: 509 blob hashes, full tree and exact commit matched; clean checkout; relevant authentic history restored. Exact successor freeze receipt not established.

**CANONICAL REGRESSION:** FAIL: complete tests/ run 987 passed, 2 failed, 0 skipped. Both failures share receipt newline defect. Canonical subset 516 pass; PWA/Dell Node60 pass; Dell packaging3 pass; reproducible source manifest pass.

**DELL ADVERSARIAL REGRESSION:** FAIL / PROVEN_BY_AUTOMATION, independently authored outside ABEX. Voice8:3 pass5 fail (2 P2 groups plus defensive gaps); candidate-provenance API accepts fabricated claims/dirty/wrong checkout. Native Dell run UNPROVEN.

**P0:** None identified in performed scope; absence system-wide UNPROVEN

**P1:** None identified in performed scope; absence system-wide UNPROVEN

**P2:** 4 finding groups: stale speech callback/attempt identity; missing post-start terminal watchdog; receipt newline-dependent digest; candidate-provenance checker trusts self-authored verification and does not bind checkout. Checker findings have no demonstrated production caller.

**MIGRATION:** BLOCKED: independent target-image migration rehearsal not performed

**ROLLBACK:** BLOCKED: independent target/previous-image rollback rehearsal not performed

**IDENTITY:** UNPROVEN: native Dell binding and exact authenticated ABEX deployment identity absent

**AUTHORITY:** UNPROVEN overall; provenance checker challenge FAIL; no demonstrated production authority bypass

**PROVENANCE:** FAIL in candidate checker/evidence-binding scope; exact source integrity separately passes

**SESSION/RECONNECT:** Scoped canonical software tests pass; native-device/session/restart acceptance UNPROVEN

**PWA/CACHE:** Scoped Node source tests pass; installed iPhone cache/version/offline transitions UNPROVEN

**PHYSICAL GATES REMAINING:** Owner audible iPhone English/Chinese Read Aloud with exact deployed revision; Owner tap/Stop/replay and interruptions; Actual PWA cache/update/offline/reconnect behavior; Physical Dell commissioning and scheduled/restart observation

**UNPROVEN CLAIMS:** This chat runs on physical Dell; Permanent native independent certification service installed; DeepSeek credential/live API/native Codex profile operational; Current successor image and approved/deployed identity correspondence; Independent migration and rollback readiness; Full mandatory adversarial coverage on native Dell; Longer-duration reliability and prediction accuracy; Physical audibility or root cause of historical iPhone silence

**PROMOTION VERIFICATION:** FAIL: do not issue PROMOTION_VERIFICATION_PASS for this source

**PASS / FAIL / BLOCKED:** FAIL, with additional BLOCKED gates

**EVIDENCE ARTIFACT:** See EVIDENCE.md for archive and SHA-256; raw initial and successor verification runs retained

**next_action:** ABEX repairs via successor; native Dell Codex completes START-HERE.md. No repair to audited candidate or ABEX production occurred.

## Preserved findings

1. Late speech start can revive stopped UI and misattribute an old event to a new attempt.
2. A started utterance has no terminal watchdog if end/error never arrives.
3. Committed receipt bytes use LF; acceptance helpers expect the SHA-256 of CRLF-transformed bytes.
4. The candidate-provenance checker accepts fabricated evidence and unbuilt-artifact claims, plus dirty or wrong checkout state. No production call site was found.

Two defensive voice API exception paths and a synchronous callback fault injection are preserved separately; native-browser applicability is not established. Malformed candidate metadata also raises uncaught TypeError in the checker. These are not inflated into demonstrated production breaches.

The historical voice report accidentally used PROVEN_BY_INDEPENDENT_DELL for cloud tests. Its original bytes are preserved, and challenges/voice-091e2f9/ERRATUM.md corrects every such classification. Read the correction with that report.

## Toolkit repairs

The independent review found and corrected misleading promotion PASS after deployment drift, omitted physical/unproven post-audit fields, inconsistent outage status and corrupt-binding error handling. Initial failing snapshots and successful independent rechecks remain in review/. Current gate tests do not establish a trusted native runner.

## History and scope

Initial full run:981 pass8 fail, with seven failures initially hitting missing history. Authentic Git objects were then independently acquired and hash-verified. New full run:987 pass2 fail, both receipt newline binding. Initial logs were preserved; the current result supersedes only their checkout limitation, not their existence. Source remained unchanged.

Canonical subset:516 pass; client Node:60 pass; Dell packaging:3 pass. The full failure takes precedence over subset success. Image, migration, rollback, native Windows scheduling and physical audio were not performed.

DeepSeek is prepared as a bounded advisory reviewer; no live credential or paid API request was used. Native Codex launch remains blocked pending effective local connector/sandbox verification. The exact-file API helper is the bounded integration path.

The passive native watcher is prepared, not installed. The cloud observation schedule is separately recorded in the final handoff and is never native Dell proof.
