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

## Remaining gate

A new protected, signed certification closure must be issued before these seven
files can be renamed and the one-way lookup removed. Changing the bytes first
would invalidate the existing signed admission boundary, so that step is not
part of this migration.
