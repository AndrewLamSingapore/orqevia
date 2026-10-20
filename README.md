# ORQEVIA · 奥启维亚

**One workspace for ideas, evidence and useful execution.**

[Explore the public walkthrough](https://authority-engine-app.vercel.app/orqevia) · [Discuss a use case](https://authority-engine-app.vercel.app/contact?source=orqevia&intent=collaboration)

ORQEVIA brings planning, tools and traceable results into an authenticated workspace. The public walkthrough explains its purpose; private work remains access-controlled.

Read [STATUS.md](STATUS.md) for current portfolio status claims, then the
[machine-readable operational reference](https://github.com/AndrewLamSingapore/orqevia/blob/main/governance/operational-manifest.json) and
[the shared channel contract](governance/CHANNEL_CONTRACT.md).

Each product owns its source, configuration, contracts, and domain records in its
repository. STATUS.md records portfolio status and evidence classification only.
The operational reference records architecture, component revisions and dated
observations; it cannot establish current runtime status.

Golden Generation 4 is a historical non-audio baseline, recorded in
`governance/golden-gen4-manifest.json`. Read the latest dated STATUS.md entry
and its runtime receipts before identifying the deployed generation. Pre-gen4
baselines were removed on 2026-10-16 per Owner order and remain recoverable
from Git history. The living architecture reference is
`docs/TOTAL-INTEGRATION-ARCHITECTURE.md`. Architecture v1 remains the
implementation foundation: ABEX PRIME, authenticated
Dell/mobile/voice clients, 21 agents, deterministic/local/cloud routing and direct
observed execution with narrow consequential controls. Runtime acceptance is
recorded separately and must not be inferred from this README or passing CI.

`system.manifest.json` binds PRIME product components. `deploy/product-runtime-v1.json`
defines entrypoints and external inputs.

Validate with `python scripts/validate_canonical.py` and
`python scripts/check_canonical_state.py`. Run `scripts/run_canonical_ci.py` with
isolated ORQEVIA_DATA_DIR and ORQEVIA_COMPUTE_QUEUE_DB. PWA checks live in clients/pwa;
Dell packaging instructions are in clients/dell/PACKAGING.md. Dell synchronization
and independent reconciliation tools remain under tools/ and docs/DELL_*.md.

Credentials, production data and provider qualification remain external. Retain
the sealed ABEX baseline. Historical source and migration evidence remain in Git.


## Public experience and connected projects

[Explore ORQEVIA](https://authority-engine-app.vercel.app/orqevia) presents curated decision examples and the public agent registry. [Discuss a use case with Andrew](https://authority-engine-app.vercel.app/contact?source=orqevia&intent=collaboration).

The public contract is `governance/public-experience.json`. Authority Engine, The Portal, Living Worlds, Sky Tablet and VELYQUA link to that experience. Navigation and enquiry context do not grant private runtime access or merge product databases.

STATUS.md records current portfolio status claims. The operational manifest and its generated resume checkpoint are machine references, not second status records. Historical deployment identities belong in explicitly historical evidence fields and cannot occupy current PRIME runtime fields.
