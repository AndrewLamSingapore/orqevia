# PRIME performance branch receipt — 2026-10-02 SGT

## Decision

- **Branch engineering:** reviewable isolated candidate, checkpointed and pushed.
- **Inference selection:** N=3 with a two-background/one-Owner local slot policy is the current *technical candidate*, not a qualified production setting. N=3 without reservation regressed Owner first-token time in the sampled workload. N=6/8 lacked memory margin at the real context. N=2 remains a fallback.
- **Deployment:** deferred. Golden Gen 2 stays unchanged at production inference N=1; `HOST_STABILITY=UNQUALIFIED` and the remaining production-specific proofs prevent acceptance.
- **Status authority:** this receipt is agent-observed evidence, not Lam's personal Verified section in `STATUS.md`.

## Completed in branch

- Recorded real production before/after timing for the 30-minute model-retention configuration change without replacing the accepted Golden image.
- Ran isolated Ollama N=1/2/3/4 and bounded N=6/8 comparisons at the real 8,192-token context; rejected N=6/8 for inadequate 6-GiB memory margin.
- Exercised a disposable priority queue against a separate pinned Ollama container. N=3 Owner reserve delivered first token in 0.913 s for the short case and 0.976 s for the longer case; all six outputs were correct in each run.
- Added fail-closed queue admission requiring an explicit backend parallel setting and hash-pinned measured profile; added an Owner-reserved local slot for candidate N>1.
- Corrected priority aging and queue scans so aged background and large blocked same-agent backlogs do not hide ready Owner/other-agent work.
- Added an isolated non-inference ready-work DAG, registry/fake-tool parallel proofs, opt-in PWA timing, and optional disabled-by-default prewarm. None is represented as a live 21-agent activation or a production integration.

## Checks and limits

- Focused Python regression: 126 passed. Focused PWA Node tests: 28 passed.
- Broad Python run before the final queue-lane fix: 1,073 passed, three protected exact-byte receipt/Golden checks failed on CRLF working-tree copies of LF-indexed evidence. The protected bytes were not rewritten; the final queue-lane change passed focused tests afterward.
- Follow-up ABEX checkout/test repair: explicit per-file Git checkout line endings preserve the frozen digests; the historical portfolio insertion assertion is anchored to its insertion commit. The final branch then passed the full Python suite (1,077 tests) and 48 PWA Node tests. The frozen Git blobs and manifest digests were not changed. Fresh cross-platform checkout remains unverified.
- Production PRIME/Interface/Ollama remained healthy and on the accepted image after the isolated probes. The temporary benchmark container was removed; no model volume was mounted writable for it.
- Owner PWA first paint, sustained thermal/resource behavior, live 21-agent execution, service-restart and normal-reboot persistence of an N>1 deployment, and a genuine host-stability PASS remain unverified. Do not report this as integrated or accepted production performance.

Detailed evidence: [baseline and tests](PERFORMANCE_TEST_RESULTS.md), [concurrency comparison](PRIME_INFERENCE_CONCURRENCY_20261002.md), [Owner load](PRIME_OWNER_LOAD_PROOF_20261002.md), [remaining blockers](PERFORMANCE_BLOCKERS.md).
