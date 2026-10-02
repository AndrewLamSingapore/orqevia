# Performance regression guardrail (isolated candidate)

`benchmarks/performance_regression.py` compares two saved JSON receipts offline. It
does not call PRIME, Ollama, or any production endpoint. It does not claim that
the receipts were measured or that an optimization has passed. The benchmark
producer must record its own raw evidence and use the same workload, model,
context, hardware, and measurement method in both receipts.

Example policy (save as a separate JSON file):

```json
{
  "schema_version": 1,
  "comparability": ["production_image", "model", "workload_id"],
  "metrics": [
    {"path": "latency.first_token_ms_samples", "direction": "lower", "aggregate": "median", "min_samples": 5, "relative_tolerance": 0.05, "absolute_tolerance": 10},
    {"path": "throughput.tokens_per_second_samples", "direction": "higher", "aggregate": "median", "min_samples": 5, "relative_tolerance": 0.05}
  ]
}
```

Run `python benchmarks/performance_regression.py BEFORE.json AFTER.json POLICY.json`.
Exit 0 means every selected metric stayed within its envelope; exit 1 means a
measured regression; exit 2 means invalid, missing, null, non-finite, or
incomparable evidence. A pass is a guardrail result, not proof of host
stability, production acceptance, or a performance gain. The comparator prints
the selected before/after aggregates, limits, sample counts, and decisions as
JSON; preserve this output with the raw receipts.

Use `lower` for latency and resource cost, `higher` for throughput or success
rate. `relative_tolerance` is a fraction (0.05 = 5%); `absolute_tolerance` is in
the metric's unit. For arrays, `median` and nearest-rank `p95` are supported;
the default sample minimum is three. Choose the tolerances and sample floor
*before* evaluating the candidate. A null field is never silently treated as
zero. The comparator performs no significance test, so repeated runs and
manual review of raw distributions remain required for close calls.

Current `PERFORMANCE_BEFORE.json` includes some null first-visible-response
fields. Those fields cannot be used as regression evidence until an instrumented
producer records actual measurements on both sides. Existing production
identity should remain fixed during comparisons unless the test explicitly
qualifies a new image; do not weaken comparability fields to make a pass.
