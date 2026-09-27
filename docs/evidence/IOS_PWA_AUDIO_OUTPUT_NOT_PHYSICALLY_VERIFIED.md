# IOS_PWA_AUDIO_OUTPUT_NOT_PHYSICALLY_VERIFIED

Status: **PARKED — PHYSICAL FAIL / NOT ACCEPTED**  
Production critical: **NO — explicit Owner scope waiver**  
Next action: **NONE until separately authorized**

## Preserved evidence

- Physical Owner-iPhone tests repeatedly produced no confirmed audible Read Aloud output.
- Web Speech emitted `start` while the Owner physically heard no sound.
- One exact trace was: `TTS start; attempt=2; gesture=1; lang=en-SG; voices=70; matching=26; standalone=1; visibility=visible; speaking=1; pending=0; paused=0`.
- Other preserved observations showed different voice availability, including zero available/matching voices.
- Golden Gen 1 displayed a false-active state (`Reading your result. Tap Stop audio to interrupt.`) without audible output.
- Physical audibility of the independent Web Audio control was not established before the Owner parked the issue.
- Browser lifecycle callbacks, `speechSynthesis.speaking`, automated browser tests and generated tone completion are not physical-audio evidence.

## Tested generations

- Golden Gen 1: `17fad78d410dca5d9101483cb777a2b9b619bac3`
- Rejected candidate: `1f50580dcaf774a02f74b18e5a1d532c4e74b628`
- Rejected candidate: `091e2f919edb1711b5a9e88404818095fa32b537`
- Accepted non-audio Phase-2 source carrying bounded diagnostics: `b171253566e7c879283d2aacf699ae6c1ec8988e`

## Current hypothesis boundary

The observed failure lies at or below the iOS standalone-PWA audio-output boundary. Evidence does not yet distinguish device output/routing from Web Speech implementation behavior because the independent test tone lacks confirmed physical observation. Do not resume voice-selection changes, claim a root cause, or call Read Aloud PASS without a separately authorized physical investigation.

## Production rule

Read Aloud is excluded from Golden Gen 2 acceptance. The current UI may contain diagnostic controls inherited from the frozen source, but their presence is not a verified-feature claim. This issue remains separate from PRIME task execution, identity, authority, provenance and non-audio PWA acceptance.
