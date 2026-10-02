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

Regression comparator: `C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_performance_regression -v` returned 8/8 PASS on the isolated performance branch. This validates comparator behavior, **not** production performance acceptance. `git diff --check` passed.

Known evidence gaps: repeated controlled cold trials, 30-minute idle, longer representative PRIME task, owner-visible first useful token, PWA render, tools/agents, parallelism, thermals, GPU A/B, and Windows reboot persistence. The first 12.19 s result must not be generalized into an SLO from one sample.
