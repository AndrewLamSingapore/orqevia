# Candidate measured local admission receipt

Golden/default admission remains one atomic endpoint lease. A measured N=1
profile continues to accept the existing `prime.backend-memory.v1` operator
receipt. Every measured profile must pin a nonempty Ollama `runtime_version` and
the exact 64-character hex `digest` of each profiled model; admission checks
the live `/api/version` and `/api/tags` identity before reserving a model.

Measured N=2 or N=3 additionally requires `prime.backend-memory.v2` in the
same `ORQEVIA_BACKEND_MEMORY_RECEIPT` operator-owned, atomically published,
read-only file. The v2 receipt retains all v1 fields and adds:

```json
{
  "schema": "prime.backend-memory.v2",
  "runtime_version": "exact measured Ollama version",
  "model_digests": {"model:name": "exact measured 64-character digest"},
  "resident_leases": ["PRIME job id whose allocation is already reflected in available_mib"]
}
```

The operator producer must identify resident leases from backend execution,
not infer residency from a drop in free memory or from a PRIME pending/running
database state. `captured_at` must be after each lease's dispatch before that
lease can be treated as resident. Admission counts every pending lease and
every running or cancelled-but-uncertain lease without such post-dispatch
residency proof against `available_mib`, then preserves the fixed 2048 MiB
reserve. Completion alone does not refresh memory evidence: the next claim
requires a newer receipt. A stale, incomplete, mismatched or downgraded receipt
holds parallel admission.

This is a source contract only. The operator v2 producer, access control,
fresh host telemetry, SSD thermal qualification and monitored N=2/N=3 runtime
evidence are still required before enabling parallel admission on ABEX. No N=4
admission is implemented or qualified here.
