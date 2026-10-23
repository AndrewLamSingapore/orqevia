# Fixed fabric integration contracts

The collective registry observes actual contracts. Its entries do not grant
execution permission and are not mandatory dependencies of fabric execution.

The queue completion adapter publishes execution metadata into the existing
event fabric. It preserves the frozen event contract's `prime` source
identifier. Only hashes, agent attribution, execution identity and provenance
are projected; model prompts and answers are not copied into these events.
The four projectors create an unpromoted memory candidate, graph observation,
review disposition and evaluation record. Readiness checks compare their
persisted contents with the actual completed queue execution. Replaying an
identical event reuses its projections; changed content with the same event ID
is rejected. The narrow authenticated endpoint is
`GET /api/collective/v1/fabrics/events`; completed execution replay uses the
existing source-bound `POST /api/collective/v1/jobs/{job_id}/publish`.

The MLP adapter loads one release-reviewed, data-only JSON artifact, pinned by
its complete file SHA-256. It verifies those exact bytes on access, including
when a model is cached. `scripts/build_mlp_reference.py` is an offline pipeline
and never an application training endpoint. Its disclosed synthetic quadratic
reference was independently checked at 59 unseen numerical points: mean
absolute error 0.15043, maximum absolute error 0.52493 over the reference
domain. These are reference-model measurements, not product benchmarks or
agent qualifications.

The owner-only MLP endpoints are
`GET /api/collective/v1/fabrics/mlp` and
`POST /api/collective/v1/fabrics/mlp/infer`. The latter accepts 1–32 finite
`{"x": value}` rows within [-3.0, 2.9], plus a bounded `trace_id`. It records
model, artifact, input and output digests without persisting raw input. Trace
reuse with changed input is rejected. Session-facing routes use the existing
same-origin, bound-owner gateway under `/interface/v1/collective/`. This
reference is an approximation and grants no agent execution authority.
`MLPCapabilityFabric.infer_for_agent` still requires independently verified
capability decisions and actual certification; this release creates neither.

The Hugging Face adapter performs read-only inspection of the existing queue
and the task/agent-bound execution ledger. A queue's selected primary provider
alone is insufficient: the actual executed provider, model, usage and cost must
agree. A successful fallback through another provider cannot qualify the
requested primary. Disabled providers, missing or malformed receipts, failed
latest attempts and observations older than 24 hours are unavailable. Registry
reconciliation never submits cloud work, resolves new credentials, changes
budgets or automatically spends money. Recorded provider-usage costs remain
unreconciled with invoices unless the existing billing system reconciles them.

Actual release acceptance must test API authentication, owner isolation, real
model execution, durable evidence, event readback, replay, replacement denial,
registry evidence and restart recovery. Staging leaves cloud providers disabled;
live cloud acceptance requires separately observed production execution.
Unit fixtures alone do not establish live readiness. Retain an explicit
environment and timestamp for every acceptance claim.
