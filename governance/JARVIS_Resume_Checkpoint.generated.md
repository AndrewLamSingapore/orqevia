# JARVIS / PRIME Resume Checkpoint

> Generated from `governance/operational-manifest.json`. Do not maintain this file manually.

- Effective status: **STALE**
- Manifest observation: `2026-09-04T03:05:52Z`
- Verification time: `2026-09-04T03:05:52Z`
- Freshness window: `24 hours`

## System facts

| System | Source head | Release | Runtime | Verified | State |
|---|---|---|---|---|---|
| control | `3b522bd5c321` | `3b522bd5c321` | `—` | `2026-09-04T03:05:52Z` | SOURCE_RELEASE_VERIFIED |
| authority | `28645c67f2aa` | `28645c67f2aa` | `28645c67f2aa` | `2026-09-04T03:05:52Z` | ALIGNED_VERIFIED |
| game | `47645107322c` | `47645107322c` | `47645107322c` | `2026-09-04T03:05:52Z` | ALIGNED_VERIFIED |
| portal | `0fadecdbc3d6` | `0fadecdbc3d6` | `0fadecdbc3d6` | `2026-09-04T03:05:52Z` | ALIGNED_VERIFIED |
| prime | `—` | `daeeb30b6319` | `daeeb30b6319` | `2026-09-04T00:39:20Z` | RECHECK_REQUIRED |

## Shared contract

- Version: `2.0.0`
- Publication commit: `a05fa2e3df80733af9ed87068b3526768d4a8394`
- Canonical file: `AndrewLamSingapore/AndrewLamSingapore/portfolio-contracts/manifest.json`

## Branch classification

- Snapshot: `2026-09-04T02:58:00Z`
- Total non-main branches: `112`
- active: `1`
- checkpoint: `11`
- merged: `94`
- rollback: `6`

## Dell acceptance gate

- Command: `JARVIS.cmd status`
- Accepted: `false`
- Last observed runtime: `daeeb30b631954211d30d838821aaca5c72fe037`
- Last status capture: `2026-09-04T00:39:20Z`
- Post-update status: `false`
- Result: Healthy, local-only, approval-gated and no-actuation; acceptance withheld because this status capture predates the later installer/update capture.

## Current blockers

- `dell_status_post_update_required`
- `dell_status_predates_latest_update`

## Resume rule

Re-run the live verifier before relying on this checkpoint. A manifest older than 24 hours is STALE. PRIME may be declared aligned only after a post-update Dell `JARVIS.cmd status` acceptance check.
