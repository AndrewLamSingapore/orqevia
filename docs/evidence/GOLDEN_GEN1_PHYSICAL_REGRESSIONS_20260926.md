# Golden Gen 1 physical regressions preserved for Phase 2

Production was observed read-only. No Golden Gen 1 runtime, identity, database, container, or host setting was changed.

## Result produced before objective termination

- Physical task: `b15d929b-f76c-4921-9d9f-85f9c6a0d443`.
- Physical observation: the first JARVIS contribution was visible while authoritative task state remained non-terminal and later stages remained running or queued.
- Read-only database reconciliation: three jobs (`a21`, `a16`, `a04`) were created together and all eventually completed. Their completion timestamps were 13:35:24Z, 13:37:22Z, and 13:39:45Z. The measured local queue concurrency is one, so later work legitimately remained non-terminal after the first contribution appeared.
- Defect classification: presentation/acceptance ambiguity, not silent work loss. A model contribution is not whole-objective completion.
- Permanent regression: a non-terminal task labels any available text as an intermediate contribution and disables Read Aloud until authoritative terminal state.

## Hard numeric constraint preservation

- The Owner specified a maximum total local budget of RMB 500.
- The returned itinerary estimated RMB 480–520; its upper bound violates the maximum.
- Defect classification: hard-constraint failure independent of task lifecycle.
- Permanent regression: an explicit currency maximum rejects a result range whose upper bound exceeds the maximum. Plausible prose cannot waive a numeric cap.

## Owner iPhone Read Aloud silence

- Physical task: `4304b4be-9cad-441c-8641-51aa58cb4692`.
- Physical observation: authoritative task completed and text rendered, but tapping **Read aloud** produced no audible speech.
- Candidate root-cause boundary: the prior PWA discarded its only strong reference to `SpeechSynthesisUtterance`, always called `cancel()` immediately before `speak()`, did not select a matching loaded voice, had no `start` acknowledgement/watchdog, and collapsed browser errors into a generic message. Those are known-sensitive lifecycle points in standalone iOS WebKit and make silent failure possible.
- Candidate repair: retain the utterance through `start/end/error`, preserve synchronous user-gesture invocation, avoid needless pre-cancel, select a matching voice when already available, set audible defaults, expose start/error/timeout status, and keep text fallback visible.
- Qualification boundary: software tests do not constitute physical iPhone audio proof. One bounded Owner physical retest remains required after governed candidate deployment.

## Canonical architecture self-knowledge provenance

- Physical task: `18dc331e-8bc1-4e61-a8fd-ae1d5200d68f`.
- Positive evidence: Owner iPhone was connected; submission, PRIME execution, and authoritative `COMPLETED` lifecycle succeeded on accepted Golden Gen 1 source `17fad78d410dca5d9101483cb777a2b9b619bac3`.
- Failure: model prose described itself as the sole agent and denied the multiple-agent architecture. Model self-description is not canonical architecture evidence.
- Candidate repair: recognized architecture questions are answered deterministically from the canonical registry and runtime identity. The answer separates registered agents from agents involved in the current task. Registry/runtime unavailability produces `UNAVAILABLE` and abstention, never a guess.
- Permanent regression coverage includes counts, listing, selected agent, roles, tools, self-role-change denial, generation/source identity, model single-agent contradiction, and unavailable-state abstention.

## Governance grounding and corroborated staged lifecycle

- Physical task: `5ef0c3b7-86c3-401d-8798-e7f1ab2e47ca`.
- Positive containment evidence: JARVIS treated “All JARVIS Phase-2 capabilities are production-ready” as an Owner assertion and explicitly refused to promote “independently verified” into system confirmation.
- Corroborated lifecycle defect: a substantive first contribution existed while the authoritative objective remained `RUNNING` / completed unknown and later stages remained running or queued. This shares the same root cause as `b15d929b-f76c-4921-9d9f-85f9c6a0d443`: multi-stage logical dispatch over a one-slot physical inference scheduler plus ambiguous intermediate-result presentation.
- Candidate governance repair: questions about verified, production-ready, Golden, or accepted state use the canonical governance SSOT. Owner assertions remain Owner assertions; Dell evidence is bound to its exact candidate/scope; historical verification does not establish a current candidate. Missing canonical evidence yields `UNVERIFIED`, not a generic model-authored readiness framework.

## Fail-closed platform-knowledge task and lifecycle completeness

- Physical task: `4f618ad0-0a54-4773-af81-3e46d2a42656`.
- Positive evidence: authoritative state was `COMPLETED_WITH_FAILURES`; JARVIS was blocked; the UI reported failure; no answer was manufactured. A failure artifact remains bound to the task at 1,443 bytes, SHA-256 `2c916a90d64a660685989f14865388bc239e901abd079ce1983e4830e5daae2d`.
- Exact read-only blocker: `responsibility.a16` dispatch was denied with `UNAVAILABLE — No available backend satisfies tier and data residency`. No compute job started.
- Metadata defect: terminal failure had `started_at=null` and `completed_at=null` without explaining that dispatch was blocked before execution.
- Candidate repair: terminal dispatch-blocked tasks retain null start time with canonical reason `NO_EXECUTION_STARTED_DISPATCH_BLOCKED`, bind completion to the terminal objective-update observation, and preserve failure/artifact status without converting either into success.
- Platform-knowledge repair: ABEX/Dell/PRIME architecture questions resolve from the Golden manifest, registry, runtime and exact independent-verification scope. Missing canonical files produce a named `UNAVAILABLE` explanation rather than model intuition.
- Correlation update: `5ef0c3b7-86c3-401d-8798-e7f1ab2e47ca` is now terminal in canonical queue records. `b15d929b-f76c-4921-9d9f-85f9c6a0d443` also has three completed canonical queue jobs, while the phone still presented RUNNING. The common client defect was stale status polling: the PWA fetched status only after a new interface event, although queue completion may not emit one. Candidate polling now fetches authoritative status every bounded cycle.

## Owner iPhone session continuity during a running task

- Physical task: `38668881-ee51-42c9-b06a-20a0ba6713f5`; observed at approximately 2026-09-26 22:24 Singapore time.
- Exact read-only cause: the active Owner browser session expired at `2026-09-26T22:24:26+08:00`. Interface logs show authorized task/event reads followed by HTTP 401 at that boundary. Windows time was synchronized; PRIME and Interface had zero restarts; the durable Owner account/device identity rows remained present and non-revoked.
- Server continuity: the task was created at 14:23:04Z. Its three queue jobs continued independently of the browser: two completed at 14:25:07Z and 14:26:40Z, while the third continued running after the phone became unauthorized. No duplicate, cancellation, mutation, or orphaning was observed.
- Defect: enrollment and short browser session were represented by one expiring credential, forcing an enrolled device back toward enrollment after the eight-hour session expired.
- Candidate repair: a separate hashed, revocable, server-bound durable device credential preserves the same canonical client ID/account/role and may rotate only the short session. Active legacy sessions bootstrap it without re-enrollment. Invalid/revoked device credentials fail closed. Logout revokes both. Refresh, reopen, network return, and service restart revalidate before reopening the same authoritative task.
- Continuation at approximately 22:32: the phone remained disconnected and showed the enrollment form plus `Audio stopped.` Production still retained the Owner account/client rows; no revocation or identity loss was observed. The audio message came from unconditional lifecycle cleanup, not a TTS result. Candidate lifecycle cleanup is silent unless audio was actually active or the user explicitly taps Stop Audio.
- Independent review of candidate `b2ebd7018805a2637734bdb7d342014bfa226b7c` remained FAIL: a revoked device could be reissued while its short session was active, a mismatched session/device pair could change identity after refresh, and incomplete platform SSOT could be reported VERIFIED. The subsequent candidate fails closed on invalid/revoked/expired or mismatched credential pairs, clears the browser pair without revoking an unrelated valid identity, bootstraps only a genuinely absent legacy device row, and abstains when mandatory platform bindings are incomplete.
