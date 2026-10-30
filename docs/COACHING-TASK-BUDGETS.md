# Coaching execution budgets

The running producer used a fixed 300-second execution budget. On 30 October,
eight probability-foundation jobs reached that budget while still producing
output; the original failures and partial results remain in the existing queue.
These failures were distinct from the structured primary-role cases, whose
existing 600-second qualification budget had successful current-model evidence.

The producer now submits 600 seconds for `role` work and 1800 seconds for
`probability-foundations`. These are active execution budgets. Time waiting for
the existing coordinator, model loading/first progress, stalled output and
persistence are governed by their existing separate mechanisms. This change
does not increase inference concurrency, retry count or cloud spending.

An explicit `ORQEVIA_COACHING_EXECUTION_SECONDS` applies to both task families.
`ORQEVIA_COACHING_ROLE_EXECUTION_SECONDS` and
`ORQEVIA_COACHING_PROBABILITY_EXECUTION_SECONDS` override their own family.
Settings remain finite and bounded from 60 to 7200 seconds. Unknown programs
are rejected. Malformed settings fall back to their valid task-family default.

The existing idempotency bindings, source-bound cohort history, semantic oracles,
Owner background-admission state and HOME_ECO resource policy remain intact.
Reconstruction observes an already accepted job with its original budget;
changing a setting does not rewrite or resubmit that job. New submissions use
the selected program budget. Baseline, practice and acceptance remain separate.

`deploy/coaching-budget-overlay.Dockerfile` reuses the exact installed coaching
image and dependencies and copies only the controller and its small budget
helper module. It replaces the existing producer role, not the backend or model
service. The release must retain the old container for rollback, preserve data
mounts and cohort-source identity, update the Windows supervisor's implementation
pin to the actual new image/source, and verify the next natural submission.

Focused tests exercise actual controller submission for both programs, waiting
job recovery without duplication, explicit overrides, invalid settings, zero
cloud disclosure/cost and unchanged retries. Source tests do not themselves
establish deployed behavior or model-answer correctness. Keep implementation,
test, deployment, enforcement and observed runtime receipts distinct under the
[Intelligent Efficiency Doctrine](INTELLIGENT_EFFICIENCY_DOCTRINE.md).
