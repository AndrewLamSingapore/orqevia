# Closed Evidence Loop

The repository now implements the complete bounded software path:

1. The Portal emits a versioned ExperimentCandidate.
2. PRIME validates and persists an ExperimentSpec.
3. VELYQUA records explicit observation-only owner approval and attributable evidence.
4. VELYQUA's ordered transactional outbox sends authenticated version 1.0 events to PRIME.
5. PRIME validates identity, account ownership, state order and provenance; stores events idempotently; and produces a deterministic evidence summary.
6. PRIME's result outbox returns authenticated versioned results to The Portal.
7. The Portal persists only monotonic results and attaches them to matching graph nodes.

Scientific support is never inferred from observation counts. Results state only protocol status and whether attributable evidence was collected. No result authorizes dosing, medication, diagnosis, mains switching, device control or autonomous livestock care.

Runtime secrets are configuration only:

- PRIME_INTEGRATION_TOKEN authenticates VELYQUA events and administrative flush requests.
- PORTAL_RESULT_URL is the exact Portal result endpoint.
- PORTAL_RESULT_TOKEN authenticates PRIME results at The Portal.

Until the persistent PRIME host and the corresponding Portal environment variables are configured and verified, repository completion does not imply a running production loop.
