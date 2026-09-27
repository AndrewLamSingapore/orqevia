# JARVIS PRIME

Start with [STATUS.md](STATUS.md) for current status, then the
[machine-readable operational reference](https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json) and
[the shared channel contract](governance/CHANNEL_CONTRACT.md).

STATUS.md is the only current status source of truth. The operational reference
records architecture, component revisions and observations; it cannot establish
current status.

Golden Generation 2 is the frozen accepted non-audio architecture, described by
`docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md` and
`governance/golden-gen2-manifest.json`. Golden Generation 1 and its immutable
manifest remain the preserved rollback/reference. Architecture v1 remains the
implementation foundation: ABEX PRIME, authenticated
Dell/mobile/voice clients, 21 agents, deterministic/local/cloud routing and direct
observed execution with narrow consequential controls. Runtime acceptance is
recorded separately and must not be inferred from this README or passing CI.

`system.manifest.json` binds product components; it is subordinate to STATUS.md for
status and to the operational reference for component identity. `deploy/product-runtime-v1.json`
defines entrypoints and external inputs.

Validate with `python scripts/validate_ssot.py` and
`python scripts/check_canonical_state.py`. Run `scripts/run_canonical_ci.py` with
isolated PRIME_DATA_DIR and PRIME_COMPUTE_QUEUE_DB. PWA checks live in clients/pwa;
Dell packaging instructions are in clients/dell/PACKAGING.md. Dell synchronization
and independent reconciliation tools remain under tools/ and docs/DELL_*.md.

Credentials, production data and provider qualification remain external. Retain
the sealed ABEX baseline. Historical source and migration evidence remain in Git.


## Public experience and connected projects

[Explore JARVIS PRIME](https://authority-engine-app.vercel.app/jarvis) presents curated decision examples and the public agent registry. [Discuss a use case with Andrew](https://authority-engine-app.vercel.app/contact?source=jarvis&intent=collaboration).

The public contract is `governance/public-experience.json`. Authority Engine, The Portal, Living Worlds, Sky Tablet and VELYQUA link to that experience. Navigation and enquiry context do not grant private runtime access or merge product databases.

STATUS.md is the only current status record. The operational manifest and its generated resume checkpoint are machine references, not second status authorities. Historical deployment identities belong in explicitly historical evidence fields and cannot occupy current PRIME runtime fields.
