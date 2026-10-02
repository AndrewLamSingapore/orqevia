# Measured performance bottlenecks — 2026-10-02

## 1. Cold model load (confirmed for tested request)

A real local-only PRIME dispatch to `responsibility.a02` using `gemma3:4b` took 12.194774 s from submit to terminal result. The authoritative queue completion event reported 9.155453348 s of model load and 0.986179 s of generation for 10 output tokens. Queue wait was 0.048667 s, while HTTP dispatch took 0.06831 s. Cold model loading contributed about 75.1% of measured client wall time. This establishes the first bottleneck for *that request*, not every PRIME workload.

The identical immediate warm request took 1.596262 s, and its load event was 0.001113862 s. Warm direct Ollama measured 0.232208 s to first token, 0.211778 s prompt evaluation for 178 tokens, and 9.99 output tokens/s (10 tokens).

## 2. CPU generation (measured, not yet optimized)

The container reports `gemma3:4b` running `100% CPU`. Ollama logs show CPU runner, 8 threads, and no GPU backend. Warm generation is about 10 tokens/s for the tiny fixture; a longer-output representative benchmark remains required before generalizing.

## 3. Owner-visible streaming (architecture finding, not timed)

PRIME's `app/direct_stream.py` consumes Ollama's streamed chunks but returns a joined result only at completion. The PWA requests bounded task-status SSE snapshots, then polls status with a 2 s wait in `clients/pwa/app.mjs`. Thus backend token streaming is not currently equivalent to owner-visible token streaming. Actual Owner PWA first-visible-token/render timing remains unmeasured.

## Not primary in first measurement

Host CPU baseline 2.75%, free RAM 18,230 MB, PRIME `/health` 3.172 ms, Interface PWA 11.537 ms, dispatch 68 ms, queue wait 49 ms. These do not explain the measured 12.19 s short-request delay. Do not optimize CPU utilization as an end in itself.
