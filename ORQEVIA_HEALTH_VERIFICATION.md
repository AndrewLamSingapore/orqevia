# ORQEVIA health verification - executed source checks, not live acceptance

Actual combined command from the candidate worktree:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_host_metrics.py tests/test_interface_telemetry.py tests/test_interface_telemetry_counts.py tests/test_observability_health.py --junitxml=C:/Users/Admin/Documents/ABEX/operations/observability-recovery-20261027/handover/integrated-tests.xml
```

**68 passed in8.87s**, one Starlette/AnyIO deprecation warning. Log and JUnit saved at that path. Agent component runs:24host,23telemetry,21operational-health tests. These are deterministic source/fixture tests; no model jobs or live service outages were induced.

`ruff check app/host_metrics.py app/interface_telemetry.py app/observability_health.py tests/test_host_metrics.py tests/test_interface_telemetry.py tests/test_interface_telemetry_counts.py tests/test_observability_health.py --output-format concise`: All checks passed. `python -m ruff` was unavailable; it was not a successful check.

PowerShell AST ParseFile of scripts/collect-host-metrics.ps1: PASS. This validates syntax only. `git diff --check`: PASS at source handoff. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_portfolio_reconciliation.py` passed53 tests in4.31s after the dated checkpoint insertion; original historical and Owner-only sections remain pinned. JUnit/log are saved as status-preservation.xml/log in the handover.

Covered fixture behavior includes missing/malformed/oversized/stale/identity-mismatched receipts, independent field dates, invalid numerics/byte totals, first/reset rate baselines, failed/cancelled/running activity, model/config unavailability, functional/process distinction, TLS validation rules, incomplete inventory, store failure, dedup/open/recovery and stale observations that cannot resolve incidents.

ABEX handover runtime evidence: operations/observability-recovery-20261027/handover/runtime-at-handover.json; strict-https-at-handover.json; persisted-work-at-handover.json; database-checkpoint-summary.json. The first handover harness attempt had two local defects: metrics list treated as dict and prepending code before a future import in the existing backup helper. The corrected harness preserves its original log/HTTPS observation as before-harness-fix/first-attempt history; those harness errors are not service outages. Backup success is only claimed by the final verified summary.

The deployed runtime remains b360da9. New producer/installation/mount/PWA/source-bound CI-build-deployment acceptance, actual collector/service/API/network/heartbeat/database failure and recovery, new dashboard mobile/desktop checks, least-privilege changes and post-shutdown recovery remain UNVERIFIED. Do not report source fixture success as production readiness.
