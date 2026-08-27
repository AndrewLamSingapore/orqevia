# Portal → PRIME Runtime

`POST /api/integrations/portal/experiments` accepts a version 1.0 Portal `ExperimentCandidate`, validates its identity and evidence boundary, routes it through PRIME's existing specialist selector, emits a bounded `ExperimentSpec`, validates it, and persists the canonical candidate/spec pair in PRIME's local SQLite state.

`GET /api/integrations/portal/experiments/{candidate_id}` retrieves the persisted handoff.

Ingestion is idempotent by Portal `candidate_id`.

## Verification semantics

The current first runtime uses deterministic PRIME routing and contract verification. It does not fabricate an LLM research result. Provenance-bearing candidates can become `verified`; candidates without provenance remain `draft` with `EVIDENCE_REQUIRED`. Neither state grants execution authority.

## Execution authority

A generated spec may target `velyqua` when aquarium/water/ecology/sensor concepts are present, but it never becomes `approved` automatically. External or physical execution remains explicitly owner-gated.

## Runtime composition

The Docker image starts `app.entry:app`. `app.entry` imports the existing PRIME FastAPI application unchanged and attaches the Portal integration router. This avoids invasive modification of the large existing `app/main.py` runtime.
