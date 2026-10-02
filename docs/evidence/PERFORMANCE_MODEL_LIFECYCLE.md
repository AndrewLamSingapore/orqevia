# PRIME/Ollama model lifecycle audit — 2026-10-02

Read-only audit. No inference request, model stop/start, configuration edit, or production edit was made in this lane. Timestamps below are UTC unless marked otherwise. Avoid interpreting the concurrent performance experiment's later load events as normal workload.

## Live configuration and observed behavior

Selected non-secret `docker inspect` environment fields:

| Container | Setting | Live value |
| --- | --- | --- |
| PRIME | `PRIME_FAST_MODEL` | `gemma3:1b` |
| PRIME | `PRIME_DEEP_MODEL` | `gemma3:4b` |
| PRIME | `PRIME_EVALUATOR_MODEL` | `gemma3:1b` |
| PRIME | `PRIME_EMBED_MODEL` | `embeddinggemma:300m-qat-q4_0` |
| PRIME | `PRIME_MODEL_KEEP_ALIVE` | `30m` |
| PRIME | `PRIME_CONTEXT_TOKENS` | `8192` |
| PRIME | `PRIME_MAX_OUTPUT_TOKENS` | `2048` |
| PRIME | `PRIME_COMPUTE_PROFILE` | `compat` |
| Ollama | `OLLAMA_KEEP_ALIVE` | `5m` |
| Ollama | `OLLAMA_NUM_PARALLEL` | `1` |
| Ollama | `OLLAMA_MAX_LOADED_MODELS` | `2` |

`ollama ps` showed a resident 2.9-GB `gemma3:4b` runner, `100% CPU`, context 8192, with about 29 minutes remaining at inspection. Selected Ollama log lines show that this model was loaded at `2026-10-02T07:42:10Z`. Direct CPU-thread probes by the performance lane at `08:18:30Z`, `08:18:50Z`, `08:19:06Z`, and `08:19:22Z` varied request-scoped `num_thread` (8, 4, 12, 8), and logs show a new llama-server runner load each time. This strongly suggests incompatible runner options can defeat warm reuse, but the reason was not directly logged. A subsequent normal PRIME parallel test at `08:31:08Z` also triggered a new runner load and measured `8.36s` model `load_duration` despite an earlier `ollama ps` showing residency. Thus the `08:18` reload must **not** be attributed to idle expiry based only on the 36-minute gap; neither failure of the 30-minute keep-alive nor a model switch has been proven. The `sched.go` logs reported CPU mode and one runner loaded; no GPU path was observed (see `PERFORMANCE_GPU_REVIEW.md`).

## Code-path semantics

- `app/settings.py` reads the model names and `PRIME_MODEL_KEEP_ALIVE`.
- `app/model_gateway.py` sends `keep_alive: settings.keep_alive` on `/api/generate` requests. `app/direct_stream.py` and `app/governed_stream.py` send the same field on `/api/chat` requests.
- `app/main.py`'s generic `ollama_post` forwards whatever payload the caller supplied. Its `llm()` `/api/chat` calls and `embed_one`/`embed_many` `/api/embed` calls do **not** add `keep_alive`. Thus, for a direct `/api/chat` call through that path, the server's live `OLLAMA_KEEP_ALIVE=5m` applies; the PRIME 30-minute setting does not automatically apply. This does not prove that the observed 07:42→08:18 reload came from that path.
- Repository search of Python and Compose sources found no explicit `ollama stop` or `keep_alive: 0` unload call. This is evidence of absence in those searched sources, not a claim about all external callers.
- `app/main.py` contains a legacy `/api/chat` route that enters `orchestrate`, but the inspected production PRIME container starts `app.production_entry:app`, which mounts `app.direct_entry:app`, not `app.main:app`. Do not attribute observed production reloads to the legacy route without separate evidence. The production direct-execution path uses `app/direct_stream.py` with the explicit PRIME keep-alive value.

Read-only `compute-queue.db` aggregate (SQLite `mode=ro`; no prompts, results, IDs, or secrets retrieved): 54 total jobs over 19 Sep–2 Oct; 40 completed jobs on `gemma3:4b` and 14 on `gemma3:1b`. Six jobs dated 2 Oct were on `gemma3:4b`; none on `gemma3:1b`. The separate `/data/compute-ledger.db` exists but its `compute_events` table was absent, so it cannot support call-frequency or token-rate claims. The queue is not necessarily a complete census of all chat/model calls.

## Official behavior and limits

[Ollama's FAQ](https://docs.ollama.com/faq) says the default model residency is 5 minutes. The `/api/generate` and `/api/chat` `keep_alive` parameter can specify a duration, `0` for immediate unload, or a negative value for indefinite residency; request `keep_alive` overrides `OLLAMA_KEEP_ALIVE`. It also documents `OLLAMA_NUM_PARALLEL` and `OLLAMA_MAX_LOADED_MODELS`; increasing parallelism scales context memory demand. Ollama's [generate API](https://docs.ollama.com/api/generate) reports `load_duration`, `prompt_eval_duration`, `eval_duration`, and token counts in the response, which are the preferred per-request measures. A longer residency is a latency/memory tradeoff, not proof of higher generation throughput.

## Diagnosis boundary and safe next checks

**Strong correlation:** Changing request-scoped CPU thread settings in the controlled probes accompanied repeated same-model runner reloads, and the following normal PRIME request incurred an 8.36-second load. The configuration difference is a plausible runner-compatibility explanation, not a confirmed internal scheduler cause. **Also true:** legacy generic chat paths lack a 30-minute request override and would fall under the server's 5-minute default, but those routes are not mounted in the inspected production entrypoint. **Not confirmed:** that idle expiry caused any logged reload, that `30m` keep-alive failed, or that model switching/memory pressure was responsible. The current 30-minute PRIME-side setting did preserve model residency through a separate approximately 14-minute idle trial; future like-for-like trials must avoid changing runner options between requests.

For a controlled isolated change, instrument the caller/path and record model name, `load_duration`, prompt-eval tokens/duration, generation tokens/duration, and peak system/container memory. Compare multiple trials at the same prompt/context/output bounds. Only consider changing server default residency or adding a request override after confirming which path experiences repeated cold loads, and verify both memory pressure and production recovery gates. Do not treat CPU utilization or a single load event as a performance verdict.
