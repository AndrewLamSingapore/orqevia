> Current ABEX runtime, 29 October 2026: Guardian is deployed and enforced in
> persistent HOME_ECO, with Owner-resumed OPEN generation1. Offline backup and
> logging remain parked. [Live acceptance](LIVE-ACCEPTANCE-20261029.md) supersedes
> the earlier candidate-only or paused-state statements below. Earlier measurements
> and failure records remain dated evidence, not current deployment instructions.

# Candidate deployment and rollback

The source is based on the saved, unmerged PR 467 candidate. It must not be
mistaken for production main or deployed from an unrelated checkout.
No production release or default HOME_ECO activation was performed.

## Reproduce safe checks

```powershell
python -m pytest -q tests/test_resource_guardian.py tests/test_home_eco.py tests/test_background_admission.py tests/test_job_queue.py tests/test_measured_compute_profile.py tests/test_host_metrics.py
uvx --offline --from ruff==0.17.1 ruff check app/resource_guardian.py app/resource_process.py app/job_queue.py scripts/resource_guardian.py benchmarks/resource_guardian/run_bounded.py tests/test_resource_guardian.py --select E9,F
python benchmarks/resource_guardian/run_bounded.py --output C:/Users/Admin/Documents/ABEX/reports/resource-guardian-20261029/new-isolated-run
python scripts/resource_guardian.py --profile config/resource-guardian.abex.example.json observe
```

The benchmark's output directory contains disposable test databases and metadata.
It never points at production data. Use a fresh output directory to retain each run.
For persistent mode testing, pass an explicitly disposable `--db` and select
`status` or `mode Balanced`. Selecting a mode changes no Owner admission state.

## Preconditions for a future release

1. Review and release the correct parent source before this stacked candidate.
2. Match model digests, context, runtime revision and representative peak memory;
   resolve the separate failed deep-task correctness oracle. The example profile
   cannot qualify those by declaration. Choose reserves from the full live envelope.
3. Verify actual existing producer coverage, owner identity, cost/locality contracts,
   fairness, recovery and pressure deferral through isolated jobs. Keep ordinary
   background admissions paused. Do not manufacture 21 liveness generations.
4. Install the validated `Get-ResourceSensors.ps1` beside the protected existing
   `collect-host-metrics.ps1` only through its established administrator-owned
   deployment path. Back up both files and the collector integrity receipt first,
   preserve ACLs and the existing scheduled task, then update its integrity record
   with the actual deployed file hashes. No additional scheduled service is needed.
5. Build/version the correct backend source and stage it through existing procedures.
   A backend replacement affects the OTel network-namespace dependency; prepare
   their coordinated maintenance and all exact rollback inputs first. The latest
   Owner storage mission forbids stopping/recreating services without a new
   explicit maintenance authorization.
6. Opt in with the fixed operator-owned `ORQEVIA_RESOURCE_GUARDIAN_PROFILE` path
   only after the profile is qualified. Bind the existing protected host receipt
   read-only where needed. Do not change model/provider or private endpoint URLs
   merely to enable this feature.
7. Verify actual source/image identity, fresh telemetry, persistent selected mode,
   pause generation, no duplicate dispatch, new-work pressure deferral, safe task
   completion and responsiveness. Only observed behavior can become enforcement
   evidence. Production background resume is a separate Owner instruction.

## Rollback

Remove the optional profile opt-in and restore the prior backend image/config and
protected sampler/helper files through the established maintenance procedure.
Retain all additive resource observations, existing jobs, results, models and
databases. Never restore a stale database, drop the Owner pause trigger or restore
the old supervisor's automatic pause-clearing behavior as rollback.

An uncertain tool permit is evidence to reconcile against its owned process and
existing artifacts. Never clear a permit solely to increase concurrency or rerun
the same logical-work identity after an ambiguous external effect. No new queue,
deployment hold, cloud spending authority or blanket process-killing policy exists.
