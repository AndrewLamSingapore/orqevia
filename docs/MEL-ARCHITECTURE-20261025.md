# Independent Model Efficiency Layer

MEL adds optimization inventory and benchmark evidence to the existing ORQEVIA
model registry database. It does not become a model provider, execution worker,
or model-promotion authority. PIF and MEL have no dependency on one another.
Neither is a required dependency of core agent execution.

The verified preimplementation baseline is
[INTELLIGENCE-ARCHITECTURE-BASELINE-20261025.md](INTELLIGENCE-ARCHITECTURE-BASELINE-20261025.md).
Implementation lives in `app/mel`, with no mandatory dependency additions.
The CPU benchmark imports ONNX Runtime, ONNX and NumPy only when explicitly run.
Plain service imports, disabled health and core startup need none of those
frameworks. There is no MiroFish or REA integration.

`MELService(path=None, enabled=None)` uses the existing
`ORQEVIA_MODEL_REGISTRY_DB`, or `ORQEVIA_DATA_DIR/model-registry.db` by default.
The independent `ORQEVIA_MEL_ENABLED` flag defaults off. Disabled service methods
do not create a directory, database or model session. Enabling MEL creates only
its additive `mel_experiments` table/index; existing model versions, event
history and model assignments are preserved. No fake LLM token counts are used
for embedding/optimization records.

| Interface | Contract |
|---|---|
| `health()` | Independent enabled/disabled/available/degraded signal; storage failure cannot stop inference. |
| `inventory()` | Runtime/package metadata without loading neural frameworks; artifact availability and integrity verification are separate fields. `ORQEVIA_MEL_MODEL_DIR` optionally identifies an existing local graph. |
| `experiments(tenant_id, limit=50)` | Only that tenant's persisted immutable evidence records, newest first. |
| `record_experiment(evidence, tenant_id=..., actor=...)` | Validates the versioned finite JSON contract; records actor/time and canonical SHA-256. Does not promote a model. |
| `recommend(model_id, tenant_id=..., max_quality_loss=0.01)` | Advisory `retain_baseline` or `eligible_candidate`. Never changes routing or grants execution authorization. |

The gateway must reuse existing bound-owner/tenant authentication and exception
handling. The caller cannot supply a command, model-download URL, benchmark
script or filesystem path to these service APIs. Benchmark execution is an
explicit offline operator CLI, not a request-driven subprocess endpoint.

Evidence includes baseline and candidate digests, source revision, time,
hardware/runtime, corpus digest and classification, repeat counts, numerical
agreement, measured latency/throughput, process peak memory, preparation cost
and task-quality availability. Typed validation rejects NaN/Infinity, malformed
probabilities/cosine ranges, invalid digests, impossible timing order and
claims that a controlled fixture is a representative production workload.
It requires representative labeled evidence and its hash before recording a
claim of critical operational task-quality validation.

Recommendations retain baseline for missing evidence, unvalidated critical
quality, unsupported runtime, excessive declared task-quality loss, slower
tail latency or an unsupported measured mean improvement. The comparison uses
the measured mean difference against a disclosed normal-approximation radius
`1.96 * sqrt(s_base²/n_base + s_candidate²/n_candidate)` for both batch sizes.
Repeated timings on one shared host may be correlated; this comparison is an
engineering screening rule, not a claim of independent experimental samples,
forecast calibration or guaranteed acceleration. A recommendation cannot replace
existing model activation/approval/rollback contracts. The default quality-loss
threshold is an advisory normalized loss fraction; actual critical task metrics
must be specified and justified by their separately hashed validation report.

The benchmark reuses `OnnxMiniLMEncoder`, its local tokenizer, CPU provider,
normalization, 384-dimensional output and 256-token preprocessing. The sole
supported baseline is the retained graph SHA-256
`e81857e1b034a003c6dba3ae71271faa3c0ca29f8e0b06505ef2e0e6c35ab0f8`.
It creates a separate dynamic per-channel QInt8 MatMul candidate with copied
tokenizer files. It verifies both graph digests and ONNX integrity, rejects
external tensor loading, and never modifies the original model or corpus.
It never downloads model/tokenizer code or uses pickle/remote-code loading.

| Technique / workload | Verified assessment |
|---|---|
| Existing MiniLM FP32 ONNX CPU | Pinned local baseline; preserve it and current retrieval configuration. |
| Dynamic INT8 MatMul | Supported candidate path; actual benchmark required and critical quality remains separate. |
| NVIDIA 2:4 acceleration | NOT APPLICABLE to verified AMD 8840HS / Radeon 780M host with no NVIDIA device. No sparse-kernel activation or 2x claim. |
| FP16/BF16, INT4 | NOT VERIFIED for this graph/kernel/CPU combination; no activation. |
| Structured/channel pruning | NOT VERIFIED; no architecture-specific recovery training or representative quality evaluation. |
| Unstructured pruning | NOT VERIFIED; no sparse execution-kernel performance evidence. Merely setting weights to zero does not establish speedup. |
| Hosted API models | NOT APPLICABLE to local weight modification; no externally controlled weights are pruned. |

The inventory service reports GPU compatibility as NOT VERIFIED when the current
runtime cannot verify a device and kernel. This is deliberately distinct from
the evidence-backed NOT APPLICABLE assessment of the inspected physical host.

The retained original retrieval documents identify themselves as synthetic
acceptance fixtures. Their measured benchmark can validate implementation,
numerical stability and scoped local resource use; it cannot qualify actual
production task quality. First-line document queries measure agreement with the
baseline ranking only. They are not human relevance labels or real user queries.
No zero-accuracy-loss, production gain or guaranteed acceleration claim follows.

The benchmark records load and first-batch cold latency separately from warm
batch-1/batch-8 timings including tokenization. Each artifact uses separate fresh
processes with alternating order, repeat distributions and OS-reported peak
working set/RSS. OS disk cache is retained; compilation/quantization overhead is
recorded independently. CPU/wall time are measured, while physical energy and
dollar cost remain NOT MEASURED. Other shared-host workloads are not controlled.
No queue guard, execution hold, artificial rate limit or mandatory sandbox is
introduced by MEL.

Rollback: set only `ORQEVIA_MEL_ENABLED=0` and redeploy the existing runtime using
its established workflow. Keep experiment rows and candidate files as inert
evidence; inference routing was never changed. PIF can remain enabled or disabled
independently. The existing baseline model, tokenizer, current index, credentials,
certificates and trusted sessions are unaffected. Deleting a candidate is not
required to roll back and no shared database table should be dropped.

Operator benchmark (optional verified benchmark dependencies on PYTHONPATH):

```powershell
python -B scripts/benchmark_mel_onnx.py --model-dir <retained-model-directory> --corpus <local-chunks.json> --output-dir <new-private-directory> --workload-kind controlled_fixture --source-revision <actual-40-character-Git-SHA>
```

`benchmark.json` contains metrics and hashes, without document text or embeddings.
`private-workload.json` contains frozen local inputs for reproducibility and must
remain private and outside source control/public evidence. No corpus content is
sent over a network. Keep failed worker receipts; rerun in a new output directory
rather than overwrite historical observations. Pass only `benchmark.json.evidence`
to the tenant-scoped experiment API. Source tests and an execution benchmark do
not constitute a live deployment or operational model-quality certification.
