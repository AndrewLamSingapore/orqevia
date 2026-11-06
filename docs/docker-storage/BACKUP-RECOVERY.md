# Cold backup and disaster recovery runbook

Prepared, not executed. No live VHDX copy is a consistent backup.
Docker's [official backup procedure](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)
requires Docker Desktop fully stopped before copying its VM disk. This plan
also captures the verified boot disk requested by the Owner.

Verified sources on ABEX:

- C:/Users/Admin/AppData/Local/Docker/wsl/disk/docker_data.vhdx
- C:/Users/Admin/AppData/Local/Docker/wsl/main/ext4.vhdx

Both exist. Their total logical length is41,188,065,280B; the current plan reserves
45,306,871,808B free (10% margin). Recompute immediately before maintenance.
An external/off-device destination is preferred. The dry-run C:destination in
evidence is capacity planning only, not an off-device disaster-recovery backup.
No destination folder/disk copy was created by the plan action.

## Preparation without downtime

1. Run scripts/docker_storage_monitor.py and inventory all9roles,4volumes,images,
   source/imageIDs, aliases, mounts, Compose/source files, jobs/model lists and
   current pause generation. Retain active independent agents' handovers/work.
2. Choose a NEW protected destination with sufficient free capacity and recovery
   permissions. Backup archives can contain credentials/private data. Preserve
   encryption/ACL and user/machine recovery material; DPAPI is context-bound.
   Record physical device/off-device location and media health. Do not upload
   source/credentials to unapproved storage or turn on billable backup services.
3. Plan additional protected backups for Windows bind-mounted data/repositories,
   certificates, Docker settings, authorized private configuration and Windows
   Ollama knowledge. Two VHDXs do not contain every Windows bind mount or secret.
4. Record all automatic Docker/WSL startup/supervisor tasks and original states.
   Existing Runtime Watchdog, Pathway Auto-Start and coaching tasks may revive
   services. Prepare restoration of their exact prior state after the window.
   No recurring task was changed by this mission.

Dry-run command (replace placeholders with a real selected destination):

```powershell
python scripts/docker_cold_backup.py plan --destination <new-protected-folder> --output <plan.json>
```

## Explicitly authorized maintenance window only

1. Obtain a specific quiet window covering active developers, agents and users.
   Confirm no builds, migrations or dependent work is using Docker/WSL. The
   durable Owner production background pause remains active; do not resume it.
2. Follow the existing operational stop procedure after authorization. Quiesce
   database writes/services and suppress only recorded automatic restart paths
   for the window; retain exact prior state. Quit Docker Desktop, stop Docker
   service if applicable, then ensure docker-desktop is stopped. WSL-wide shutdown
   affects other work and requires that same explicit authorization/coordination.
3. Recheck no Docker Desktop/backend process, responsive daemon or running
   docker-desktop distro. The helper refuses if active/uncertain. Hold exclusive
   share-none READ handles to BOTH disks before creating any disk output; those
   handles remain held across the entire copy and readback verification.
4. Only after the Owner has approved that window, run:

```powershell
python scripts/docker_cold_backup.py copy-offline --approved-maintenance-window --destination <new-protected-folder>
python scripts/docker_cold_backup.py verify --destination <same-folder>
```

The helper never performs shutdown/stop/compaction. It creates a new directory,
never overwrites a disk, streams SHA256 during copy, fsyncs each destination,
reads back both destination hashes and records file lengths/UTC/original paths.
Both data/boot records and completed status are required for later verification.
Failure preserves partial artifacts as IN_PROGRESS; never label those a backup.
Record source Docker/WSL versions and before/after inventory alongside manifest.
Cryptographic consistency does NOT establish application recovery qualification.

5. Restart via the existing documented startup route; restore recorded task
   states without clearing the Owner pause. Validate all9roles, database/volume
   mounts, model inventory, HTTPS certificate/authentication, retained job history,
   trusted session behavior and independent work. Stop/rollback if identities,
   data or security differ unexpectedly. Record elapsed recovery time and results.

## Restoration and rollback decision points

Restoration is manual maintenance only and has NOT been tested on live ABEX.
Never restore to active VHDX files. Verify manifest/size/SHA of both saved disks
first, select a compatible recorded Desktop/WSL environment, confirm source paths
and free capacity for saved disks PLUS retaining current two disks. Stop/reconcile
all dependent work with explicit authorization. Preserve BOTH current disks as a
new pre-restore rollback set with hashes; do not overwrite/delete that evidence.
Stage copies from the verified backup to new filenames, verify staged hashes,
and replace the matching original paths only while Docker/WSL remains offline.
Keep boot and data from the same backup; never mix generations or detach active
virtual disks. Preserve ACLs and original settings/path metadata.

If any preparation/hash/capacity check fails: stop before swapping. If restore
validation fails: stop Docker/WSL within the authorized window, retain failed
restore evidence, restore BOTH pre-restore disks, restart and repeat validation.
Reconcile model manifests, retained records, all9services, HTTPS/Access/session
controls and pause0 before returning to service. A controlled isolated recovery
test, with protected private-data handling and no collision with production, is
still required before marking RESTORE_QUALIFIED. No new container or duplicate
production service is installed for this future test without justification.
