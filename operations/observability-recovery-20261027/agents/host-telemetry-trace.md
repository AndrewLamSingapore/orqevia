# ABEX Windows host telemetry trace and source patch

Source baseline: `b360da98641a1332856c8fdeb2063d36312b7669`.
Worktree: `C:/Users/Admin/Documents/ABEX/work/orqevia-observability-20261027`.
Observation window: 2026-10-27 03:50-03:55 UTC. Source-only implementation followed under root authorization.

## Observed path and exact fault

1. Native Windows source works. `Win32_Processor`, `Win32_OperatingSystem`, `Win32_LogicalDisk`, `Get-NetAdapter`, `Get-NetAdapterStatistics`, and `Win32_PerfFormattedData_Tcpip_NetworkInterface` returned actual host measurements without model calls.
2. Installed sampler: `C:/ProgramData/ABEX/PrimeHostMetrics/collect-host-metrics.ps1`. Its initial SHA256 matched the baseline source: `3C5DCFF82C02474BC708C85E9F609D22F4CC3596272CC1663DD63D3AB598103A`.
3. Its receipt `C:/ProgramData/ABEX/PrimeHostMetrics/receipt/host-metrics.json` was actively refreshed. Writes observed at 03:50:05, 03:52:05 and 03:55:09 UTC. At 03:55:48 UTC its age was 39 seconds. It identified `DESKTOP-27LKJ2V`, boot `2026-10-27T00:15:26.5000000Z`, collector `abex-host-metrics-v1`, schema `orqevia.host-metrics.v1`.
4. Docker inspect of `orqevia-epoch-20261016-interface-1` showed its read-only `/run/orqevia-host-metrics` bind source was `C:/Users/Admin/Documents/ABEX/runtime/orqevia-epoch-20261016/deploy/unconfigured-host-metrics`, rather than the active receipt directory. Container `ls -la /run/orqevia-host-metrics` returned only `.` and `..`.
5. Its environment contained `ORQEVIA_HOST_METRICS_RECEIPT=/run/orqevia-host-metrics/host-metrics.json`. The deployed `.env` inspection returned no `ORQEVIA_HOST_METRICS_DIR` assignment. The Compose fallback selects the placeholder.
6. A read-only execution of the live reader returned `configured=True` and all four scalar values `None`. The old reader conflated absent, unreadable, stale and malformed receipts and removed the original identity, sample times and reasons.
7. Source tracing of `/interface/v1/telemetry` found the old projection labeled these rows `host-collector` whenever the path was absolute, used the Interface instance as source instance, left `event_timestamp=None`, and dated every row with API snapshot time. Source tracing of `clients/pwa/dashboard.mjs` found only four scalar gauges and a generic "host gauges unavailable" label. No authenticated API/browser acceptance was performed by this agent.

## Actual Windows measurements

These are separate observations, not a synchronized benchmark or deployment acceptance.

- At 03:54:05 UTC: memory total `33,644,036,096` bytes, used `28,423,585,792`, available `5,220,450,304`.
- At 03:54:05 UTC: C: NTFS total `999,012,954,112` bytes, used `290,401,996,800`, available `708,610,957,312`.
- At 03:54:52 UTC: AMD Ryzen 7 PRO 8840HS CPU load `27%`, 8 cores and 16 logical processors.
- At 03:54:24 UTC: Wi-Fi interface index 3, Intel Wi-Fi 6E AX210, Up at 287 Mbps; Ethernet index 6 disconnected. Adapter counters showed Wi-Fi received `603,582,981` bytes and sent `105,634,711`; receive/transmit packet errors and discards were zero. The WSL virtual adapter was also observable.
- At 03:54:57 UTC: Windows formatted network counters reported Wi-Fi receive `5,476` bytes/s and send `2,212` bytes/s, with zero packet errors/discards. This established source availability; the patch derives rates from same-boot receipt counter deltas instead.

## Scheduler and permission limits

- No dedicated Prime/HostMetrics task or service was visible by name; no task action directly containing `collect-host-metrics.ps1` was visible in the ordinary task context.
- `C:/Windows/System32/Tasks` directory enumeration returned AccessDenied. Exact current metrics task name, command line, trigger and SDDL therefore remain UNVERIFIED. Do not interpret this as collector downtime: the receipt was actively updating.
- Existing `operations/permanent-readiness-20261017/Invoke-FullStackCanary.ps1` explicitly records that the protected SYSTEM metrics registration can be invisible to the ordinary task context. Its freshness check accepts v1 schema/collector and verifies the current boot. Source evidence does not establish the live registration's exact identity.
- The receipt owner was SYSTEM; script/root owner was Administrators. Actual root/script/receipt ACLs inherited or explicitly granted `BUILTIN\\Users` FullControl. Read permission did not cause the empty mount. Protected-writer provenance is not established by these ACLs.
- Recommended follow-up for root: verify actual SYSTEM/Owner execution paths and preserve original SDDL before separately applying least privilege to this collector's own script/receipt paths. No host ACL, service, scheduler, network endpoint, certificate, session or runtime file was changed by this agent.

## Authorized source patch

Only these three source files were changed by this agent:

- `scripts/collect-host-metrics.ps1`: preserve v1 scalar fields/schema/collector identity and atomic NTFS replacement; collect byte totals, system-drive identity, CPU detail, visible interface counters/errors/discards and rate intervals; retain per-field native source and original capture time; expose collection failures; derive rates only with a usable same-host/same-boot previous counter sample. First sample, reboot, reset or missing baseline leaves rates unavailable with an explicit reason. Receipt size is bounded at 128 KiB.
- `app/host_metrics.py`: bounded read with separate missing, permission, malformed, oversized, schema, identity, future and stale reasons; reject booleans/non-finite values as measurements; retain original identity, timestamps and ages; verify optional `ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID`; preserve legacy `configured`/`values` and add field/group provenance and details. The 150-second maximum sample age allows measured one-minute cadence plus jitter. Original times are never replaced with API time. Writer trust is `NOT_ATTESTED`.
- `tests/test_host_metrics.py`: focused coverage of native detail, exact timestamps, cadence jitter, stale/missing/malformed/permission failures, duplicate JSON, oversized receipts, identity mismatch, legacy compatibility, invalid numerics, independent field staleness, inconsistent totals and first network baseline.

The API agent owns `app/interface_telemetry.py` and its tests. Root owns PWA rendering, installation of the source sampler, deployed mount configuration and actual HTTPS acceptance. Runtime host identity checking should use `ORQEVIA_HOST_METRICS_EXPECTED_HOST_ID=DESKTOP-27LKJ2V`; the Interface alias `ABEX` is not the native Windows computer name.

## Fixed operational-health producer hook

After successful host receipt replacement, the existing sampler optionally invokes the normal non-reparse sibling file `C:/ProgramData/ABEX/PrimeHostMetrics/collect-operational-health.ps1` with no arguments. The hook path is fixed, not caller supplied. Existing root-directory reparse checks remain. A hook failure emits a sanitized exception-type warning and preserves the host receipt. Root owns this hook's implementation and deployment. No duplicate collector or scheduler was introduced.

## Validation

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_host_metrics.py`: **24 passed in 1.32s**.
- Windows PowerShell AST parse of `scripts/collect-host-metrics.ps1`: **PASS**. This is syntax validation, not a collector runtime acceptance.
- No model calls, heavy regressions, restarts, deployment, authenticated acceptance requests or secret/header inspection occurred in this lane.
