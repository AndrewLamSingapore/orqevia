# Portal → PRIME Verification Gate

This branch must not be promoted unless `.github/workflows/portal-integration.yml` passes.

The gate verifies:

1. Python compilation.
2. Contract and routing unit tests.
3. A real Portal aquarium candidate fixture emits a validated VELYQUA-targeted ExperimentSpec.
4. FastAPI ingestion, persistence, retrieval and idempotency.
5. Untrusted source rejection.
6. The composed runtime exposes `/api/integrations/portal/experiments`.
7. The production Docker image builds using `app.entry:app`.

Safety invariant: `verified` is never automatically upgraded to `approved`. External or physical execution still requires explicit owner approval.
