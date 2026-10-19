# ORQEVIA naming retirement - 19 October 2026

## Completed in source

- Runtime configuration, Compose, Dockerfiles, scripts, workflows, tests and the
  active client now use `ORQEVIA_*` environment names.
- Internal runtime mounts use `/run/orqevia-*`.
- Active SQLite names are `orqevia-spine.db` and `orqevia-memory.db`. A
  non-destructive startup migration copies an existing legacy database family
  when the current name is absent and leaves the legacy file available for
  rollback.
- The active Interface contract and headers use `orqevia.interface.v1`,
  `X-ORQEVIA-Protocol`, `X-ORQEVIA-PWA` and `X-ORQEVIA-Client-Id`.
- `app/prime_evidence_adapter.py` is now
  `app/orqevia_evidence_adapter.py`.
- The legacy `env_compat` package-wide mirror has been removed.

## Protected exception

Seven files remain byte-identical to the signed certification revision:

- `app/action_records.py`
- `app/objective_api.py`
- `app/agent_cert_event_api.py`
- `app/agent_dispatch_api.py`
- `app/agent_registry.py`
- `app/runtime_status.py`
- `app/compute_catalog.py`

Those files still request historical environment names. A one-way lookup in
`app/protected_env.py` serves them from the current `ORQEVIA_*` values without
changing their bytes. It does not accept legacy-only values.

Dated evidence and pinned Golden fixtures retain their original names and bytes.

## Signed candidate deployment

The Owner approved deployment on 19 October 2026. The exact
`orqevia:final-naming-candidate` image
(`sha256:67af1345345ab8b89b2195507c3ed8343ac1998de79ec81f8494dcaf49346f37`,
source `767f9451d42c65eb905f2c3e5f816536c4e17982`) is deployed for backend and
interface. Post-deploy checks passed for all nine expected containers, Owner
authentication, gateway health and denial, 21/21 queue liveness, and Higgsfield
readiness. Runtime attestation is bound to Golden gen7.

The fresh signed closure was issued before deployment: 29/29 cases, independently
verified against the pinned Azure public key.

## Remaining gate

The seven compatibility files remain byte-identical in this exact signed
candidate. Final legacy-name retirement still requires a separate byte
migration with fresh evidence and a subsequent closure; changing these files
in place would invalidate the current runtime closure binding. The signed
closure's fixed expiry is `2026-10-20T10:21:09.966142+00:00`.
