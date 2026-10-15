# ABEX runtime forensic baseline

Observed 15 October 2026 UTC. Source review pinned to ORQEVIA main `25675aa35baf6e6b49a4682bd6e7666c796dc4de`. This report is an evidence inventory, not a replacement status authority. Latest owner recovery directive supersedes historical Dell implementation and parked architecture instructions.

## Actual running system

Host `DESKTOP-27LKJ2V` identifies this environment as ABEX. Four containers were running, all Docker-healthy: backend, TLS Interface, paused coaching controller, and Ollama. The complete selected inventory contains 93 running/stopped containers; retained rollback and qualification containers were preserved.

Backend and Interface report revision `891e3adfdd6defac00d7faef34bec06a10de4a4e` in OCI labels and selected environment metadata. Actual image ID is `sha256:36c11eebd2e4f2f5806088e976c22fb9393805f5338881f1004d82a373fad419`, reference `orqevia:official-logo-891e3adf`. Both started `2026-10-15T04:38:39Z`, restart count zero at capture. Coaching image label is `b8db7febd7eae9299b2a687a84e344e7e8a26eab`; its inherited runtime revision environment says `81f2d1dcb238f39c26af153d2e870cc16674993f`. Those are separate observed identities, not interchangeable provenance.

Backend binds `127.0.0.1:8000`; Interface binds `192.168.1.23:8443`. Actual user entry is `https://192.168.1.23:8443/pwa/`. Backend `/health` returned 200 `{"ok":true}`. TLS chain and hostname were verified against the existing private CA for read-only Interface probes. `/pwa/` returned 200 with SHA-256 `cb0af5f66f9a5021bded7a33a088a30030f1ad0b366c82d220d7deb2c1865b35`, matching the retained 13 October receipt. Interface `/health` is an unmounted path returning 404; Docker health and the backend health pass must not be confused with that path.

All four requested `/api/orqevia/intelligence/...` paths returned 404 on anonymous GET to the backend. Sources and God's Eye also returned 404 through TLS Interface. GET on POST-only retrieval/ingestion is not a functional POST test; installed-file and mount evidence independently proves these modules absent from the image. The current PWA dashboard JavaScript contains no God's Eye path literal. This is NOT a deployed God's Eye release.

## Storage and preservation

`prime-epoch-20260919-data` is an external Docker named volume, mounted writable at `/data` in backend, Interface and coaching. `PRIME_DATA_DIR=/data`; `ORQEVIA_DATA_DIR` is absent. Current intelligence API fallback in source would use `/work/orqevia-intelligence-data` in this image layout, outside the persistent mount. Setting the requested variable to a bounded `/data/...` target is necessary before a qualified deployment, not performed here.

Thirteen root SQLite files were discovered, including two empty historical files. The artifact store contains 686 files totaling 1,141,195 bytes. `/data/coaching.pause` exists and exactly matches the owner pause marker SHA-256 `b370d8d87784e3c5a5070b47bedf252be903abe3729a85379b5470ff0e2b1934`. Controller readback is PAUSED; all 302 compute jobs are terminal (286 completed, 16 failed). No queue was resumed.

New preservation `/data/forensic-recovery-backups/20261015T062946Z` contains individual online SQLite backups, all integrity `ok`, 686 source-stable hash-checked artifact copies, pause marker and additive root file copies. It was copied to private host storage at `private/forensic-recovery-20261015/runtime-backup-20261015T062946Z`; every database hash/integrity and artifact hash was rechecked. Eight selected compose/overlay/environment configuration files were copied privately and hashed. No configuration values or credentials are included in reports.

This is individual database consistency and same-host off-volume preservation. It does not establish cross-database transactional coherence, encrypted off-device recovery, host-loss recovery, or complete TLS/credential backup qualification. Root-file stability flags are in the receipt. Source files were never deleted or overwritten.

## Deployment mechanism and exact localized blockers

The existing runtime uses the retained compose project `runtime/prime-epoch-20260919` with seven layered compose/activation files. Historical names remain infrastructure identifiers, not a revival of PRIME governance. `operations/coaching-priority-20261013/install-runtime.py` is an existing reversible manual Docker replacement script. It checks image revision, active jobs, snapshots databases, stores original configurations privately, stops/renames old containers, recreates retained mounts/ports, waits for health and attempts rollback on failure. `RUNTIME-INSTALL-20261013T130852Z.json` and stopped rollback containers establish historical execution, not a new deployment.

The script is purpose-built for a prior queue/interface rollout: it changes cloud concurrency/cost policy, inherits labels that still name older compose overlays, and asserts a specific queue policy after rollout. It does not configure ORQEVIA intelligence, new authentication, a safe standalone UI listener, or intelligence data paths. It must not be replayed broadly to deploy this release.

Three concrete blockers affect production promotion only:

1. **Unreconciled source/runtime divergence.** Live installed files include capability broker, collective workspace and agent tool bridge APIs and direct-entry mounts absent from canonical main. Main includes the new ORQEVIA UI, Academy, UIEF, scaffolding and Hyper-Inference modules absent live. Replacing the image with main without reconciliation could remove existing legitimate functionality.
2. **No qualified production integration contract.** Source `app/orqevia/ui.py:60` mounts the intelligence API only in a standalone application, deliberately absent from production/interface entrypoints. Default Dockerfile starts `app.production_entry`. Existing rollout therefore cannot expose these routes just by rebuilding the merged commit.
3. **Security/storage/interface claim mismatches.** Intelligence router has no authentication dependency; POST ingestion calls external USGS and writes local state, contrary to the standalone UI's read-only docstring and manifest. Its default state path is not the live `/data` mount. A narrowly designed authenticated integration and persistent path must be verified before production exposure. Do not disable the existing transport/session/sink controls to make endpoints appear.

Production deployment, service restart and emergency suspension were withheld during the latest recovery operation. This avoids disrupting preserved runtime before source integration and acceptance gates. Existing retained rollback containers/images and fresh data/configuration backups improve rollback readiness; no current rollback drill or service restart was performed, and full rollback acceptance remains NOT TESTED.

## Real isolated source execution

`ISOLATED-USGS-QUALIFICATION.json` records a real USGS HTTP 200 at `2026-10-15T06:33:00.936470Z`: 9,802 bytes, SHA-256 `c4e97303321b0d2a6ad396225ae70af3e31d9260fc6a9af7f0b45364f9dcbfc7`, 13 normalized observations persisted in a new evidence directory. Retrieval returned GROUNDED passages with provider-backed event citations and non-authority/non-executable flags. Historical replay preserved source/time provenance. Geospatial distance executed. One deliberately labeled demonstration alert was manually evaluated and duplicate suppression passed. A fresh Python process reopened 13 observations, GROUNDED retrieval and one alert. A controlled source outage returned failure while retaining observation count.

This demonstrates isolated library execution and process persistence, not deployment, an integrated live alert pipeline, full service recovery, external alert delivery, or scientifically validated earthquake prediction. The baseline forecasting function measures last-value sequence error only. No aviation, AIS or geopolitical feed was claimed or called.

## Evidence

- `docker-selected.json`: selected live/stopped container metadata, identity, mounts and controls; no full Env or command lines.
- `installed-source-metadata.json`: installed file presence/hash/import/route AST; no application imports.
- `http-readonly.json`: anonymous GET status/hash receipts with verified TLS.
- `data-selected.json`, `agents-selected.json`, `golden-path-metadata.json`: bounded read-only metadata.
- `DATA-PRESERVATION-20261015T062946Z.json`, `config-preservation.json`: preservation receipts.
- `ISOLATED-USGS-QUALIFICATION.json`, `isolated-usgs-20261015T063259Z/`: real public-data source qualification.

Limits: no physical iPhone journey; no authenticated live dispatch; no remote Dell host or cloud infrastructure inspection; no production restart or new deployment; complete test execution belongs to the root recovery verification receipt.
