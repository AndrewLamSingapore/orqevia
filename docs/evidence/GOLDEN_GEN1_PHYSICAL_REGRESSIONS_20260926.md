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
