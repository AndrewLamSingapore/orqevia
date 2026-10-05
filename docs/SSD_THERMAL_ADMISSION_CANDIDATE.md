# SSD thermal-admission candidate (not deployed)

This branch adds a Windows StorageReliabilityCounter collector **source** and an
opt-in thermal gate at the existing local backend lease. It makes no live sensor
or persistent collector claim. Golden production remains unchanged.

The exact disk DeviceId, serial and friendly name must be pinned in a policy
file with a model-specific manufacturer limit and its source. Hash-pin the
policy through `PRIME_SSD_THERMAL_POLICY_SHA256`. Do not import the Windows
`TemperatureMax` field as a measured historical peak or assume that a single
`Temperature` field measures the SSD hotspot. The sensor scope is explicitly
`MSFT_StorageReliabilityCounter.Temperature` in degrees Celsius.

An independently provisioned Windows collector must run with only the rights
needed to read this counter, atomically replace the receipt in a pre-created
directory, and grant PRIME **read-only** access. PRIME must not be elevated or
gain a Docker socket. Set `PRIME_SSD_THERMAL_ENFORCE=1` only after that ACL,
sensor, model limit, restart persistence and receipt freshness are verified.
With enforcement enabled, demand at or below 1024 MiB remains light; larger
work uses the pinned policy threshold. Heavy local demand fails closed if the
policy/receipt is missing, stale, mismatched, malformed or within 5 C of the
pinned limit. The caller may route permitted work to governed cloud capacity;
this module does not force cloud offload or broaden data authority.

The sample collector script is not an installer and must not be scheduled or
run against production without separate review. No current sensor reading or
manufacturer limit is encoded in source. Controlled service restart and reboot
verification remain outstanding.
