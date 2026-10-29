# Deep-reasoning correctness - deterministic lane resolution

Dated engineering record, 29 October 2026. Candidate source only; nothing here
is deployed to production. The production background pause remains generation 0.

## The recorded failure

The 2026-10-28 deep-lane qualification (`gemma3:12b`) answered a synthetic
single-slot nonpreemptive scheduling task by preempting the occupied slot:
I1 at 5-15 and B2 at 8-28, violating the nonpreemptive constraint. The
independent oracle expects I1 at 40-50 (wait 35) and B2 at 50-70 (wait 42).

The 2026-10-29 bounded re-qualification at 4 threads reproduced the identical
wrong answer, so the model failure is stable, not noise. Both receipts are
preserved:

- Original: `reports/infrastructure-optimization/20261028T071443Z/eco-deep-thread-comparison.json`
- Re-qualification: `reports/deep-correctness-20261029/eco-deep-requalification.json`

## Resolution without weakening the oracle

1. `app/deterministic_scheduling.py` computes the exact nonpreemptive
   single-slot schedule from first principles: at every release point the slot
   takes interactive before background, then earliest arrival, then declaration
   order; waiting never consumes the execution budget. The solver reproduces
   the trial oracle exactly (`oracle_matches_deterministic: true`).

2. The formulaic scheduling class is served by the existing deterministic lane
   through `deterministic_operation='schedule_single_slot'` on the internal
   dispatch API (`/api/agents/dispatch`). Zero model calls; the result is
   bound to a provenance artifact exactly like `sha256` and `json_validate`.

3. `check_answer` is the exact cross-check gate for any model-produced schedule.
   It rejects the recorded deep failure (`answer-values-or-types-mismatch`) and
   accepts only values, types and key sets identical to the deterministic
   solution. The deep benchmark now records both the gate verdict and the
   oracle-vs-solver agreement, with the oracle itself byte-identical to before.

The deep model is no longer trusted for this formulaic class. Genuinely deep
reasoning remains separately qualified, as the P0 mission requires.

## Evidence

- New solver and gate tests: `tests/test_deterministic_scheduling.py`
  (20 tests, including end-to-end dispatch with artifact roundtrip).
- Regression run: dispatch, deterministic ops, routing, production
  compatibility and integration suites pass. One pre-existing failure
  (`test_external_surface_has_no_owner_or_legacy_routes`) fails identically on
  the untouched parent branch and is unrelated.
- Bounded deep re-qualification receipt preserved with
  `production_background_pause_preserved: true`; live check after the run:
  pause still 1, no running/held jobs, three queued records retained.

## Not deployed

Production backend remains `f37673b4`. Deployment of this candidate requires
the established release window (backend image rebuild and recreation), which is
not performed while the Owner-authorized Docker maintenance mission is live.
Background production admission remains paused until an explicit Owner resume.
