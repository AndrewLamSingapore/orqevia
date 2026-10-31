# Smallest reversible proof of concept

No new service, model, container or cloud call is necessary for the first test.

1. Use isolated SQLite fixtures and the existing WorkerPool. Concurrently submit
   work through independent database connections; demonstrate one local owner,
   priority ordering, eventual background progress and bounded queue admission.
2. Exercise all21 actual registry IDs with deterministic fixture tool execution,
   persisted results and lifecycle events. Label this scheduler/integration
   evidence, not model inference, specialist quality or certification.
3. Simulate hours of queue waiting without spending active budget. Test finite
   first-progress, stalled-generation, active, persistence and total budgets.
   Test cancellation holding a slot until the actual coroutine closes.
4. Reopen the same isolated DB to test expired-worker recovery, original job IDs,
   bounded retries, backoff and idempotency conflicts. Never replay ambiguous
   external effects merely because a worker lease expired.
5. Run the read-only compliance observer against production and preserve actual
   NOT_ENFORCED/NOT_VERIFIED results. Current code versions and model residency
   must not be inferred from the candidate worktree.
6. After approved deployment, repeat a labeled representative workload with the
   same model digest, options, prompts, cold/warm state and output oracles.
   Record attempts, failures, queue wait, load/prefill/generation, TTFT, tokens/sec,
   resource time series and responsiveness. Report sample sizes and uncertainty.
7. Evaluate selective-agent routing against the existing default-one baseline,
   not a hypothetical21-agent fan-out. Include independent verification cases.
8. Only after that, request a separate native-MoE model-download/benchmark decision
   and a separate bounded cloud-quality experiment if justified.

First measured source validation:106 focused tests passed initially, including
21 deterministic scheduler pipelines; a broadened regression run subsequently
passed137 tests plus73 subtests. Full production model-quality tests, resource
before/after comparisons and deployment recovery remain NOT VERIFIED.

Prior read-only query optimization experiments were rejected: a window-query
candidate was slower than baseline on a6915-row in-memory journal copy, and a
grouped candidate also failed to improve its paired baseline. No query speedup
or hardware inference speedup is claimed. Preserve failed experiments.
