# ORQEVIA bounded workflow evolution experiment - 5 November 2026

## Implemented result

The fixed experiment compared three executable scheduling workflows against an independently hand-calculated, hash-pinned oracle. It selected reuse of the existing exact scheduling tool on development data and confirmed that selection on disjoint held-out inputs. No production scheduler, routing policy, financial control, model configuration, queue, service or database was modified.

This demonstrates one bounded **compare, evaluate and retain an experimental method** cycle. It does not establish general intelligence, live throughput improvement, autonomous code generation or a new production capability. The exact solver already exists; the new work is the reproducible, provenance-preserving experiment harness and its quality-gated comparison.

## Motivation and scope

`operations/efficiency-sweep-20261102/BENCHMARK-SUMMARY-20261102.json` records a deep-model scheduling trial that failed its quality gate. Its 49.33s elapsed/274.44 CPU-s result is historical motivation only. No live model was rerun here, and no speedup versus that historical trial is claimed.

Task contract: one nonpreemptive slot; start only after arrival; among ready jobs prefer interactive, then arrival, then declaration order; waiting does not consume execution budget. The evaluator has 6 development workloads (17 jobs) and 8 held-out workloads (32 jobs). Input hashes are disjoint. Held-out examples include late starts, future priority arrivals, release-boundary arrivals, tie-breaking, zero duration, unsorted declarations and a finite interactive burst.

Frozen suite SHA256: `a080d94fdd8c182e8281ffbc981b7e7fe40c1da84baf92b6fcaf66dab8e1bc12`.

## Competing implementations

| Candidate | Actual implementation | Tradeoff |
|---|---|---|
| `arrival_fifo` | Sort validated jobs by arrival/declaration; execute sequentially | Minimal baseline; preserves a single slot but ignores the requested interactive priority |
| `release_aware_priority_heap` | Independently implemented ready heap, fed by arrival events | Correct contract, but requires maintaining another scheduling algorithm |
| `existing_exact_tool` | Direct call to existing `app.deterministic_scheduling.solve_schedule` | Reuses an existing capability and avoids an additional production coordinator |

Candidates receive only fresh job-input dictionaries. Expected answers are explicit frozen values in the evaluator, not calls to the candidate solver. Candidate/evaluator separation is functional, not an adversarial sandbox. The release fixes the candidates and evaluator together; the API accepts no arbitrary code, changed scoring rule or permission expansion.

Selection is frozen before held-out results are evaluated: require full development correctness, then prefer fewer new scheduling implementations. Held-out evaluation may confirm or reject that candidate; it cannot retune/reselect another method. A method is retained only if all held-out workloads pass and it produces more correct held-out workloads than the FIFO baseline.

## Measured quality and waits

| Candidate | Development exact pass | Held-out exact pass | Held-out useful completed jobs | Mean held-out interactive wait | Mean held-out background wait |
|---|---:|---:|---:|---:|---:|
| FIFO | 4/6 | 2/8 | 6/32 | 4.533 ticks | 2.000 ticks |
| Priority heap | 6/6 | 8/8 | 32/32 | 2.267 ticks | 3.000 ticks |
| Existing exact tool | 6/6 | 8/8 | 32/32 | 2.267 ticks | 3.000 ticks |

All three returned physically valid nonoverlapping schedules. FIFO fails the specified priority semantics on six held-out workloads. Useful completed jobs count only jobs in workloads that pass the complete, type-strict oracle. Wait ticks are synthetic schedule units, not measured production queue seconds. The higher background wait is visible; this is a priority tradeoff, not universal latency reduction.

Both release-aware methods satisfy the workload contract. Reuse wins the predeclared simplicity tie-break: zero new production scheduling algorithms versus one alternative implementation. The recorded result is `RETAIN_EXPERIMENTAL_METHOD`, `existing_exact_tool`, with six additional correct held-out workloads versus the FIFO baseline. This retention is an experiment finding; it does not activate routing or change admission.

## Timing and resource evidence

Every candidate/split has three measured CPU and wall-clock samples of 128 repeated suite passes, with call counts, median time per call, CPU seconds per correct workload and CPU seconds per useful completed job. Samples include constructing public input dictionaries. Windows process CPU resolution is coarse and the workload is small; the recorded CPU medians do not justify a speed ranking. Wall-clock samples are available for reproducibility but are not used to claim a throughput gain. No models, providers or network were called.

Result from the final source in this child task:

`7cba20c95444bfc5a59cc490ddb016ed1f2850fd7d04159a538a53394e94db26.json`

An earlier pre-metric-extension run `dc8383d65367ae8eb05179cd9a0463c02c4699ccc544d40fd516b8ef15ba3a47.json` remains dated evidence. Both contain source digests; no result was overwritten to disguise that change.

## Persistent learning evidence

Each run records content-addressed `observation -> hypothesis -> experiment -> result` records, with parent IDs, source hashes, suite/input/oracle hashes, candidate answers, quality verdicts, timing samples and limitations. A run ID hashes the result and a new `<run_id>.json` is created exclusively. Existing evidence cannot be overwritten through the writer. No new database, service, scheduler, approval hierarchy or mutable production-policy pointer is introduced.

`run_experiment(output_dir=None)` returns a fixed comparison without writing files. Supplying an explicit evidence directory preserves a new immutable result. It does not inspect or modify production queues, databases, permissions or provider credentials.

## Validation

- `uv run pytest -q tests/test_evolution_experiments.py`: **7 passed** (2.84s after the final code change).
- Strict E9/F lint: passed for the three added files; Ruff formatting: passed.
- Tests cover frozen-evaluator tampering, disjoint held-out inputs, no oracle fields in candidate inputs, fresh-copy isolation, strict value types, overlap/early-start/wait-budget rejection, real comparison and content-addressed evidence, overwrite rejection, and rejection when the development-selected method fails held-out evaluation.
- Parent owns full-session regressions, CI and deployment; this child performed no commit, push or deployment.

Reproduce with:

```powershell
uv run pytest -q tests/test_evolution_experiments.py
uv run python scripts/run_evolution_experiment.py --output C:/Users/Admin/Documents/ABEX/operations/reboot-sweep-20261105/evolution-experiment
```

## Remaining limitations and next cycle

The held-out set is authored independently from candidate code, disjoint from development inputs, but visible in released source. It is suitable for a controlled regression comparison, not an uncontaminated general-intelligence benchmark. The design evaluates known fixed workflows; it does not safely execute arbitrary generated Python or claim an autonomous research breakthrough.

Next: collect a representative set of independently withheld owner scheduling missions, freeze their evaluation before proposing any new method, and compare the existing exact tool with current routing on those workloads. Record end-to-end mission success, actual CPU and queue seconds, fairness and recovery. Only then consider a scoped production-routing change. No production change is authorized merely by this synthetic result.
