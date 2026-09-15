# JARVIS PRIME

Start with [the canonical operational SSOT](https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json) and
[the shared channel contract](governance/CHANNEL_CONTRACT.md).

Architecture v1 is the sole intended architecture: ABEX PRIME, authenticated
Dell/mobile/voice clients, 21 agents, deterministic/local/cloud routing and direct
observed execution with narrow consequential controls. Runtime acceptance is
recorded separately and must not be inferred from this README or passing CI.

`system.manifest.json` binds product components; it is subordinate to the operational
manifest. `deploy/product-runtime-v1.json` defines entrypoints and external inputs.

Validate with `python scripts/validate_ssot.py` and
`python scripts/check_canonical_state.py`. Run `scripts/run_canonical_ci.py` with
isolated PRIME_DATA_DIR and PRIME_COMPUTE_QUEUE_DB. PWA checks live in clients/pwa;
Dell packaging instructions are in clients/dell/PACKAGING.md. Dell synchronization
and independent reconciliation tools remain under tools/ and docs/DELL_*.md.

Credentials, production data and provider qualification remain external. Retain
the sealed ABEX baseline. Historical source and migration evidence remain in Git.
