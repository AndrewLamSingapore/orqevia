# Independent Read Aloud falsification record

Candidate: `091e2f919edb1711b5a9e88404818095fa32b537`

Verdict for this scope: **FAIL**. Two P2 lifecycle defects are independently reproduced in deterministic software fault scenarios. They must be fixed by ABEX in a successor candidate, then retested independently. This report does not certify source-tree provenance, production deployment, native browser behavior, or physical audibility.

Execution environment: Linux verification workspace, Node `v24.19.0`, 2026-09-27 UTC. This is not execution on physical Dell Windows hardware. All browser and speech APIs in these tests are controlled mocks. No ABEX production calls or candidate edits were made.

## Inputs and preserved execution

| Input | SHA-256 |
|---|---|
| `clients/pwa/voice.mjs` | `db8fd83608eae5848cb0ba07c15d078f09e804bee72c175cfc16649f89f20c61` |
| `clients/pwa/voice-tests.mjs` | `cde672c2c827af0ef07bfa3a128e17cd5e3ac63a4dbb6030134af06560257108` |
| `clients/pwa/app.mjs` | `90d5f8be4b5ae433faa3ff16da39f49ba2d0b0dc9fa5e131c2d1c38c9ac2dbfa` |

`voice-independent.test.mjs` independently exercises ownership, STOP races, missing terminal events, and API exceptions. It verifies the input voice source SHA-256 before testing. Its first execution is preserved in `run-20260927T030353Z.tap` with detailed state transitions in `observations.ndjson`: **8 tests, 3 pass, 5 fail, exit 1**. The `.tap` filename contains Node's human-readable test reporter output, not strict TAP serialization.

`voice-sync-independent.test.mjs` adds one explicit reentrancy fault injection: **1 fail, exit 1**, preserved in `supplemental-sync-run.tap`. Reentrancy has not been demonstrated in native WebKit and is kept separate from confirmed promotion-blocking findings.

The adjacent `SHA256SUMS` binds all report, test, and log files. Preserve this directory as the first-run evidence. To rerun without changing its append-only observation file, copy the test scripts to a fresh sibling directory at the same depth and run `node --test voice-independent.test.mjs` and `node --test voice-sync-independent.test.mjs` there.

## P2-DV-01: late start callbacks defeat STOP and misattribute attempt identity

Source: `clients/pwa/voice.mjs`, `speak()` on line 8, `utterance.onstart`; `speechTrace()` on line 7. Unlike `finish`, `onstart` does not check that its captured utterance is still owned. `speechTrace` reads the mutable current `this.speechAttempt`, instead of an immutable attempt identifier captured with the callback.

Minimal reproduction A, DV-01:

1. Call `voice.speak('Result')` and retain that utterance.
2. Call `voice.stop()`; owned state is cleared and the message is `Audio stopped.`
3. Deliver the old utterance's queued `onstart` callback.
4. Observe `Reading your result. TTS start; attempt=1` with UI state `speaking`, although `voice.utterance === null` and `voice.speaking === false`.

Minimal reproduction B, DV-02:

1. Start attempt 1, stop it, then start attempt 2 without delivering attempt 2's start.
2. Deliver attempt 1's old `onstart`.
3. Observe `Reading your result. TTS start; attempt=2`; the callback came from attempt 1.

Impact: a stale event can revive stopped UI and fabricate a start observation for the wrong attempt. In `app.mjs` lines 59–60, that callback updates the visible message and displays Stop audio. This undermines the instrumentation intended to diagnose the historical Read Aloud failure. It does not establish an authority/security escalation.

Classification: **PROVEN_BY_INDEPENDENT_DELL** for deterministic callback handling under an injected late event. Native event-delivery frequency and physical iPhone reproduction: **UNPROVEN / REQUIRES_PHYSICAL_DEVICE**. Proposed severity P2 for the violated lifecycle and evidence-identity contract; no claim that this was the historical physical root cause.

ABEX successor requirement: reject all callbacks from non-owned/retired attempts; capture immutable attempt identity for every trace; test STOP, replacement, and late start/end/error. The passing DV-07 confirms old end is currently guarded, so the defect is specifically inconsistent callback guarding.

## P2-DV-02: start without end/error has no terminal timeout

Source: `clients/pwa/voice.mjs` line 8. The single 8-second timer acts only when `!started`. Once a start event occurs, the callback does nothing, and no later timer exists.

Minimal reproduction, DV-03:

1. Speak `One short sentence.`
2. Deliver its start event; suppress subsequent end/error to model a stalled speech service.
3. Advance the controlled clock one hour.
4. Observe `voice.utterance` still retained, `voice.speaking === true`, UI still `Reading your result`, and zero timers remaining.

Impact: loss of a terminal event leaves a permanently active operation without terminal error evidence or automatic recovery. A second tap performs Stop rather than a fresh read. The simulated hour consumes no real waiting or significant resources; it is not a real long-duration reliability observation.

Classification: **PROVEN_BY_INDEPENDENT_DELL** for absent-event handling; native/iPhone incidence **UNPROVEN**. Proposed severity P2 because bounded failure detection is missing for the exact start-to-end/error/timeout lifecycle requested.

ABEX successor requirement: introduce a bounded, text-length-aware terminal watchdog after start, with guarded cleanup and a distinct timeout reason. Preserve Owner acceptance as a separate physical gate.

## Supplemental robustness observations

| Cases | Result | Interpretation |
|---|---|---|
| DV-04 / DV-05 | Injected `getVoices()` or utterance-constructor exception escapes `speak()`; zero error messages | Voice enumeration, creation, and setup are outside the try/catch. This is a proven containment gap for injected API faults. A native trigger is unproven; do not inflate it into a confirmed iPhone P1/P2. |
| DV-06 | PASS: a `synthesis.speak()` exception clears owned state and displays error | **PROVEN_BY_INDEPENDENT_DELL**, limited to this mock exception path. |
| DV-07 | PASS: old end cannot finish current attempt | **PROVEN_BY_INDEPENDENT_DELL**, limited to stale end handling. |
| DV-08 | PASS: normal mocked invocation/start/end emits lifecycle messages and clears state | **PROVEN_BY_INDEPENDENT_DELL** for software sequencing; no audible outcome observed. |
| DV-09 | Synchronous start/end inside `synthesis.speak` is overwritten with `Starting Read aloud` afterward | Defensive reentrancy weakness reproduced with a mock. Native WebKit synchronous delivery is unproven; excluded from primary P2 count. |

## Instrumentation and physical boundary

| Requested stage | Candidate evidence | Remaining gap |
|---|---|---|
| User gesture | `navigator.userActivation.isActive` snapshot; Read aloud handler directly calls `speak` | Mock activation is not a physical tap or OS speech permission proof. |
| Speech API invocation | `TTS invoked` after `synthesis.speak` returns | Invocation does not prove service acceptance, audio routing, or sound. Reentrancy can corrupt stage ordering. |
| Voice availability/resolution | Snapshot count, matching-language count, requested language | `utterance.voice = null` delegates choice. No actual resolved voice identifier is recorded; no `voiceschanged` observation. Resolution remains **UNPROVEN**. |
| Utterance creation | Source creates and retains an utterance | No distinct creation stage; construction exceptions evade reporting. |
| Start | `TTS start` callback | Ownership and attempt binding fail DV-01/DV-02. Start is an engine event, not audible proof. |
| Audible physical outcome | No sensor or Owner acceptance event | **REQUIRES_PHYSICAL_DEVICE**. Only Owner physical observation can close this gate. |
| End/error/timeout | End, error, no-start timeout available | No start-without-end timeout. Engine end is not proof sound was heard. |
| Preserved trace | `app.mjs` writes the latest callback into one message element | Previous stages are overwritten; these source paths do not preserve a complete durable event history. Dell's local mock record is durable evidence of tests only. |

No physical iPhone, installed PWA, volume setting, output route, real voice availability, real network transition, or audible result was observed here. Historical physical failures remain historical reports; no new physical acceptance is asserted. Long-running reliability remains **REQUIRES_LONGER_OBSERVATION**.

## Handoff

ABEX must create a new frozen successor; Dell must obtain it independently and rerun these challenges plus canonical regression. Do not repair this frozen source and call the result independent. This scope returns **FAIL** and cannot authorize promotion. Overall image, migration, rollback, identity, authority, provenance, and deployment gates belong to the aggregate audit and are not certified by this report.
