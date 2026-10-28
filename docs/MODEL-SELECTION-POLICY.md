# Owner model-selection supersession - 28 October 2026

This is the current selection policy. It supersedes earlier instructions to
always use Gemma 3 12B, always use the largest model, exclude alternatives by
name, or require one provider for all ORQEVIA work. Historical receipts and
archived instructions retain their original bytes and dates.

No model or provider has exclusive inference authority. Existing models and
adapters are reusable choices. Selection follows task capability, authorization,
quality checks, measured resource use, context needs and availability.

1. Use deterministic code, structured queries and authorized validated results
   when they fully satisfy the task.
2. Use the configured lightweight model for narrow tasks after representative
   correctness checks. Gemma 3 1B is an installed candidate, not a universal rule.
3. Use a qualified deep model for complex reasoning. Gemma 3 12B remains available
   and must not be silently replaced when a task needs its measured capability.
4. Use embedding models for embeddings. Do not generate prose to calculate a
   hash, check a schema or report ordinary service readiness.
5. Other compatible local or cloud models may be qualified. No new installation,
   download, external disclosure or paid call is implied by this policy.

Preserve model identity, digest, prompt/configuration and quality evidence in
receipts. Keep comparison and acceptance runs consistent; qualify a changed
model without rewriting historical results. Independent verification must remain
independent. An unavailable qualified model does not justify an untested downgrade.

The existing fast/deep/evaluator/embedding roles are configurable responsibilities,
not exclusive vendor or model requirements. Preserve credentials, TLS, access
controls, data residency and spending safeguards.

Current runtime still configures 1B as fast and 12B as deep/evaluator. Source
changes and qualification tests do not establish deployment. The Owner's durable
background pause stays in effect until an explicit authorized resume.
