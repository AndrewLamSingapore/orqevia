# PRIME independent cloud audit — 27 September 2026

**FAIL for audited source `c4f897b0d311a4c15be27df52f14d4c9e6ab5702`.** Five software defect groups are assessed P2. Four continue from the earlier audit; the new phone-sound diagnostic adds an ownership, cancellation and cleanup defect. ABEX must produce and freeze a successor. No production or candidate repair was performed.

This is cloud Linux evidence, classified **PROVEN_BY_AUTOMATION**. It does not establish native Dell commissioning, native Dell execution, physical iPhone audibility or production deployment identity. The source was authenticated and acquired independently; an exact freeze receipt and candidate image were not established.

The mutable branch subsequently advanced to `b171253566e7c879283d2aacf699ae6c1ec8988e`. That publication is tracked separately below. Neither the test counts nor this FAIL are transferred to the newer SHA.

## Required candidate record

| Field | Result |
|---|---|
| CANDIDATE SHA | `c4f897b0d311a4c15be27df52f14d4c9e6ab5702` — audited published source; exact freeze not established |
| IMAGE | BLOCKED: immutable candidate image/platform digest and source-to-image binding unavailable |
| SOURCE INTEGRITY | PASS for acquired source: 509 blobs, full commit and tree checked; clean detached source and execution copy; tree `36dd016eacae9c5495a6119ef00cab7e8ee44d36` |
| CANONICAL REGRESSION | FAIL: full Python 987 pass, 2 fail, 0 skipped. Canonical subset 516 pass overlaps the full run. Client Node 63 pass; Dell packaging 3 pass |
| DELL ADVERSARIAL REGRESSION | Native Dell BLOCKED. Independent cloud challenges FAIL: continuing speech lifecycle defects, new diagnostic lifecycle defect, and provenance counterexamples reproduced |
| P0 | None observed in this limited audit; absence across production is UNPROVEN |
| P1 | None observed in this limited audit; absence across production is UNPROVEN |
| P2 | Five assessed root-cause groups, detailed below |
| MIGRATION | BLOCKED: no native candidate-specific predecessor-data migration rehearsal receipt |
| ROLLBACK | BLOCKED: no candidate-specific rollback image/data rehearsal or retained production rollback identity established |
| IDENTITY | Exact source verified; physical Dell identity and authenticated ABEX source/image/runtime binding UNPROVEN |
| AUTHORITY | FAIL in the scoped provenance-helper trust check; complete Owner/Member and production authority isolation UNPROVEN |
| PROVENANCE | FAIL: receipt byte binding and helper acceptance of self-authored evidence/unchecked checkout; exact candidate manifest and image provenance BLOCKED |
| SESSION/RECONNECT | Canonical assertions ran; independent native expiry/recovery/restart/offline end-to-end qualification UNPROVEN |
| PWA/CACHE | 63 client Node tests passed in their fixture scope; actual cache/version transitions, offline/reconnect and physical PWA behavior UNPROVEN |
| PHYSICAL GATES REMAINING | Owner-observed iPhone speech and diagnostic tone, bound separately to actual device/browser or PWA, source/image and attempt; Stop/replay, interruptions, offline/reconnect and cache transitions |
| UNPROVEN CLAIMS | Native Dell installation/executor/restart readiness; real DeepSeek connection; exact freeze and image; production identity and data preservation; full mandatory challenge coverage; migration/rollback; long-duration reliability |
| PROMOTION VERIFICATION | FAIL; no PROMOTION_VERIFICATION_PASS issued |
| PASS / FAIL / BLOCKED | FAIL for the tested source; additional prerequisites remain BLOCKED |
| EVIDENCE ARTIFACT | `PRIME-SUCCESSOR-EVIDENCE-c4f897b-20260927.zip` — 33 files, 158287 bytes |
| EVIDENCE SHA-256 | `48c1b48d18b4f854d6f4d9f07c9a5765a04953b3a578561144223bbf9b4c36a0` |

## Reproduced defects and successor requirements

| Group | Deterministic observation | Scope and required successor behavior |
|---|---|---|
| P2: stale speech callback and attempt binding | Start speech, Stop, then deliver the retired start callback: UI returns to reading. Start a replacement and deliver the old callback: trace attributes it to the replacement attempt | Bind callbacks to immutable owned attempts; retired callbacks cannot alter current state or receipts. Native callback incidence and historical iPhone root cause remain unproven |
| P2: missing terminal speech watchdog | Start a short utterance, omit end/error, advance the simulated clock one hour: speaking remains true with no timer left | Provide a bounded, truthful terminal transition after start, with cancellation and attempt ownership |
| P2: receipt newline binding | Two Python tests reject the actual committed receipt bytes. LF digest is `a84d531833665336254392adf2c4b0121c814ce9ea52ac8b2e001ae5be3abc8f`; recorded expected digest `49c6668f38b9654cc1b20e46af7b70664b79b787b45befac8bc42b1d1ce488b0` matches CRLF conversion | Define and bind exact artifact bytes consistently across platforms; preserve the original mismatching receipt and publish successor evidence |
| P2: provenance-helper trust binding | `verify_candidate_package` accepts fabricated verification receipts and an unbuilt arbitrary artifact; also accepts dirty checkout and HEAD different from the claimed source | Separate trusted observations from supplied claims and verify actual checkout/artifact bindings. No production caller or exploited production path was established |
| New P2: diagnostic audio ownership/recovery | Start a tone and call Stop: no immediate oscillator cancellation or context close. A suspended pending resume has no wall-clock timeout; three taps retain three live contexts | Own at most one diagnostic; Stop/hidden/logout release it; bound pending operations and cleanup; reject callbacks from retired diagnostics. Three safe fixture instances do not establish production exhaustion |

Injected rejected `resume()` and `close()` promises escape asynchronous handling. These support the diagnostic lifecycle group, rather than adding separate P2 counts. Injected voice-enumeration/utterance-construction exceptions and malformed provenance scalar types also reveal handling gaps; their native triggers and broader impact are unproven.

The portable independent speech suite records 4 pass, 5 fail and one optional synchronous-event skip; one pass is a source-digest check. The new diagnostic suite records 2 pass and 5 fail. Canonical voice tests pass 11/11 and are included within the 63-client-test run. Counts overlap and must not be summed into a coverage claim.

## Read Aloud outcome boundary

| Stage | Established scope / remaining gap |
|---|---|
| User gesture | Software handler/trace exists; an actual physical tap on the deployed device remains a device observation |
| Speech API invocation | Fixture invocation is observable; it does not establish speaker output |
| Voice availability/resolution | Enumeration and default-voice detail improved. System automatic selection is correctly labeled unobservable; actual resolved system voice remains unproven |
| Utterance and start | Software lifecycle events exist, but late start callbacks can still corrupt attempt attribution |
| Audible outcome | REQUIRES_PHYSICAL_DEVICE. Only Owner observation can establish audible speech; tone and speech are separate paths |
| End/error/timeout | Software events alone do not prove audibility. The missing post-start timeout remains reproducible |

The tone completion message correctly asks for physical confirmation. A running AudioContext, an end event, or an audible diagnostic tone does not prove an audible Read Aloud utterance. The latest-status element is not a durable full stage history.

## Required challenge coverage and gaps

All entries below refer to cloud observations only. There is no PROVEN_BY_INDEPENDENT_DELL result in this audit. Passing canonical assertions do not close an entire category.

| Required category | Evidence or remaining gate |
|---|---|
| Caller-controlled authority | Fabricated provenance acceptance reproduced in helper scope; production boundary unproven |
| Fabricated system metadata | Self-authored verification receipts accepted in helper scope; full runtime metadata envelope unproven |
| Model-content/system-metadata separation | Independent end-to-end challenge UNPROVEN |
| Owner/Member isolation | Independent cross-user, cache and recovery challenges UNPROVEN |
| Authentication/session expiry/recovery | Canonical suite exercised assertions; independent native operational coverage UNPROVEN |
| Durable identity | Restart/recovery identity preservation against real runtime UNPROVEN |
| Duplicate submission | Independent lost-ack/replay qualification UNPROVEN |
| Retries/timeouts | Missing terminal speech and suspended-audio timeout reproduced; broader API retry behavior UNPROVEN |
| STOP/COMPLETE races | Retired speech start and diagnostic Stop defects reproduced; complete task-race coverage UNPROVEN |
| TOCTOU | Unchecked source/checkout binding reproduced; atomic concurrent authorization/evidence qualification UNPROVEN |
| Concurrency | Three simultaneous diagnostic contexts reproduced within safe bounds; broader concurrent task/identity behavior UNPROVEN |
| Restart persistence | Native restart and crash-point recovery UNPROVEN |
| Corrupted/tampered evidence | Byte-digest mismatch and fabricated receipts reproduced; independently trusted signature/store verification UNPROVEN |
| Stale state | Old-attempt callback defects reproduced; full stale-client/server/state matrix UNPROVEN |
| Prediction integrity | Independent leakage/horizon challenges UNPROVEN; real future outcomes REQUIRES_LONGER_OBSERVATION |
| Learning/evidence qualification | Independent full qualification and incident-to-learning integration UNPROVEN |
| Database migrations | Candidate-specific rehearsal BLOCKED |
| Backward compatibility | Full predecessor client/server/schema matrix UNPROVEN |
| Rollback | Candidate-specific image/data rehearsal BLOCKED |
| PWA cache/version transitions | Client fixture tests pass in scope; actual transition matrix UNPROVEN |
| Offline/reconnect | Actual device and runtime reconnect behavior UNPROVEN |
| API failure | Injected audio promise failures escape handling; full network API failure matrix UNPROVEN |
| Malformed inputs | Provenance wrong-type TypeErrors reproduced; full bounded input matrix UNPROVEN |
| Safe resource exhaustion | Three retained diagnostic contexts expose missing ownership; production limits and recovery UNPROVEN |
| Dependency/service outage | Suspended audio-resume fixture covered; runtime service outage recovery UNPROVEN |
| Task lifecycle correctness | Speech/diagnostic lifecycle counterexamples reproduced; full production task lifecycle UNPROVEN |
| Runtime/source/image identity | Exact acquired source verified; image/host/runtime correspondence BLOCKED |
| Provenance and receipt integrity | Two scoped defect groups reproduced; exact frozen release and trusted native receipts BLOCKED |

## Acquisition, execution and evidence limits

The source was independently acquired from authenticated GitHub at the full SHA. Matching Git objects, 509 blob contents, tree, reconstructed commit and clean checkout were checked. The parent is `091e2f919edb1711b5a9e88404818095fa32b537`. A fresh execution copy and new fixtures were used. Authenticated historical Git objects were available; the two Python failures are not missing-history errors.

The execution reused a dependency environment whose versions are retained. Python socket-connect restrictions, file-only Git transport and a credential-free allowlisted environment were used. These restrictions are not a kernel sandbox, complete egress audit, Node/subprocess confinement, hostile-code containment certification or native Dell isolation. No claim of a production-image run is made. Logs retain commands, exit codes, timings, XML results, source digests, test snapshots and minimal counterexamples. Review these scripts and establish isolation before rerunning them.

The archive includes original evidence and a SHA-256 inventory. Its manifest SHA-256 is `86d7c31a9efa4de780ee9992e519b53c6779c590c57f675bc6ecbba5cd44f340`. Hashes establish consistency with this reference, not signer identity or tamper-proof storage. Previous FAIL evidence remains unchanged. The earlier initial archive remains `d053210b6b850c722b9df6f983cc158d5675d3e800543fe1a38f2dd5d963187f`. Its voice-report classification erratum remains in effect: cloud results are PROVEN_BY_AUTOMATION.

## Subsequent publication and production observation

An authenticated subsequent read resolved `fix/phase2-ios-audible-boundary-20260927` to `b171253566e7c879283d2aacf699ae6c1ec8988e`, tree `d1aeb123cbafca365356caae417b2809ad49e6db`. Commit time is 27 September 2026, 03:27:01 UTC. Its published state says `PENDING_NEW_CANDIDATE_FREEZE`; image status says `NOT_BUILT`, and runtime receipt says `NOT_APPLICABLE_NOT_DEPLOYED`. This is **SOURCE_PUBLICATION_ONLY**, with qualification **BLOCKED**. No tests or verdict from `c4f897b…` qualify it. A moved ref cannot close the freeze gate.

The two newer commits are titled “Own Web Audio diagnostic lifecycle” and “Clear audio UI on lifecycle stop.” Only `voice.mjs` and `voice-tests.mjs` changed. Those titles do not establish a successful repair. No full source-content acquisition or tests were performed for `b1712535…`. All 17 inspected annotated tags target other commits; releases are empty, and the inspected freeze/deployment receipts bind older sources. An external or unpublished receipt is not ruled out.

Separate publication evidence: `PRIME-PUBLICATION-b1712535-20260927.zip`, 33 files, 91289 bytes; SHA-256 `a742d6447099f6c33d0fec201493843151e072e91a55ef664a2db952e2af95ad`. The observation JSON itself has SHA-256 `e325203eff45be0bc5b993844072211560982cc70b815cc13379c822c8a13e62`.

The read-only PRIME status observation at 03:23:20 UTC reported healthy version `7.3.1.1-evidence-grounded`. It did not establish physical ABEX, deployed image, deployed source or runtime revision bindings. All three approved/deployed identity comparisons remain BLOCKED. No drift mismatch is asserted without both comparable identities. Production task execution, session/data preservation, provenance and retained rollback require authenticated existing host-bound receipts; no production tasks were created.

## Native Dell handoff

The reviewed toolkit and initial evidence are already available in [draft PR 135](https://github.com/AndrewLamSingapore/prime/pull/135), pinned at `c8cef976e530b983432dac9c0e601cb40abdb3a9`. The later cloud audit does not modify the PR, candidate or production. The toolkit passed 60 local synthetic self/review checks; this is not product acceptance or native installation.

Native Windows Dell commissioning, a trusted isolated executor, the observer's installed/scheduled/restart receipts and live DeepSeek connectivity are still UNPROVEN. The native Codex launcher remains blocked before credential access pending its effective-config/MCP/isolation audit. The separate exact-file DeepSeek advisory helper is prepared, defaults to dry run, and has not made a live request. Model output cannot confer verification authority.

For the Codex session physically running on Dell, use the [pinned START-HERE.md](https://github.com/AndrewLamSingapore/prime/blob/c8cef976e530b983432dac9c0e601cb40abdb3a9/tools/dell-independent-peer/START-HERE.md) and OPERATING-CONTRACT.md. Execute the already-authorized safe local commissioning steps and retain machine-bound evidence. Read current immutable candidate publications afresh; do not assume any SHA in this historical audit is current. Request Owner involvement only for an actual local credential, physical observation, authorization or irreversible boundary.

The new diagnostic counterexamples are preserved for ABEX successor qualification and future independent challenges. Their inclusion in ABEX's own qualification suite is not yet proven. ABEX remains responsible for product repair, image generation, promotion and rollback. Quiet publication observation continues until a meaningful new freeze, reproduced defect, completed audit or authenticated deployment-identity change.

Downloads: [audited-source evidence](sandbox:/workspace/scratch/e46efedd3273/PRIME-SUCCESSOR-EVIDENCE-c4f897b-20260927.zip), [subsequent-publication evidence](sandbox:/workspace/scratch/e46efedd3273/PRIME-PUBLICATION-b1712535-20260927.zip), [original audit](sandbox:/workspace/scratch/e46efedd3273/DELL-PEER-AUDIT-20260927.md).
