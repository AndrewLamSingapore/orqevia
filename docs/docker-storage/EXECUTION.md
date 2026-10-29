# ABEX safe execution and handover

Branch codex/docker-storage-resilience-20261029, based fetched mainf37673b4.
No production deployment, Docker resource deletion, service interruption, new
scheduler, billable service, virtual-disk live copy/compaction or model mutation.
No background Owner pause release. Preserve all other working branches.

Implemented: on-demand monitor, identity-bound logging plan, source-only10m/3
Compose/API policy, cold-backup plan/offline-copy/verification helper, fixture
tests and these6reports/runbooks. Cold backup is NOT executed. Running Intelligence
still has its original unlimited LogConfig; the prepared change needs explicit
maintenance authorization before scoped recreation.

Changed repository files:

- deploy/intelligence-abex.compose.yml
- config/docker-intelligence-logging.json
- scripts/docker_storage_monitor.py
- scripts/docker_cold_backup.py
- tests/test_docker_storage.py and scripts/run_canonical_ci.py
- docs/docker-storage/{HEALTH,LOGGING,BACKUP-RECOVERY,RECLAMATION,MONITORING,EXECUTION}.md
- docs/docker-storage/evidence/*.json and STATUS.md checkpoint

Local additional source-only file: operations/release-qualification-20261023/
promote_intelligence_capacity.py. A single LogConfig assignment/comment was
added after HostConfig copying. Exact prior bytes remain in operations/
docker-storage-20261029/before/. Before/after SHA receipt is included. No other
creator logic, private environment or running container was changed. Old source
asserts an obsolete image and is NOT a safe command to replay.

Commands actually executed, scoped read-only/source/fixtures:

```powershell
docker ps --format '{{.Names}} {{.Status}}'
docker info --format '{{json .}}'
docker inspect <existing-container-ids>  # captured privately, projected metadata only
docker image ls --no-trunc --format '{{json .}}'
docker volume ls -q
docker volume inspect <existing-volume-names>
docker system df --format '{{json .}}'
wsl --version
# monitor invokes existing docker-desktop: df, du -sk, find/stat metadata only
python scripts/docker_storage_monitor.py --output <receipt.json> --previous <prior.json>
python scripts/docker_cold_backup.py plan --destination <UNEXECUTED-new-folder> --output <plan.json>
python -m pytest -q tests/test_docker_storage.py
ruff check --select E9,F scripts/docker_storage_monitor.py scripts/docker_cold_backup.py tests/test_docker_storage.py
# Source-only Compose config parse used empty temporary env fixture; PASS.
```

12fixture tests passed. Strict lint passed. Live monitor reports9running,
9images,4volumes,cache0, no metadata collection errors. Before/after health,
identity/start/restart/model/pause comparisons are in final acceptance evidence.
The existing scheduled tasks/independent agents were inspected, not modified by
this storage workstream. Earlier Codex/producer repairs are separately documented;
this report does not erase those actions or historical failures.

Rollback source files with Git or exact preserved creator bytes after checking
for concurrent edits. No live infrastructure rollback is needed because it was
not changed. Remove no evidence/volume/model as part of source rollback.

Deferred: restore missing historical rollback image custody, select protected
off-device destination, explicitly approve a quiet maintenance window, create and
hash-verify both offline disks, qualify restoration, apply live log rotation, and
only then consider justified compaction. No immediate disk-space emergency was
measured. Exact branch head/PR, changed-file list, executed validation and artifact
hashes are retained in ABEX operations/docker-storage-20261029/CUSTODY.json.
