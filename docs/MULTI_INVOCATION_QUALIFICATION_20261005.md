# Multi-invocation qualification boundary

This isolated benchmark harness scores *recorded* exact-answer traces for
single, standard, deep and maximum modes. It makes no provider calls. The
bundled three-case input is synthetic and is **not** evidence of model quality,
actual concurrency, local thermals, or production readiness.

The synthetic run demonstrates a falsifiable property of the evaluator: its
standard mode repeats the same model and does not improve correctness; its deep
mode adds a distinct verifier and corrects two cases; maximum adds latency and
cost but no further correctness. Those numbers are intentionally constructed,
not measured PRIME outcomes.

Current candidate boundaries observed at `fcdb8717d03e937458da28dd5c058f919d0e9d5b`:

- `ModelGateway` records individual Ollama/frontier calls, but does not execute
  an adaptive multi-call reasoning tree.
- `provider_runtime` has governed HF and Chat Completions adapters, retries and
  a caller-authorized fallback; fallback is not independent parallel review.
- `compute_catalog` accepts measured route fields and requires explicit HF
  qualification/prices; its bundled HF example is disabled.
- `job_queue` has job/daily cost and concurrency controls. Neither the 21-agent
  population nor a queue concurrency value certifies safe simultaneous local
  model inference.
- `ComputeLedger` records task/stage/provider/model/latency/units/cost metadata,
  but a complete invocation-tree record still needs per-call role, timestamps,
  result/evidence reference, retry classification and objective linkage.
- The SSD telemetry/admission implementation is isolated in another candidate;
  this branch does not bypass its live trust dependency or qualify host load.

For a real qualification, collect a preregistered set of difficult tasks with
independent deterministic or domain-expert oracles, one common input per mode,
blind grading, provider/model identity, actual wall-clock timings, billed usage,
error/retry counts and ABEX resource/thermal observations. Include cases where
extra calls provide no gain, false consensus, disagreement, and a failed branch.
Compare paired per-task quality and latency/cost, not just mean answer rate.
Do not promote MAXIMUM until it beats the single baseline materially within
authorized privacy, cost, queue, and thermal boundaries.
