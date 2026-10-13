# ABEX Windows host telemetry

The Interface keeps host values unavailable until an operator provides a fresh,
valid `orqevia.host-telemetry.v1` receipt. It never substitutes Linux container
resources, stored job counts or estimates for Windows host measurements.

`scripts/collect_abex_host_telemetry.ps1` samples Windows CPU load through
`Win32_Processor.LoadPercentage`, physical memory used through
`Win32_OperatingSystem`, and **C: volume capacity used** through
`Win32_LogicalDisk`. Disk capacity is not I/O utilization. `network_latency` is
stopwatch elapsed time for the fixed, proxy-free, redirect-free
`http://127.0.0.1:8000/health` GET, including its small response body. Its scope is
`LOCAL_LOOPBACK_HTTP_HEALTH`; it measures the ABEX local HTTP path, not Internet,
LAN-client or provider latency. An unavailable or unhealthy endpoint remains null.

Each sample includes actual collection timestamps, Windows host identity,
measurement producer/scope and explicit per-metric failures. The sampler writes
UTF-8 JSON with a same-directory atomic replace, without credentials, raw
exceptions, external network calls, inference, security changes or service changes.

```powershell
.\scripts\collect_abex_host_telemetry.ps1 -HostId ABEX `
  -OutputPath 'C:\Users\Admin\Documents\ABEX\operations\host-telemetry\host-telemetry.json'
```

The default is one bounded sample. `-Continuous -IntervalSeconds 30` explicitly
enables periodic collection in an owner-managed supervisor. No scheduled task is
registered by the script. Multiple samples can be requested with `-MaxSamples`.

For a reviewed Interface candidate, mount the **parent directory read-only** at
`/run/prime-host`; mounting the individual file would pin the pre-replacement inode.
Set `PRIME_INTERFACE_HOST_TELEMETRY_RECEIPT=/run/prime-host/host-telemetry.json` and
keep `PRIME_INTERFACE_HOST_ID=ABEX`. The reader rejects receipts over32KiB,
wrong schema/host/collector, ambiguous JSON keys, stale/future samples, invalid
numbers/units/scopes and missing metrics. Freshness is90seconds, with5seconds
clock tolerance; collection timestamps within each receipt must be within30seconds.
Failures retain null values and fixed categories, with no private error content.

This source change does not install a collector, restart a service, certify host
reliability or establish an authenticated physical-client journey. Deploy only a
reviewed candidate with an exact predecessor container/image retained. Rollback
restores that predecessor and stops the sampler; it never removes runtime data,
historical evidence or the existing TLS/enrollment configuration.
