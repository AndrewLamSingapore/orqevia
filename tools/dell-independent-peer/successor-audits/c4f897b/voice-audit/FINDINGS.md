# Successor Read Aloud and phone-sound audit

Candidate: `c4f897b0d311a4c15be27df52f14d4c9e6ab5702`; parent: `091e2f919edb1711b5a9e88404818095fa32b537`.

Scope verdict: **FAIL**. The previous two proposed P2 lifecycle defects remain reproducible. The new phone-sound diagnostic introduces an unowned, unbounded audio-context lifecycle, proposed P2. No candidate repairs or production calls were made.

Every observation here is **PROVEN_BY_AUTOMATION**, independently authored outside ABEX and executed in the cloud Linux workspace with mocked browser/audio APIs. Native Dell execution is **UNPROVEN**. Physical iPhone audibility remains **REQUIRES_PHYSICAL_DEVICE**, closed only by Owner physical observation. A simulated clock is not elapsed physical observation. Candidate freeze/publication authority and image receipt are not established by this scoped audit.

| Input | SHA-256 |
|---|---|
| `clients/pwa/voice.mjs` | `040e9406333c7577264bc5a3215d9031a688ffc2564d89ad59b916facf5d1078` |
| `clients/pwa/app.mjs` | `6c279b7044276f9ab91905c64c2f55409d15cdb84be680186ed27773ca6ec5eb` |
| `clients/pwa/voice-tests.mjs` | `6d7c15bd1c360814f70edf9cfa4b3b77bce732ec077f19b72a6ad85a742f6d7f` |

## Preserved results

| Run | Outcome |
|---|---|
| Canonical `voice-tests.mjs` | 11 pass, 0 fail; exit 0 |
| Unmodified portable independent regressions | 4 pass, 5 fail, 1 optional synchronous-event test skipped; exit 1 |
| New independent AudioContext challenges | 2 pass, 5 fail; exit 1 |

The portable suite includes a separate source-digest check; counts do not represent independently proven product features. Raw logs and structured observations are in `canonical-voice-run.tap`, `portable-regression.tap`, and `audio-output-run.tap`. The portable test file snapshot and input receipt are preserved alongside this report. No previous FAIL artifacts were changed.

## Continuing P2-DV-01: stale start and wrong attempt attribution

`voice.mjs` line 8 still assigns `utterance.onstart` without checking current ownership. `speechTrace` on line 7 still reads mutable `this.speechAttempt`.

DV-01: invoke speech, STOP, deliver the old start callback. The message returns to `Reading your result` despite null owned utterance and false speaking flag.

DV-02: invoke attempt 1, STOP, invoke attempt 2, deliver attempt 1's old start. It emits `TTS start; attempt=2` even though attempt 2 has not started.

This remains a deterministic software lifecycle/receipt-identity defect. Native callback incidence and the historical iPhone failure's root cause remain UNPROVEN.

## Continuing P2-DV-02: no terminal timeout after start

`voice.mjs` line 8 still schedules only a no-start timeout. After start, missing end/error leaves the short utterance owned and `speaking=true` after a simulated hour, with no timers remaining (DV-03).

The new elapsed-time field improves diagnostic detail; it does not provide a bounded failure transition.

## New proposed P2-DA-01: diagnostic sound is not owned, cancellable, or bounded

`testOutput()` on line 9 keeps its AudioContext and oscillator only in local variables. `stop()` on line 10 has no reference to either. `app.mjs` lines 59–61 displays Stop audio for the diagnostic, wires it to `voice.stop()`, and also calls that method on hidden/offline/logout transitions.

Minimal deterministic reproductions:

- **DA-01:** create a running mock context with `voice.testOutput()`, then call `voice.stop()`. No immediate oscillator stop and no context close occur. Only the initial stop at audio time 0.65 remains scheduled. The user-visible Stop audio control does not control this audio.
- **DA-02:** create a suspended context whose asynchronous `resume()` remains pending; advance the controlled wall clock 60 seconds. No context close, error, or timeout occurs. A scheduled stop on the suspended audio clock cannot provide a wall-clock bound.
- **DA-03:** repeat the diagnostic three times under pending resume. Three live suspended contexts remain. This is a small safe reproduction, not an exhaustion attack.

Impact: cancellation, lifecycle cleanup, and bounded resource use fail in the diagnostic intended to isolate the audible-output problem. Proposed P2 covers the combined ownership/recovery defect, not three separate incidents. Native suspension incidence remains UNPROVEN here.

ABEX successor acceptance: own at most one active diagnostic context; STOP/hidden/logout must release it; bound resume/start/end by wall clock; guard late callbacks from retired diagnostics; preserve a specific terminal reason.

## Additional asynchronous failure gaps

DA-06 rejects `context.resume()` with a mock `NotAllowedError` using a real rejected Promise in an isolated Node child. The child records an unhandled rejection and the only visible state remains `Audio output control started; context=suspended`. Exit 17 is intentional evidence.

DA-07 delivers the normal end event, then rejects `context.close()` with a mock `InvalidStateError`. The child again records an unhandled rejection. Neither `void context.resume()` nor `void context.close()` installs rejection handling, and surrounding synchronous try/catch cannot catch it.

These are proven containment gaps for injected API failures, with native triggers UNPROVEN. They support the diagnostic's failure-handling remediation; they are not counted as additional confirmed physical P2 incidents. The old `getVoices()` and utterance-constructor exception gaps also remain (DV-04/05).

DA-04 passes: synchronous oscillator-creation failure displays an error and closes the context when close resolves.

## Audibility boundary and improvements

DA-05 passes: the tone end message says, `Confirm whether the tone was physically audible.` This explicitly preserves the Owner physical boundary. The start text, `A short tone should be audible`, is predictive wording, not evidence that sound was heard. Software `onended` and `context=running` cannot close the physical gate.

The successor adds elapsed time, enumerated default voice details, visibility trace output, `selected=system-auto-unobservable`, and a dedicated audio-status element. These improve diagnostic visibility. Actual system-selected voice resolution remains unobservable and is now correctly labeled. The audio-status element still stores only the latest message, rather than a durable full stage history.

A tone physically heard would prove that diagnostic tone's audible path on that device at that time; it would not prove the separate speech-synthesis path or read-aloud result. Speech and tone require distinct physical acceptance observations.

## Reproduction and next gate

Run the portable suite outside the candidate with:

```bash
PRIME_CANDIDATE_ROOT=/workspace/scratch/e46efedd3273/successor-c4f897b/source \
PRIME_CANDIDATE_SHA=c4f897b0d311a4c15be27df52f14d4c9e6ab5702 \
EXPECTED_VOICE_SHA256=040e9406333c7577264bc5a3215d9031a688ffc2564d89ad59b916facf5d1078 \
node --test --test-reporter=tap /workspace/scratch/e46efedd3273/dell-peer/challenges/voice-regression.test.mjs
```

Run the new scoped challenge with `node --test --test-reporter=tap audio-output-independent.test.mjs` from this audit directory, capturing a new log instead of overwriting the first one. This challenge binds the exact successor digest and intentionally retains the failed assertions. The surrounding verifier owns sandboxing and machine/source provenance.

Return FAIL to ABEX. ABEX must create another successor; the verifier must independently acquire and retest it. This audit cannot authorize promotion and does not establish image, migration, rollback, deployment, or physical acceptance.
