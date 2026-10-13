> Portfolio status is recorded in [STATUS.md](../STATUS.md). This document describes this repository only; current runtime and deployment claims require evidence from their owning domains.

# External integration candidate

This source is isolated in prime-next. It has not replaced production PRIME.
The authoritative Dell wire description is interface-contract.v1.json. No Dell
filesystem path is asserted. Tests use an ASGI transport fixture, not a native
Dell connection or TLS socket proof.

Use app.interface_server:app as the narrow external ASGI surface, with actual
TLS, proxy-header trust disabled, and the same application data domain as the
single owner worker pool. It exposes only the seven adopted interface routes.
Do not expose app.direct_entry owner APIs or legacy interface aliases externally.
Real certificate/private-key references, adopted peer pin and bounded client
credential provisioning remain deployment inputs. Neither credentials nor keys
are included here. The server's configured SPKI string must be reconciled with
the actual serving certificate; its identity response is not a trust anchor.

## Provider configuration

PRIME_PROVIDER_CATALOG names a local JSON catalog. The supplied unconfigured
catalog has zero models and authorizes zero cloud calls. Each enabled model needs
id, tier (MINI or FLAGSHIP), location cloud, model, HTTPS endpoint, secret_ref,
context_tokens, output_tokens, input_usd_million and output_usd_million. Optional
cached_usd_million, concurrency, max_retries and fallback_ids are explicit inputs.
Configuration stores secret_ref as env:VARIABLE_NAME only. The value is resolved
at transport time from the process environment. Other secret stores can implement
the injected resolver; no OS credential-store adapter is claimed implemented.
Do not put secret values in source, files committed to Git, receipts, prompts,
URLs, public interfaces or logs. No mock credential is a production credential.

Cloud admission requires explicit CLOUD_PERMITTED classification, no recognized
credential pattern, sufficient tier, context/output ceilings, known pricing and
job/daily budgets. Pattern scanning is defense in depth, not a complete DLP engine.
Unmeasured model performance does not count as a measured crossover. Catalog
expected_seconds/cost with measurement_evidence can rank sufficient choices only
when eligible alternatives all have measurements. No pricing/model selection is
supplied by assumption.

Timeout/cancellation stop local request processing; remote cancellation/billing
cannot be guaranteed without provider-specific evidence. Unknown usage and cost
remain null; queue accounting conservatively retains estimated reservations.
Fallback is restricted to explicit same-tier IDs after safe preflight/rejected
admission failures. Partial/ambiguous requests are never automatically replayed.
Local inference defaults to one slot. The optional
`PRIME_CLOUD_QUEUE_PARALLEL_ENABLED=1` adds independent cloud queue workers up to
`PRIME_CLOUD_REQUEST_CAPACITY` (one by default, capped at four). For example,
capacity two permits one Golden local inference plus two cloud requests from
distinct agents. This does not increase local admission, waive provider selection,
locality or budgets, or establish free credits or live qualification. Leave the
option disabled until provider access and any required spending authority are
established. Inline and queued cloud requests share the same cloud capacity.
GET /api/compute-queue/providers/health is owner-authenticated and reports local
readiness separately from unmeasured external health; it makes no external probe.

## Deterministic and trial instrumentation

Explicit sha256/json_format/json_validate objectives bypass inference, use a
bounded content-addressed cache and preserve artifacts under the parent task ID.
Retrieved bytes are rehashed. Duplicate-key/nonfinite JSON is rejected. Verified
deterministic outcomes record zero tokens/cost and actual elapsed time in the
existing compute-ledger database. Cloud completion alone is not a verified outcome.

Structured handoff validation permits only bounded facts/results/evidence and
artifact references, never raw reasoning histories. This helper does not claim
all existing agent paths have migrated to structured handoffs.

Future build_verify attempts now expose model/backend, build/verification latency,
repair cycles, interventions and independent artifact hash validation. Missing
provider tokens/cost and qualitative role/tool/context/handoff scores remain null.
They must be supplied by actual future provider telemetry and trial review, not
inferred from successful transport. The sealed failed unfamiliar-repository trials
are untouched and have not been rerun. Rerun the same sealed cases only after a
real Flagship is configured; preserve case/protocol hashes in the new receipt.

GPU characterization reuses sealed G5 evidence: Radeon 780M Vulkan gemma3:1b is
qualified only for the measured one-worker/30-minute corpus. Vulkan 4b two-worker
inference failed; four-worker 4b was not performed. NPU execution is unmeasured
and unsupported by the tested stack. These limits are not removed by this code.
