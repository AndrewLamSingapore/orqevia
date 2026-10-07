# Source-only projection around the proven read-only NVMe SMART reader.
# No caller-controlled command, path, disk identity or output filename is
# accepted. All directories and this script require a protected broker-write
# ACL; PRIME must have read-only access only to the projected receipt.
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'Collector accepts no caller arguments' }
$Root = 'C:\ProgramData\ABEX\PrimeThermal'
$ReaderScript = Join-Path $Root 'reader\Read-NvmeHealth-ReadOnly.ps1'
$ReaderSha256 = 'E72418020F5B9E900B165B350E8E45A7561D75288F7A11A63B6F792B222826D2'
$ExpectedSerial = '0000_0006_2506_1915_CAF2_5B02_3703_0900.'
$RawDirectory = Join-Path $Root 'raw'
$OutputDirectory = Join-Path $Root 'receipt'
$OutputPath = Join-Path $OutputDirectory 'temperature.json'
$RawEvidencePath = Join-Path $RawDirectory (([DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmss')) + '-' + [Guid]::NewGuid().ToString('N') + '.json')
foreach ($path in @($Root, (Join-Path $Root 'reader'), $RawDirectory, $OutputDirectory)) {
    $item = Get-Item -LiteralPath $path -ErrorAction Stop
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Protected broker directory invalid'
    }
}
if ((Get-Item -LiteralPath $ReaderScript).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Reader reparse point forbidden'
}
if (Test-Path -LiteralPath $OutputPath) {
    if ((Get-Item -LiteralPath $OutputPath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Receipt reparse point forbidden'
    }
}
if ($ReaderSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $ReaderScript).Hash -ne $ReaderSha256) {
    throw 'Proven NVMe reader identity mismatch'
}
$disk = Get-Disk -Number 0
$physical = @(Get-PhysicalDisk | Where-Object { [string]$_.DeviceId -eq '0' })
if ($physical.Count -ne 1 -or $disk.FriendlyName -ne 'Lexar SSD NM610 PRO 1TB' -or
    $disk.BusType.ToString() -ne 'NVMe' -or
    ([string]$physical[0].SerialNumber).Trim() -ne $ExpectedSerial) {
    throw 'PhysicalDrive0 identity gate failed'
}

# The hash-pinned reader uses GENERIC_READ and IOCTL_STORAGE_QUERY_PROPERTY
# StorageDeviceProtocolSpecificProperty=50, NVMe SMART log 0x02. It does not
# send SET, firmware, raw-sector or write requests. Preserve its raw JSON.
& $ReaderScript -OutputPath $RawEvidencePath | Out-Null
$raw = Get-Content -LiteralPath $RawEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($raw.device -ne 'Lexar SSD NM610 PRO 1TB / PhysicalDrive0' -or
    $raw.query -ne 'Read-only IOCTL_STORAGE_QUERY_PROPERTY, NVMe SMART Health log 0x02' -or
    $raw.temperature_sensors.Count -ne 2 -or
    [int]$raw.temperature_sensors[0].number -ne 1 -or
    [int]$raw.temperature_sensors[1].number -ne 2) {
    throw 'NVMe SMART identity/sensor layout mismatch'
}
foreach ($field in @('media_data_integrity_errors', 'error_log_entries')) {
    if ([string]$raw.$field -cnotmatch '^(0|[1-9][0-9]*)$') {
        throw 'NVMe SMART storage error field malformed'
    }
}
$temperatures = @([double]$raw.composite_temperature_c,
                  [double]$raw.temperature_sensors[0].celsius,
                  [double]$raw.temperature_sensors[1].celsius)
if (@($temperatures | Where-Object { [double]::IsNaN($_) -or [double]::IsInfinity($_) -or $_ -le 0 -or $_ -gt 150 }).Count -ne 0) {
    throw 'NVMe SMART temperature invalid'
}
$observed = [DateTimeOffset]::Parse([string]$raw.observed_at).ToUnixTimeSeconds()
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($observed -gt $now -or $now - $observed -gt 30) { throw 'NVMe SMART observation stale' }
$receipt = [ordered]@{
    schema = 'prime.ssd-temperature.v1'
    host = $env:COMPUTERNAME
    device_id = '0'
    serial_number = $ExpectedSerial
    friendly_name = [string]$disk.FriendlyName
    sensor = 'NVMe.SMART.HealthLog0x02.CompositeAndTemperatureSensors'
    source = 'Windows.IOCTL_STORAGE_QUERY_PROPERTY.NVMeSmartHealthLog0x02'
    unit = 'C'
    composite_temperature_c = $temperatures[0]
    temperature_sensors = @(
        [ordered]@{ number = 1; celsius = $temperatures[1] },
        [ordered]@{ number = 2; celsius = $temperatures[2] }
    )
    critical_warning_bits = [int]$raw.critical_warning_bits
    media_data_integrity_errors = [string]$raw.media_data_integrity_errors
    error_log_entries = [string]$raw.error_log_entries
    captured_at = $observed
    boot_id = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
    collector_id = 'abex-nvme-smart-projection-v1'
    reader_sha256 = $ReaderSha256.ToLowerInvariant()
    read_ok = $true
}
$json = $receipt | ConvertTo-Json -Compress -Depth 5
$parent = [System.IO.Path]::GetDirectoryName($OutputPath)
if (-not [System.IO.Directory]::Exists($parent)) { throw 'Pre-provisioned output directory required' }
$temporary = Join-Path $parent ([System.IO.Path]::GetRandomFileName())
try {
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
    if ([System.IO.File]::Exists($OutputPath)) {
        [System.IO.File]::Replace($temporary, $OutputPath, $null)
    } else {
        [System.IO.File]::Move($temporary, $OutputPath)
    }
} finally {
    if ([System.IO.File]::Exists($temporary)) { [System.IO.File]::Delete($temporary) }
}
