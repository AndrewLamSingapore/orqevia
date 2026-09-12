# JARVIS / PRIME Resume Checkpoint

> Generated from `governance/operational-manifest.json`. Do not maintain this file manually.

- Effective status: **STALE**
- Manifest observation: `2026-09-12T08:51:19.749633Z`
- Verification time: `2026-09-07T07:12:00Z`
- Freshness window: `24 hours`

## System facts

| System | Source head | Release | Runtime | Verified | State |
|---|---|---|---|---|---|
| control | `f3fec388a29c` | `f3fec388a29c` | `—` | `2026-09-12T07:06:43.552309Z` | SOURCE_RELEASE_VERIFIED |
| authority | `90f2a487a8d8` | `90f2a487a8d8` | `90f2a487a8d8` | `2026-09-12T08:51:19.749633Z` | SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED |
| game | `49e7bfab2c32` | `49e7bfab2c32` | `49e7bfab2c32` | `2026-09-12T07:06:43.552309Z` | SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED |
| portal | `0d6b2bc8089b` | `0d6b2bc8089b` | `0d6b2bc8089b` | `2026-09-12T08:51:19.749633Z` | SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED |
| prime | `—` | `c449dd1c8e22` | `c449dd1c8e22` | `2026-09-07T07:12:00Z` | ALIGNED_VERIFIED |
| sky | `2de175dc61a0` | `2de175dc61a0` | `2de175dc61a0` | `2026-09-12T08:51:19.749633Z` | SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED |
| velyqua | `8177e7d79f1d` | `8177e7d79f1d` | `8177e7d79f1d` | `2026-09-12T07:06:43.552309Z` | SOURCE_RUNTIME_ALIGNED_DEPLOYMENT_ID_UNVERIFIED |

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
- Last observed runtime: `c449dd1c8e22976c97507733201807d4d73bf92e`
- Last status capture: `2026-09-07T07:12:00Z`
- Post-update status: `true`
- Result: Healthy, local-only, approval-gated and no-actuation. Harness v0 pilot is ready for a14, a16 and a21; cloud overflow is disabled and local inference concurrency is one.

## Published software and remaining implementation

- PRIME published image: `ghcr.io/andrewlamsingapore/prime:sha-c449dd1`
- A published image does not establish Dell installation or active agents.
- registry: v1.1 source merged and image published; public 29-agent/six-lead projection, read-only runtime health, and latest release activation verified
- harness_v0: Dell pilot runtime deployed and status verified for a14, a16 and a21; functional dispatch/lease acceptance exercises and ABEX commissioning remain pending
- hermes_agentscope: cognition-only integrations require Harness v0; not activated
- predictive_ml: awaits sufficient real sensor data
- velyqua: acquisition integrity implemented; full quality policy enums unrecovered
- portal_inhabitants: concept recovered; implementation pending
- sky_tablet: current source and production artifact content are hash-aligned; exact Vercel deployment identity remains unverified
- glm_track_1: full wrapper and logging contract not recovered
- checkpoint_repair: PRIME image sha-c449dd1 deployed on Dell; post-update health and Harness v0 pilot status verified
- Branch protection: VELYQUA_MAIN_PROTECTED_VERIFIED

## Current blockers

- `vercel_api_not_verified:authority`
- `vercel_api_not_verified:game`
- `vercel_api_not_verified:portal`
- `vercel_api_not_verified:sky`
- `vercel_api_not_verified:velyqua`
- `verification_expired:dell_runtime`
- `verification_expired:manifest`
- `verification_expired:prime`
- `verification_expired:shared_contract`

## Resume rule

Re-run the live verifier before relying on this checkpoint. A manifest older than 24 hours is STALE. PRIME may be declared aligned only after a post-update Dell `JARVIS.cmd status` acceptance check.
