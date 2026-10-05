# Source-only collector candidate. Installation, task identity and ACLs require
# separate review. The runner must be allowed to read StorageReliabilityCounter;
# PRIME must have read-only access to OutputPath and no write access to it.
param(
    [Parameter(Mandatory=$true)][string]$DeviceId,
    [Parameter(Mandatory=$true)][string]$ExpectedSerial,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'

if (-not [System.IO.Path]::IsPathRooted($OutputPath)) { throw 'Absolute output path required' }
$matches = @(Get-PhysicalDisk | Where-Object { [string]$_.DeviceId -eq $DeviceId })
if ($matches.Count -ne 1) { throw 'Exact physical disk not found' }
$disk = $matches[0]
$serial = ([string]$disk.SerialNumber).Trim()
if (-not $serial -or $serial -ne $ExpectedSerial) { throw 'Physical disk serial mismatch' }
$counter = $disk | Get-StorageReliabilityCounter
if ($null -eq $counter -or $null -eq $counter.Temperature) { throw 'Temperature unsupported' }
$temperature = [double]$counter.Temperature
if ([double]::IsNaN($temperature) -or [double]::IsInfinity($temperature) -or
    $temperature -le 0 -or $temperature -gt 150) { throw 'Temperature invalid' }

$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
$captured = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$receipt = [ordered]@{
    schema = 'prime.ssd-temperature.v1'
    host = $env:COMPUTERNAME
    device_id = [string]$disk.DeviceId
    serial_number = $serial
    friendly_name = [string]$disk.FriendlyName
    sensor = 'MSFT_StorageReliabilityCounter.Temperature'
    source = 'Windows.StorageReliabilityCounter'
    unit = 'C'
    temperature_c = $temperature
    captured_at = $captured
    boot_id = $boot
    collector_id = 'abex-windows-storage-v1'
    read_ok = $true
}
$json = $receipt | ConvertTo-Json -Compress -Depth 3
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
