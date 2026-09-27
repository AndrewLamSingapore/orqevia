# Authoritative classification correction — read before the historical report

Candidate: `091e2f919edb1711b5a9e88404818095fa32b537`

This erratum supersedes the proof classifications in `READ-ALOUD-FINDINGS.md`. The original report, tests, logs, observations, and `SHA256SUMS` are preserved unchanged as historical evidence.

**All execution in this directory occurred in a cloud Linux workspace with mocked speech/browser APIs. No execution on physical Dell Windows hardware was observed. The correct classification is PROVEN_BY_AUTOMATION, independently authored outside ABEX. Native Dell execution remains UNPROVEN.** Naming the challenge suite “Dell” does not establish that it ran on Dell.

| Historical report location | Incorrect classification | Correct classification |
|---|---|---|
| P2-DV-01, classification paragraph, line 42; DV-01 and DV-02 stale callbacks | PROVEN_BY_INDEPENDENT_DELL | PROVEN_BY_AUTOMATION for deterministic mocked callback behavior; independently authored outside ABEX; native Dell UNPROVEN |
| P2-DV-02, classification paragraph, line 59; DV-03 missing terminal watchdog | PROVEN_BY_INDEPENDENT_DELL | PROVEN_BY_AUTOMATION for deterministic missing-event behavior; independently authored outside ABEX; native Dell UNPROVEN |
| Supplemental table, line 68; DV-06 invocation exception handling PASS | PROVEN_BY_INDEPENDENT_DELL | PROVEN_BY_AUTOMATION for this mock exception path; independently authored outside ABEX; native Dell UNPROVEN |
| Supplemental table, line 69; DV-07 stale end handling PASS | PROVEN_BY_INDEPENDENT_DELL | PROVEN_BY_AUTOMATION for this mock stale-event path; independently authored outside ABEX; native Dell UNPROVEN |
| Supplemental table, line 70; DV-08 lifecycle sequencing PASS | PROVEN_BY_INDEPENDENT_DELL | PROVEN_BY_AUTOMATION for mock software sequencing; independently authored outside ABEX; native Dell UNPROVEN |

The same corrected classification applies to all other observations and fault injections in this directory. The subtask response and messages that called these “independent Dell” evidence must be interpreted only as independent authorship outside ABEX, never machine provenance.

The reproduced outputs and FAIL verdict do not change. The two proposed P2 findings concern deterministic source behavior under injected late/missing events. Their native iPhone incidence is UNPROVEN. DV-04, DV-05, and DV-09 remain supplemental injected robustness gaps with native triggers UNPROVEN; they are not additional confirmed native P2 incidents.

Physical iPhone speech remains REQUIRES_PHYSICAL_DEVICE and can be closed only by Owner physical observation. Long-duration reliability remains REQUIRES_LONGER_OBSERVATION; a simulated one-hour clock advance is not elapsed physical observation. No artifact here qualifies as PROVEN_BY_INDEPENDENT_DELL, native device acceptance, or production verification.

Original unchanged `SHA256SUMS` SHA-256: `48a53cc5d28fd1de106e491fdf197fd9907e0e5abdc850415b62f33ef58e4be5`.

`CORRECTION-SHA256SUMS` separately binds this erratum and the preserved original manifest; it does not replace the original evidence manifest.
