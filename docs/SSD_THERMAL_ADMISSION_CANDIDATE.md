# SSD thermal-admission candidate (not deployed)

This branch adds a projection around the already-proven read-only Windows NVMe
SMART Health log 0x02 reader **source** and an
opt-in thermal gate at the existing local backend lease. It makes no live sensor
or persistent collector claim. Golden production remains unchanged.

The exact disk DeviceId, serial and friendly name must be pinned in a policy
file with a model-specific manufacturer limit and its source. Hash-pin the
policy through `PRIME_SSD_THERMAL_POLICY_SHA256`. The policy also binds the
read-only SMART reader's exact SHA-256. The proven reader uses
`StorageDeviceProtocolSpecificProperty=50` (not 24), `GENERIC_READ`, and
`IOCTL_STORAGE_QUERY_PROPERTY`; it has produced composite, sensor 1 and sensor
2 readings on this Lexar SSD. A separate Windows StorageReliabilityCounter
reading was close to composite temperature, but its `TemperatureMax` field is
a capability/threshold value, **not** a measured historical peak. Thermal
admission uses the hottest fresh SMART reading of composite, sensor 1 and
sensor 2, not just composite.

The existing reader failed `CreateFile` under the ordinary Admin user token
and succeeded elevated. This establishes a real Windows privilege boundary,
not proof that `SYSTEM` is the least-privilege answer. Provision a dedicated,
one-purpose local broker only after testing whether LocalService can perform
the read; if it cannot, review the narrowest viable service/task identity.
Do not grant PRIME elevated privileges, broaden the physical-drive ACL, or
give it a Docker socket. Store the hash-pinned reader and wrapper under a
protected ProgramData directory not writable by PRIME. Run the broker on a
short bounded cadence and at startup. Keep raw SMART receipts in a protected
evidence directory; atomically project only the allowlisted temperature,
identity, warning and provenance fields to a separate path with a broker-write
and PRIME-read-only ACL/mount. No secret is needed. A missed broker restart
expires the receipt and holds heavy local work. Test that startup, PRIME
restart and a controlled Windows reboot actually restore fresh receipts.

Set `PRIME_SSD_THERMAL_ENFORCE=1` only after those ACL, sensor, model limit,
restart persistence and receipt freshness checks are verified.
With enforcement enabled, demand at or below 1024 MiB remains light; larger
work uses the pinned policy threshold. Heavy local demand fails closed if the
policy/receipt is missing, stale, mismatched, malformed or within 5 C of the
pinned limit. The caller may route permitted work to governed cloud capacity;
this module does not force cloud offload or broaden data authority.

The wrapper script is not an installer and must not be scheduled or run
against production without separate review. It accepts the exact hash-pinned
proven reader as a dependency, preserves its raw receipt, and emits only the
allowlisted projection. No current sensor reading or manufacturer limit is
encoded in source. Controlled service restart and reboot verification remain
outstanding.
