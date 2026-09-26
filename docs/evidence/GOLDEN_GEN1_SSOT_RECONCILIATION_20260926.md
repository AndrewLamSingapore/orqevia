# Golden Generation 1 SSOT reconciliation

Verdict: **PASS**  
Scope: documentation/governance reconciliation only; production remained unchanged.

## Classification

| Surface | Classification | Authority/scope |
|---|---|---|
| `STATUS.md` | CANONICAL | human current status |
| `docs/JARVIS-PRIME-GOLDEN-BASELINE-ARCHITECTURE.md` | CANONICAL | Golden Gen 1 architecture |
| `governance/golden-gen1-manifest.json` | CANONICAL | Golden Gen 1 machine identity |
| `config/agent_registry.json` at `17fad78d...` | CANONICAL | agent role/capability truth |
| ABEX production runtime | CANONICAL | live deployed behavior/state |
| server identity/session and task/artifact stores | CANONICAL | their owned record categories |
| `governance/operational-manifest.json` | DERIVED / MACHINE STATUS | cross-system observation; local PRIME acceptance embedded, global status may be stale |
| `governance/JARVIS_Resume_Checkpoint.generated.md` | DERIVED | replaceable human mirror |
| `system.manifest.json`, `deploy/product-runtime-v1.json`, Compose files, PWA manifest | DERIVED PRODUCT/DEPLOYMENT CONTRACTS | implementation inputs, not live proof |
| ABEX runtime receipt, corrected Dell artifact, acceptance record | EVIDENCE | bind source/build/runtime/acceptance |
| commissioning and repair reports | HISTORICAL / EVIDENCE | preserved, generation-scoped |
| old 29-agent registry fixture, stale images/sources, prior Dell FAIL | HISTORICAL / SUPERSEDED | never current truth |
| Phase 2 branches/documents | CANDIDATE | cannot override Gen 1 or production |

## Repository reconciliation

- Accepted runtime source `17fad78d410dca5d9101483cb777a2b9b619bac3` is remotely reachable on the production lineage.
- Governance acceptance is remotely merged at `234ed6041f78b253eaa83ee9e15f4badc9ff0cf8`.
- Golden freeze work began from that clean remote lineage.
- Candidate branches were not merged into Gen 1.
- `origin/main` is a distinct development lineage and is not used as runtime evidence.

## Source-to-runtime reconciliation

All authoritative identities agree on source `17fad78d...`, image `prime:sha-17fad78`, image ID `sha256:745244...`, PWA `jarvis-shell-v11`, registry schema `2.0`, 21 logical agents, receipt digest `49c6668f...`, Dell verification `f5a6f344...`, and accepted runtime state `VERIFIED`.

## Contradiction handling

Active current surfaces no longer present the superseded 29-agent schema, old images, missing receipt or `prime.state=unverified` as current local PRIME truth. Those statements remain inside historical evidence where necessary. Global portfolio staleness, Wuhan physical verification and long-duration stability remain explicitly separate gates.

## Golden freeze test

All critical questions are YES: exact source, image, runtime receipt, registry, authority contract, PWA generation, data stores, rollback target, independent Dell boundary and historical/current separation are reconstructable from committed references. No critical material is chat-only.
