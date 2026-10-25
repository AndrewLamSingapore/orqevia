# Measured local MiniLM optimization experiment, 25 October 2026

**Decision: retain the existing FP32 baseline.** The actual INT8 candidate executed
successfully, with numerical differences and lower observed latency in this
specific experiment. Operational task quality remains NOT VERIFIED: the available
retained corpus comprises five synthetic acceptance chunks, no relevance labels,
and no established representative production workload. Concurrent Defender,
HTTPS verification and other host activity also limit timing conclusions.
These measurements are not a production acceleration or zero-quality-loss claim.

The benchmark ran at source
`07503ae8162f146b0d813795bcaba30b11fa3ae9`, completed
`2026-10-25T08:43:07.143955+00:00`, and exited 0. The runner and inference encoder
did not change during measurement. Subsequent service-only validation hardening
added stored-record integrity checks and does not change the measured model path.
The measured receipt also passes that stricter evidence contract.

The verified host baseline is AMD Ryzen 7 PRO 8840HS, 8 physical/16 logical CPUs,
33,644,036,096 bytes RAM and Radeon 780M. This experiment used the existing ONNX
Runtime 1.31.0 CPUExecutionProvider with two intra-op threads, one inter-op thread,
and the production `OnnxMiniLMEncoder` preprocessing/normalization. No NVIDIA
hardware was verified, so NVIDIA 2:4 acceleration is NOT APPLICABLE here.

| Measured field | Retained FP32 graph | Dynamic per-channel QInt8 MatMul candidate |
|---|---:|---:|
| Model artifact bytes | 90,374,450 | 58,715,652 |
| Mean session/model load, ms | 13,936.333 | 10,341.206 |
| Mean cold first batch, ms | 34.681 | 21.438 |
| Warm batch 1 mean, ms | 23.700 | 11.934 |
| Warm batch 1 median, ms | 19.480 | 9.536 |
| Warm batch 1 p95, ms | 43.366 | 21.846 |
| Warm batch 1 sample stdev, ms | 13.321 | 6.263 |
| Warm batch 1 mean-derived items/s | 42.193 | 83.797 |
| Warm batch 8 mean, ms | 343.026 | 170.009 |
| Warm batch 8 median, ms | 326.037 | 169.228 |
| Warm batch 8 p95, ms | 446.085 | 209.198 |
| Warm batch 8 sample stdev, ms | 57.013 | 23.424 |
| Warm batch 8 mean-derived items/s | 23.322 | 47.056 |
| Maximum worker process peak memory, bytes | 609,120,256 | 571,199,488 |
| Mean worker CPU seconds | 41.573 | 25.042 |
| Mean worker wall seconds | 30.187 | 18.494 |

There were three fresh process runs per artifact, 40 timed calls for each batch
size per process, and 120 observations per batch/artifact after three excluded
warm-up calls. Workers ran sequentially, with baseline/candidate order alternated
between process runs. At most one MEL inference worker ran at a time; no MEL
benchmark worker remained after completion. The separate quantization step took
2.783 seconds wall / 2.531 seconds CPU, with a parent process peak of 492,904,448
bytes. Six measured workers and one quantization step do not establish steady
production concurrency capacity.

"Cold" means a fresh process/session and first batch. OS disk cache was retained,
so these are not uncached storage measurements. Load includes local graph digest
verification, tokenizer and runtime/model initialization. Warm timings include
tokenization, truncation/padding, session execution, normalization/output checks
and result assembly. Inputs cycle over the same five frozen chunks, including
different text lengths; batch 8 repeats them to fill the batch. Observations are
therefore correlated and their variability combines input lengths, scheduling,
thermal/cache effects and concurrent host activity. No CPU allocation, firewall,
queue guard, deployment hold or sandbox was introduced for this experiment.

Quantization used ONNX Runtime `quantize_dynamic`, MatMul operators only, QInt8
weights, per-channel quantization and `reduce_range=False`. The transformed graph
contains 36 `MatMulInteger` operators and 12 remaining `MatMul` operators; it does
not quantize every tensor or reduce every component fourfold. ONNX checker and
the production embedding contract accepted both artifacts. The graph contains
22,565,376 baseline initializer elements; that is an observed graph count, not
an independently verified trainable-parameter count. The recorded ONNX warning
about optional quantization preprocessing was retained; no preprocessing or
accuracy-recovery training was claimed.

Numerical comparison observed mean cosine **0.9941963354**, minimum cosine
**0.9924136579**, maximum absolute embedding difference **0.0240436010** and
top-1 agreement **1.0** on queries derived from each document's first nonempty
line. Those queries are a baseline-ranking proxy, not real user queries or human
relevance labels. The results contain measurable numerical change and cannot
support a zero-accuracy-loss claim. Critical task-quality loss remains unavailable.
Physical energy, dollar cost, pruning performance, FP16/BF16/INT4 quality and
production population/workload scalability were not measured.

Integrity and evidence:

- Baseline SHA-256: `e81857e1b034a003c6dba3ae71271faa3c0ca29f8e0b06505ef2e0e6c35ab0f8`.
- Candidate SHA-256: `728b34c0e614e7567564b90e4faa29d01d1e0a397ec78116d24915bf00f5e7e0`.
- Frozen input-content SHA-256: `3f4f46ba154b735e7f3e98a24cdb64c48399311e015930169f423b7750690fdc`.
- Metrics receipt `operations/system-security-20261025/mel-benchmark-07503ae.json`, SHA-256 `7eb0667fa419a3988838b2ced4811d6af958f81c05c459e35e55756ad56d302a`.
- Original private candidate/receipt directory: `C:/Users/Admin/AppData/Local/ABEX/engineering/mel-benchmark-07503ae-20261025`.
- Official optional-wheel integrity, package advisory response and installation log are retained in `operations/system-security-20261025/mel-wheel-integrity.json`, `mel-dependency-audit.json` and `mel-optional-deps.log`.

Only the metrics receipt may be reused as deployment evidence. The private
frozen corpus is outside Git/public output and must remain private. Neither
document text nor embeddings appear in the metrics receipt. The benchmark
checked the retained baseline digest again after execution; that model and the
original corpus were not modified. Candidate artifacts remain inert, with no
production routing, model assignment, tokenizer or index promotion.

Validation completed: **39 focused tests PASS** across MEL, the retained ONNX
encoder and existing model registry; Ruff and `git diff --check` passed. These
are implementation/benchmark observations. API integration, live deployment,
source-bound HTTPS acceptance and operational critical task quality are separate
milestones owned by the main release task. Disable MEL independently with
`ORQEVIA_MEL_ENABLED=0`; no model rollback is required because the baseline
remained in use throughout.
