# Performance test results — 2026-10-02

The controlled production fixture asked the same short local-only question through PRIME's authenticated loopback dispatch. It creates a normal advisory job but no external action. The answer length and token counts matched across before/after trials (178 input, 10 output, 29 result characters). It does not test Owner PWA paint latency.

| Condition | Samples / observation | Result |
| --- | --- | --- |
| Initial cold request | 1 real PRIME task | 12.194774 s total; 9.155453348 s model load; 0.986179 s generation |
| Initial immediate warm request | 1 real PRIME task | 1.596262 s total; 0.001113862 s model load |
| Warm direct backend | 1 Ollama stream | 0.232208 s first token; 0.211778 s prompt eval; 9.99 tokens/s generation |
| 30-minute retention probe | one bounded direct Ollama request | `ollama ps` displayed 29 minutes remaining; no persistent config yet |
| Production `PRIME_MODEL_KEEP_ALIVE=30m` | PRIME-only controlled recreation | PRIME, Interface, Ollama healthy; Golden image ID unchanged; PRIME restart count 0 |
| Immediate production repeat | 3 same-fixture requests | totals 1.895342 / 1.366924 / 1.362313 s; model loads 0.002093 / 0.001007 / 0.001529 s |
| Approx. 14-minute idle then request | 1 same-fixture request | model still resident; 1.636574 s total; 0.001970 s model load |
| Idle host memory after retention | 1 snapshot | 17,046 MB free; Ollama 3.504 GiB; no sampled pressure |

CPU thread exploration used identical 31-token prompt, `temperature=0`, 96 generated tokens, and request-scoped `num_thread` values 8, 4, 12, 8. Output SHA-256 was identical in all four runs (`3d28c8c35bd2beb9226ef77ad6d5f635df1feac07e26ca57d25ed50d10d0de91`). Measured generation throughput was 8.98, 9.13, 8.74, and 9.18 tokens/s respectively. Each changed runner configuration incurred a 4.56–8.57 s load. Differences are too small/noisy to justify altering production thread configuration; request-scoped switching worsens latency. No CPU thread optimization was retained.

One deterministic SHA-256 dispatcher/tool operation completed in 0.039097 s with `model_calls=0`, a JSON artifact, and a correct expected digest. It is a one-sample tool-path observation, not a tool-latency distribution.

One two-job *concurrent submission* experiment requested two `gemma3:4b` advisory jobs. The first ran 08:31:08.304–08:31:19.718 UTC; the second waited and ran 08:31:19.757–08:31:22.775 UTC. Total client wall time was 14.660932 s. The first job's model-load event was 8.360872495 s, the second's 0.001775518 s; both completed with 178 input and 13 output tokens. Because the preceding request-scoped thread probes changed runner options, this cold load is a benchmark interference/confound, **not** evidence that the 30-minute idle policy failed. The sequential execution is consistent with the intentional one-slot PRIME inference queue. Do not extrapolate benefit from launching all 21 agents simultaneously.

Regression comparator: `C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_performance_regression -v` returned 8/8 PASS on the isolated performance branch. This validates comparator behavior, **not** production performance acceptance. `git diff --check` passed.

Known evidence gaps: repeated controlled cold trials, 30-minute idle, longer representative PRIME task, owner-visible first useful token, PWA render, tools/agents, parallelism, thermals, GPU A/B, and Windows reboot persistence. The first 12.19 s result must not be generalized into an SLO from one sample.

## Priority Zero continuation (after the baseline)

An **isolated** Ollama backend comparison tested N=1/2/3/4 at PRIME's real 8,192-token context. The same five-request deterministic workload took 29.595/17.902/12.675/13.024 seconds, with 5/5 correct answers at every N. N=3 was repeated at 12.716 seconds; [full method and caveats](PRIME_INFERENCE_CONCURRENCY_20261002.md) and [raw repeat](OLLAMA_N3_8192_RAW.json) are preserved. N=6/8 hit the 6 GiB test-container limit during real-context warm-up and are rejected. No inference-concurrency production change was deployed.

The isolated priority scheduler, agent registry/fake tool overlap proof, queue admission candidate, prewarm candidate, and production compatibility tests passed together: 86 tests plus 19 subtests. PWA timing/revision focused checks passed 19/19. The broader `pytest tests -q` run yielded 1,068 passed and four failures. One new ready-work timestamp assertion was revised to use the independently observed overlap event and now passes. The other three are historical exact-byte Golden/independent-evidence checks; this Windows checkout has CRLF working-tree copies of LF-indexed files (for example the Dell verification JSON is 7,929 bytes versus the test's protected 7,804-byte expectation). Those files are unmodified in Git and were **not** rewritten. Thus the full suite is not claimed green; the exact-byte checkout issue remains an environment blocker for that suite on this worktree.

After adding server-issued OWNER priority to the isolated interface candidate, a focused regression run covering interface submit/continuation, ready-work, agent overlap, queue admission, prewarm, production compatibility and dispatch passed **113/113**. This proves priority propagation into the dispatch request, not owner latency under real background inference. The production interface remains unchanged.
