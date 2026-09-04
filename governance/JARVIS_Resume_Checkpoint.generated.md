# JARVIS / PRIME Resume Checkpoint

> Generated from `governance/operational-manifest.json`. Do not maintain this file manually.

- Effective status: **STALE**
- Manifest observation: `2026-09-04T03:14:47Z`
- Verification time: `2026-09-04T03:14:47Z`
- Freshness window: `24 hours`

## System facts

| System | Source head | Release | Runtime | Verified | State |
|---|---|---|---|---|---|
| control | `98a1b745ad21` | `98a1b745ad21` | `—` | `2026-09-04T03:14:47Z` | SOURCE_RELEASE_VERIFIED |
| authority | `b1fa520f8916` | `b1fa520f8916` | `b1fa520f8916` | `2026-09-04T03:14:47Z` | ALIGNED_VERIFIED |
| game | `85a5ff8dd064` | `47645107322c` | `47645107322c` | `2026-09-04T03:14:47Z` | SOURCE_AHEAD_OF_PRODUCTION |
| portal | `d117c918ee42` | `d117c918ee42` | `d117c918ee42` | `2026-09-04T03:14:47Z` | ALIGNED_VERIFIED |
| prime | `—` | `daeeb30b6319` | `daeeb30b6319` | `2026-09-04T00:39:20Z` | RECHECK_REQUIRED |

## Shared contract

- Version: `2.0.0`
- Publication commit: `a05fa2e3df80733af9ed87068b3526768d4a8394`
- Canonical file: `AndrewLamSingapore/AndrewLamSingapore/portfolio-contracts/manifest.json`

## Branch classification

- Snapshot: `2026-09-04T03:14:47Z`
- Total non-main branches: `112`
- active: `0`
- checkpoint: `11`
- merged: `95`
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
- `source_release_drift:game`

## Resume rule

Re-run the live verifier before relying on this checkpoint. A manifest older than 24 hours is STALE. PRIME may be declared aligned only after a post-update Dell `JARVIS.cmd status` acceptance check.
