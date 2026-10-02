# Isolated Ollama inference-concurrency comparison — 2026-10-02 SGT

Status: **N=3 candidate, not deployed or production-verified**. `HOST_STABILITY=UNQUALIFIED` remains unchanged.

The pinned Ollama image ran in a separate, loopback-only container at `127.0.0.1:11435`, with the existing model volume mounted **read-only**, a 6 GiB memory limit and an 8-CPU limit. PRIME, Interface, their production Ollama container, Golden Gen2 image, identities, and production queues were not modified by this comparison. The temporary container was removed afterward; the source model volume was never mounted writable in it.

Each run used `gemma3:4b`, temperature 0, an identical short integer-sequence prompt, up to 64 output tokens, five simultaneous requests, and the real PRIME `num_ctx=8192`. Each configuration was warmed before the timed batch. All 5/5 responses passed the same numeric-sequence correctness check; warm model-load durations remained milliseconds. The raw second N=3 run is [OLLAMA_N3_8192_RAW.json](OLLAMA_N3_8192_RAW.json). The harness is `benchmarks/ollama_concurrency.py`.

The harness's `configured_parallel` field is an operator-supplied label, not a discovery endpoint. The separate test-container `OLLAMA_NUM_PARALLEL` environment and startup logs were checked for each run. The raw repeat predates the harness clarification fields; its `mean_individual_generation_tokens_per_s` was a pooled tokens/sum-duration calculation, not an arithmetic mean of request rates. The comparison table below uses aggregate tokens divided by workload wall time and does not rely on that mislabeled field.

| Configured parallel N | Five-request wall | Aggregate output tokens/wall-second | Mean TTFT | Max TTFT | Container memory after run |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 29.595 s | 8.79 | 12.171 s | 23.920 s | 3.639 GiB |
| 2 | 17.902 s | 14.52 | 5.083 s | 12.248 s | 4.024 GiB |
| 3 | 12.675 s | 20.51 | 3.069 s | 6.804 s | 4.402 GiB |
| 3 repeat | 12.716 s | 20.45 | 3.064 s | 6.792 s | not sampled concurrently |
| 4 | 13.024 s | 19.96 | 2.044 s | 7.081 s | 4.800 GiB |

For N=6 and N=8, even a single warm-up at `num_ctx=8192` reached the full 6 GiB test-container cap. N=6 took 26.11 s including 19.89 s reported load; N=8 took 53.23 s including 41.96 s load after an initial 45 s timeout. They did not OOM, but have inadequate memory margin under this bound and are **rejected**. Short-context (`num_ctx=1024`) tests scaled further, but those are not a production-context basis for selection.

Interpretation: N=3 cut this specific batch wall time by about 57% versus N=1 and had substantially more memory margin than N=4, while N=4 did not improve total completion. N=4 had a lower mean TTFT in this sample; therefore this does **not** yet prove N=3 optimal for owner-interactive work under background load. The backend tests also do not prove queue scheduling, real PRIME owner TTFT, thermal behavior, longer-generation correctness, sustained stability, Windows reboot persistence, or the 21-agent production fabric. A cold load can be much slower when the context and parallel count rise; protected warm retention remains important.

Production remains at `OLLAMA_NUM_PARALLEL=1` and `PRIME_QUEUE_CONCURRENCY=1`. The isolated queue candidate now admits N=2 or N=3 only when the Ollama setting, queue setting, and integrity-checked measured compute profile all agree; it otherwise fails closed to one. The isolated Compose candidate mirrors the Ollama setting to PRIME, but that environment value alone does not verify actual backend parallelism. No measured profile or deployment was created by this experiment.

Next safety gates before promotion: verify representative longer outputs and owner-priority load at N=2/3; record CPU/per-core, memory, paging, model copies and available thermal data during load; verify no errors or host events; integrate and test the scheduler with actual dispatch; establish a measured signed profile; prove fail-closed rollback. The host-stability incident remains independently unresolved.
