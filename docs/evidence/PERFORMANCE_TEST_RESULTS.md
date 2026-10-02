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

The later isolated queue plus real Ollama [Owner-under-load proof](PRIME_OWNER_LOAD_PROOF_20261002.md) compared N=2, N=3 and N=3 with one reserved Owner slot. The reserved N=3 short workload reached first token in 0.913 s after Owner submission versus 6.989 s for unreserved N=3; the longer 142-output-token case reached first token in 0.976 s. All six jobs produced the expected sequence in each measured case. These are isolated backend/queue observations, not production PWA paint measurements. The reservation deliberately reduces idle-time background saturation.

After the queue starvation/backlog/reservation fixes, the focused Python suite passed **126/126** and focused PWA Node tests passed **28/28**. The full Python suite passed **1,073 tests** and failed the same three protected exact-byte Golden/independent-evidence checks caused by this checkout's CRLF working-tree bytes; no new functional test failed. A final same-agent backlog lane fix followed that full run and passed its focused regression, but the full suite was not rerun afterward. The protected documents remain unmodified. Thus the full suite is still **not green** on this Windows checkout.

## 2 October follow-up: exact-byte checkout repair

The final branch revision was retested on ABEX after adding explicit checkout
line endings for five frozen files in `.gitattributes`. Four LF-pinned files
were restored locally to their manifest-verified byte sequences; the Gen 1
runtime receipt retains its historical CRLF checkout form. No frozen receipt
content or expected digest changed. The portfolio insertion test now checks
the historical insertion commit rather than comparing all later legitimate
`STATUS.md` entries against a pre-insertion baseline.

`pytest tests -q --tb=short`: **1,077 passed, 5 deprecation warnings** in
203.60 seconds. `node --test clients/pwa/*.test.mjs clients/pwa/*-tests.mjs`:
**48 passed**. The earlier 1,073/4 result above remains historical evidence;
it is not the current ABEX branch test result. A fresh detached Windows
checkout with `core.autocrlf=false` subsequently showed the intended LF/CRLF
forms and passed all 14 targeted Golden/receipt/portfolio tests. A native
Linux checkout has not yet been tested.

After wiring the existing bounded ready-work scheduler into both objective
submission and continuation dispatch paths, a focused integration run passed
53 tests. The complete Python suite was rerun on the final code candidate:
**1,078 passed, 5 deprecation warnings** in 197.07 seconds. This proves
branch regression behavior, not that production is running the candidate.

## Parallel/context branch continuation

The configuration-only 21-agent projections reproduce the registry SHA-256
and pass their deterministic `--check` comparison. The opt-in context-pack
dispatch path and its oversize fail-closed behavior passed focused tests after
the final request-snapshot freshness adjustment: **27 passed, 1 deprecation
warning** across agent dispatch, context pack, and export tests.

The complete Python suite on this isolated branch returned **1,107 passed,
26 subtests passed, 5 deprecation warnings** in 208.47 seconds. This run
covered the opt-in context-pack source path, but it did not connect to live
production PRIME or measure production latency. No production deployment or
restart was attempted. The PWA Node suite also returned **48 passed, 0 failed**.
See `PRIME_PARALLEL_CONTEXT_PARTIAL_RECEIPT_20261002.md`
for the unresolved live-proof and host-safety boundaries.
