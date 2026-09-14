# Direct execution migration — review candidate

Owner directive SHA-256: `544FF76EDE957914CC7AF01BDD9E182FABAE7A4B285C5EB976206C281BEF77F5`.
Isolated branch: `phase-ii-local`, parent `91712dd821f26c183f33f4c53b68ea946673453a`.
This candidate is **not merged or deployed**. Running `prime` remains clean at `f289ce06dec167fd1028f949134aa2c2bb19b930`. The commissioned report, manifest and Compute Profile hashes still match their preserved values.

The candidate entrypoint `app.entry:app` now exposes direct Registry dispatch, objectives, engineering, artifacts, Interface Node and compute APIs. It delegates to `app.direct_entry:app`, which was used for isolated live acceptance. Historical UI, Spine, Harness and relay routes are not mounted. Their source remains available for compatibility work; this is an API candidate, not a full UI deployment.

| Component | Old purpose | Status / new purpose | New critical path? | Later cleanup |
|---|---|---|---|---|
| `action_harness.py`: issuer, authorization, execution lease, revocation | Decide whether an action may run | **COMPATIBILITY-ONLY**; original implementation retained | No | Remove legacy callers before retiring module |
| `harness_api.py`, `spine_api.py`, Stable Spine policy | Signed dispatch and pre-approval | **COMPATIBILITY-ONLY**; not mounted by candidate | No | Review historical APIs separately |
| `_validate_job_lease`, `governed_stream.py` | Block inference on missing/revoked lease | **DEAD** to candidate execution; retained for historical references | No | Delete after compatibility retirement |
| `agent_runtime.py` | Authority-checked delegation and event history | **COMPATIBILITY-ONLY** for authority methods; routing keyword data still reused | Data lookup only | Extract routing data when migrating remaining old clients |
| Action Envelope / `action_records.py` | Authorization prerequisite | **REPURPOSED** as non-authorizing ActionRecord metadata and actual outcome summaries | Buffered emission only; no permission decision | Consolidate legacy envelope schema after consumers migrate |
| Ledger / `ActionLedger` | Authority and decision history | **REPURPOSED** as ordered asynchronous execution audit with hashes, flush and loss/error counters; old ledgers untouched | No synchronous disk write in action execution | Rotation, retention and independent external anchoring remain future work |
| `ConnectorRegistry` | Verify signed sink authority | **REPURPOSED** as discovery, dispatch and audit; R0–R3 are labels | Direct handler dispatch | `LegacyConnectorRegistry` retains old adapter explicitly |
| Job queue / Interface cancellation | Approval waiting and lease revocation | **REPURPOSED** as durable scheduling and operational cancellation | Yes, for real capacity/state management | Remove obsolete approval DB columns after data migration review |
| Registry, model tier selection, DAG, Artifact Factory, WASM | Routing, dependencies, outputs, containment | **UNCHANGED** functions, wired to direct execution; legacy `select_route` retained separately from `select_direct_route` | Yes | No authority cache work |
| Client authentication, ownership, Compute Profile, guest limits | Network identity, privacy and resource containment | **UNCHANGED** safeguards; endpoint capability labels no longer approve actions | Yes, for authentication/containment only | No removal proposed |

## Candidate evidence

Paths below are relative to the shared commissioning workspace, outside the repository.

- Final focused suite: **69 passed**, one third-party deprecation warning; no deselections. `outputs/phase2-tests/05a2029b90924c5da897e689eef6eb80/results.xml`. This is not a claim that every historical UI/Harness integration test passes under the new API. The selected legacy connector test explicitly targets `LegacyConnectorRegistry`; queue tests now assert direct admission and operational cancellation.
- **21/21 logical agents** executed real local Ollama inference with R0–R3 labels and no signed envelopes. Loopback client → objective → inference → artifact → checksum download passed; **94 audit events flushed, zero dropped**. `outputs/direct-execution-live/4dc2b6b2ddb64cc6ba9d7795e8c79eff/`.
- A12/A13 bounded WASM both returned 42. Independent subprocess CRC32 verification caught a seeded defect and passed all 64 vectors after repair. **Two attempts**, with actual preserved candidates and verification results. `outputs/direct-execution-mechanisms/1a9676c507a340848dbc2755811bcb58/`.
- Final tests cover A–C direct R0–R3 routing and real fixture effects; D–E action metadata, outcome and hash-chain verification; F legacy gate traps/unmounted routes; G direct sandbox/repair; H parallel independent tasks and dependency failure isolation; I model selection; J Registry, orchestration and client ownership; K unavailable logging, record-construction errors, closed logger and saturated buffer. Operational cancellation closes a silent stream without a lease.

## Measurements

| Measurement | Observed result / scope |
|---|---|
| Time to finished artifact | **0.508 s**, one warm loopback objective and JSON artifact; not a general task SLA |
| Buffered execution logging | **0.0539 ms median**, 0.0644 ms p95, 100 deterministic actions; 216 mechanism events ultimately flushed with zero loss |
| Independent verifier parallelism | **1.85×**, two actual subprocess verifiers; local model concurrency stays 1 |
| Responsibility routing | **0.0651 ms median**, 50 isolated durable enqueues |
| Model selection | **0.0178 ms median**, same 50 samples |
| Full dispatch including SQLite enqueue | **8.217 ms median**; not directly comparable to earlier Harness-only microbenchmarks |
| Two-specialist objective intake | **34.90 ms**, one isolated control-plane sample, workers not started |

Dispatch measurements: `outputs/direct-dispatch-performance/53ccf8325fa44657898026256700fd9e/`. Live queue timestamps and inference/model-load durations remain in the sealed candidate queue evidence. No universal speedup or latency SLA is claimed.

## Material limitations and review boundary

- This is direct execution of implemented connectors, bounded engineering and local inference. It is not autonomous native Windows/Python execution of arbitrary model-generated programs. WASM has no host imports; fuel and guest-memory limits remain. Host JIT compilation is not a fully process-isolated memory boundary.
- The repair fixture is deterministic. The preceding real `gemma3:1b` code-generation probe failed three attempts; general model-driven coding remains unqualified. That failure was preserved, not replaced by the seeded success.
- MINI/FLAGSHIP backends and cloud execution remain unavailable in this candidate. The data-residency-aware router is fixture-tested for available cloud backends, but no provider was configured or contacted.
- Remote Dell/iPhone/TLS enrollment, voice, historical UI/relay migration and real-reboot recovery are not established by loopback acceptance. Chrome Remote Desktop and machine configuration were untouched.
- Buffered events can be lost on abrupt process termination; a return value says BUFFERED, not durable. Explicit flush, health/loss counters and clean shutdown provide bounded durability. Hash chaining detects changes when checked against a preserved seal; it is not an independent trust root.
- Durable queue/objective state still requires SQLite writes. Those writes maintain scheduling/recovery state; they are not action-approval decisions.

**Next state: review this candidate and component audit. No merge, deployment or baseline mutation has been performed or inferred from test completion.**
