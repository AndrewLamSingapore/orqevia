# JARVIS / PRIME Resume Checkpoint

> Generated from `governance/operational-manifest.json`. Do not maintain this file manually.

- Effective status: **STALE**
- Manifest observation: `2026-09-07T05:50:06Z`
- Verification time: `2026-09-07T05:50:06Z`
- Freshness window: `24 hours`

## System facts

| System | Source head | Release | Runtime | Verified | State |
|---|---|---|---|---|---|
| control | `98a1b745ad21` | `98a1b745ad21` | `—` | `2026-09-07T05:50:06Z` | SOURCE_RELEASE_VERIFIED |
| authority | `b2bdf9863e26` | `b2bdf9863e26` | `b2bdf9863e26` | `2026-09-07T05:50:06Z` | ALIGNED_VERIFIED |
| game | `85a5ff8dd064` | `85a5ff8dd064` | `85a5ff8dd064` | `2026-09-07T05:50:06Z` | ALIGNED_VERIFIED |
| portal | `d117c918ee42` | `d117c918ee42` | `d117c918ee42` | `2026-09-07T05:50:06Z` | ALIGNED_VERIFIED |
| prime | `—` | `4ca0be64ccc4` | `daeeb30b6319` | `2026-09-07T05:50:06Z` | RUNTIME_HEALTHY_RELEASE_UPDATE_PENDING |
| sky | `006e4a39b785` | `006e4a39b785` | `006e4a39b785` | `2026-09-07T05:50:06Z` | ALIGNED_VERIFIED |
| velyqua | `7a4f32d81f5e` | `7a4f32d81f5e` | `7a4f32d81f5e` | `2026-09-07T05:50:06Z` | ALIGNED_VERIFIED |

## Shared contract

- Version: `2.0.0`
- Publication commit: `a05fa2e3df80733af9ed87068b3526768d4a8394`
- Canonical file: `AndrewLamSingapore/AndrewLamSingapore/portfolio-contracts/manifest.json`

## Branch classification

- Snapshot: `2026-09-04T03:14:47Z`
- Historical branch cohort (not live total): `112`
- active: `0`
- checkpoint: `11`
- merged: `95`
- rollback: `6`

## Dell acceptance gate

- Command: `JARVIS.cmd status`
- Accepted: `true`
- Last observed runtime: `daeeb30b631954211d30d838821aaca5c72fe037`
- Last status capture: `2026-09-07T05:50:06Z`
- Post-update status: `true`
- Result: Healthy, local-only, approval-gated and no-actuation. Read-only ChatGPT tunnel and system_health call verified; published PRIME release remains newer than the running image.

## Published software and remaining implementation

- PRIME published image: `ghcr.io/andrewlamsingapore/prime:sha-4ca0be6`
- A published image does not establish Dell installation or active agents.
- registry: v1.1 source merged and image published; public 29-agent/six-lead projection and read-only runtime health verified; latest release activation pending
- harness_v0: ABEX commissioning and acceptance pending
- hermes_agentscope: cognition-only integrations require Harness v0; not activated
- predictive_ml: awaits sufficient real sensor data
- velyqua: acquisition integrity implemented; full quality policy enums unrecovered
- portal_inhabitants: concept recovered; implementation pending
- sky_tablet: source and current production artifact recovered, deployed and content-hash verified
- glm_track_1: full wrapper and logging contract not recovered
- checkpoint_repair: Authority build repaired in PR45; Sky Tablet production aligned; SSOT refreshed from live GitHub, Vercel and read-only Dell evidence
- Branch protection: VELYQUA_MAIN_PROTECTED_VERIFIED

## Current blockers

- `release_runtime_drift:prime`

## Resume rule

Re-run the live verifier before relying on this checkpoint. A manifest older than 24 hours is STALE. PRIME may be declared aligned only after a post-update Dell `JARVIS.cmd status` acceptance check.
