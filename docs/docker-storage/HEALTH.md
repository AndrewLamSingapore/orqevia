# ABEX Docker Storage Health Report - 29 October 2026

Safe implementation complete; disruptive maintenance deferred. Evidence time
2026-10-29T02:23:01.815383+00:00. No production deployment or cleanup is part of this branch.

## Current verified state

Docker Desktop file version4.96.3.244472; Engine29.9.2; WSL2.7.14.0,
kernel6.18.33.2. Only docker-desktop WSL distro is registered. API/WSL metadata
collection took 1.505s, without reading log/model/database
contents. All9baseline roles are accounted for:9running,5configured health checks
healthy,4without configured health checks (running is not full service acceptance).

| Measurement | Historical user baseline | Current |
|---|---|---|
| Running containers | 9 | 9 |
| Images | 16 | 9;8active,12.18MB reported reclaimable |
| Volumes | 4 | 4,all active; no volume reclaimable |
| Docker data VHDX logical length | 38.27 (unit ambiguous) | 41,087,401,984B / 38.266GiB |
| Docker data VHDX allocated length | not supplied | 41,087,401,984B / 38.266GiB |
| Boot ext4.vhdx logical / allocated | not supplied | 100,663,296B / 100,663,296B |
| Internal ext4 used | 21.5 (unit ambiguous) | 23,085,314,048B / 21.500GiB |
| Docker volume accounting | about10.57GB | 10.59GB (Docker display units) |
| Ollama volume allocated file metadata | about9.21GB | 9,208,782,848B (du -sk x1024) |
| Windows free | about652 (unit ambiguous) | 706,692,169,728B / 658.16GiB |
| Build cache | 0B | 0B |

GiB=2^30B. Docker's displayed GB/MB units are retained as reported; do not compare
ambiguous historical units as exact changes. VHDX length minus ext4 used is
16.77GiB, an accounting difference,
NOT verified host storage reclaimable. Recoverable_host_bytes remains null.
VM filesystem logical capacity is about1TiB and is not host reserved capacity.
Windows allocation is read with GetCompressedFileSizeW; no disk attach/compaction.

| Container | State / configured health | Log file metadata bytes | Live log policy |
|---|---|---:|---|
| orqevia-epoch-20261016-otel-collector-1 | running / NOT_CONFIGURED | 1723916 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-epoch-20261016-backend-1 | running / healthy | 1734930 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-epoch-20261016-interface-1 | running / healthy | 473888 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-coaching-coaching-1 | running / healthy | 3960005 | json-file / {"max-file": "2", "max-size": "2m"} |
| orqevia-epoch-20261016-ollama-1 | running / healthy | 26854045 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-intelligence-1 | running / healthy | 2181116 | json-file / {} |
| orqevia-epoch-20261016-cloudflared-dual-1 | running / NOT_CONFIGURED | 454614 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-epoch-20261016-integration-gateway-1 | running / NOT_CONFIGURED | 80586 | json-file / {"max-file": "3", "max-size": "10m"} |
| orqevia-epoch-20261016-cloudflared-1 | running / NOT_CONFIGURED | 430485 | json-file / {"max-file": "3", "max-size": "10m"} |

## Ownership, growth and active work

The metadata receipt includes image IDs, start times, restart counts, Compose
ownership/files, mount ownership and networks. Backend/interface/Ollama share the
existing epoch data/HTTPS deployment; coaching remains its own service; OTel has
its own volume. Intelligence is API-managed, with no Compose project label;
its /data volume is orqevia-intelligence-data. Editing the example Compose file
alone does not change its running log limits. No new container/service/scheduler.

Three on-demand observations provide short-window deltas, not a storage trend
forecast. See growth intervals/rates in evidence. VHDX allocation remains unchanged
through those observations. Existing producer tasks and another Codex session are
preserved. No local build/redeploy/migration was initiated by this workstream.
Docker daemon events retained no explanatory deletion history; this is not proof
that no other actor changed Docker resources. Historical image count16 is now9;
earlier October28 inventory and old stopped-stage containers are not current.

Two earlier canary rollback tags are absent:
orqevia:open-access-7275620-20261021 and orqevia:orq002-workflow-20261020.
This run did not delete/prune any image, container, volume, network or model.
The cause/time of that difference is unverified. Keep rollback readiness FAIL
until exact preserved artifacts are located/verified or an authorized replacement
rollback package is qualified. Never replace the canary's expected image IDs
with whichever image happens to exist.

## Remaining operational risks

Intelligence's json-file log is unbounded today. Its log is currently small;
10m/3 source policy is prepared, not live. No immediate destructive cleanup is
justified: all volumes are active, build cache is empty, host free space is ample.
Cold two-VHDX backup, restoration qualification and offline compaction have NOT
run. No backup is claimed consistent or restore-tested. Active volume IDs/mounts
and all9container identities/start times are compared in final acceptance;
those checks cannot prove absence of all historical/application-level data loss.
No application-data deletion or downtime command was executed by this run.

See LOGGING.md, BACKUP-RECOVERY.md, RECLAMATION.md, MONITORING.md and EXECUTION.md.
