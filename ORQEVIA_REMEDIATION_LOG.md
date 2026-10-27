# ORQEVIA remediation log - SOURCE CHECKPOINT ONLY

Baseline b360da98641a1332856c8fdeb2063d36312b7669; branch codex/observability-recovery-20261027. Saved candidate commit is recorded in ABEX operations/observability-recovery-20261027/handover/CUSTODY.json.

| File | Actual change | Validation / deployment |
| --- | --- | --- |
| scripts/collect-host-metrics.ps1 | Native capacities/interfaces/counters/errors/rates and original per-field source/times; optional fixed operational sibling hook |24 host tests, AST parse; not installed |
| app/host_metrics.py | Bounded compatible v1 reader, detailed values, explicit failures/identity/freshness |24 host tests; not deployed |
| app/interface_telemetry.py | Genuine recent-success readiness; explicit on-demand/heartbeat limitation; original task/job/model/host metadata; helper aggregation |23 telemetry tests; not deployed |
| app/observability_health.py | Nine-service validation, separate process/function states, coverage, persistent dedup incident/recovery/retention |21 health tests; not deployed |
| tests/test_host_metrics.py | Realistic fixture failures, stale/partial/malformed/identity/counter-baseline coverage |Included in68-pass combined run |
| tests/test_interface_telemetry.py; tests/test_interface_telemetry_counts.py | Failed/running activity cannot count ready; real state ordering/IDs/dependencies |Included in68-pass combined run |
| tests/test_observability_health.py | Healthy/failure/recovery/dedup/stale/invalid/TLS/inventory/journal tests |Included in68-pass combined run |
| STATUS.md; tests/test_portfolio_reconciliation.py | Exact dated candidate-only checkpoint, older historical/Owner Verified sections preserved |53 preservation tests passed in4.31s |
| ORQEVIA_*.md; operations/observability-recovery-20261027/agents/ | Evidence and explicit DeepSeek handover |Documentation, not a substitute for implementation |

No PWA code, runtime Compose/env/mount, installed collector, scheduler, service configuration, runtime ACL or production alert state was changed for this checkpoint. Readonly HTTPS/runtime observations and online SQLite backups were saved separately. No new model jobs or paid calls were submitted for handover. Private DB contents never enter Git or the public packet.

Three parallel agents have finished; root owns the next implementation. No operational producer hook implementation exists yet. No new mission build/merge/deployment/acceptance has occurred. See ORQEVIA_REMAINING_BLOCKERS.md.


## Resumed implementation checkpoint

Owner resumed with full approval and clarified full access for configured ORQEVIA agents/services. Nightly shutdown/extended offline recovery is required. The handover above remains the dated initial checkpoint, not a current claim that no frontend or native changes exist.

- Implemented scripts/collect_operational_health.py, scripts/collect-operational-health.ps1, scripts/install-host-observability.ps1 and focused producer tests. Existing native scheduled sampler has run the new source automatically. Original source/ACLs preserved privately; configured writers retain access.
- Native receipt now carries actual capacities/interfaces/rates/error counters. Operational source/host/boot checks PASS. Fixed Docker inspect template nil-health handling; absence of a Docker healthcheck no longer discards four service observations. Corrected producer suite15PASS; existing68 host/API/helper tests passed in the executed81-test combined run before the two added regression cases. No model calls submitted.
- PWA consumes original child timestamps and shows source/reason/capacity/network/service/incident/readiness data. No zero critical total without full fresh coverage and working store.46 frontend tests PASS; shell coherentlyv43. Source helper/new tests formatted for CI; previous b22quality/status/browser CI passed, its new-file format failure was corrected.
- Live new-image deployment/bind/API/browser acceptance and actual prolonged offline/restart qualification are still PENDING. Public functional HTTPS request returned403 with certificate verification, so no authenticated public functional proof is claimed. Idle backend worker heartbeat and private gateway/current tunnel connection evidence remain limitations. Do not classify those as healthy from process presence.
- Evidence: ABEX operations/observability-recovery-20261027/collector-install.json, collector-install-fixed.json, integration-tests.xml. Read exact timestamps; no physical PC shutdown performed for testing yet. The existing source host task remains protected/invisible to ordinary enumeration; actual live samples prove current execution.
