# On-demand preventive monitoring

scripts/docker_storage_monitor.py uses standard-library Python, existing Docker
CLI, existing WSL and native Windows GetCompressedFileSizeW metadata. It adds no
service/container/scheduler, does not restart Docker, and does not call a model.
The prior October27 scan-storage.py is a broad one-shot host-tree inventory,
not a recurring Docker/VHDX allocation/log-growth monitor. Existing protected
host metrics/OTel infrastructure remains unchanged; these reports can be read
on demand by an authorized operator without installing another timer.

```powershell
python scripts/docker_storage_monitor.py --output <new-current.json> --logging-plan <new-plan.json>
python scripts/docker_storage_monitor.py --output <new-later.json> --previous <new-current.json>
```

Collects image/volume/cache accounting, all container health/IDs/start/restarts,
mount/Compose ownership, log policies/file metadata sizes, data+boot VHDX logical
and NTFS allocated bytes, ext4 usage and Windows available storage. Docker inspect
is filtered in process; environment, commands, token values and health output
are never exported. It only stats log files, never reads/truncates their contents.
WSL mapping is verified before fixed-path metadata access; malformed IDs/refused
access produce explicit errors/unknowns, not zeros. Source network transports
and active container settings are not altered.

Reports replace only the selected JSON output atomically. Select a new report
name to retain each receipt. First observation has INSUFFICIENT_HISTORY; intervals
under60s have INTERVAL_TOO_SHORT. Compare matching VHDX paths, volume names and
log container IDs; a recreated container never inherits the old ID's log-growth
rate. Negative deltas remain negative and cannot prove volume/data deletion or
host reclamation. Rates are short-window extrapolations, not forecasts.

Review warnings: missing baseline role, unhealthy configured check, unbounded
json-file policy, Windows free below provisional10%, missing historical canary rollback tags, or observed growth above
provisional5GiB/day. These thresholds are review aids, not automatic cleanup,
process termination, deployment locks or production admission controls. Long-term
trend and appropriate per-workload growth thresholds require retained history.
No recurring task was installed; future integration into an existing approved
observability schedule needs conflict review and the Owner's applicable approval.

Initial3actual collections took approximately1.49-1.57s. No data-file scan or model
load. Unknown recoverability stays null. tests/test_docker_storage.py validates
metadata privacy, growth edge cases, atomics, identity-bound logging plan, active
Docker refusal, copy readback/no-overwrite and corrupt/incomplete backup handling.
