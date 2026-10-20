# Operator-owned host metrics sampler. No caller arguments, paths or commands
# are accepted. Produces an atomic, read-only-consumable receipt for the
# interface telemetry surface. Run under a protected broker account.
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'Collector accepts no caller arguments' }

$Root = 'C:\ProgramData\ABEX\PrimeHostMetrics'
$OutputDirectory = Join-Path $Root 'receipt'
$OutputPath = Join-Path $OutputDirectory 'host-metrics.json'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class OrqeviaAtomicFile
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool MoveFileEx(string existingFile, string newFile, int flags);

    public static void Replace(string source, string target)
    {
        const int ReplaceExisting = 0x1;
        const int WriteThrough = 0x8;
        if (!MoveFileEx(source, target, ReplaceExisting | WriteThrough))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }
}
'@
foreach ($path in @($Root, $OutputDirectory)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Pre-provisioned directory required: $path"
    }
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Protected broker directory reparse point forbidden'
    }
}

$os = Get-CimInstance Win32_OperatingSystem
$cpu = [double]((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average)
$memory = [double](100.0 * (1.0 - ([double]$os.FreePhysicalMemory / [double]$os.TotalVisibleMemorySize)))
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$diskPercent = [double](100.0 * (1.0 - ([double]$disk.FreeSpace / [double]$disk.Size)))
$gateway = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
$latency = $null
if ($gateway -and $gateway.NextHop) {
    $ping = Test-Connection -ComputerName ([string]$gateway.NextHop) -Count 2 -ErrorAction SilentlyContinue
    if ($ping) {
        $latency = [double](($ping | Measure-Object -Property ResponseTime -Average).Average)
    }
}
foreach ($value in @($cpu, $memory, $diskPercent)) {
    if ([double]::IsNaN($value) -or [double]::IsInfinity($value) -or $value -lt 0 -or $value -gt 100) {
        throw 'Host metric out of range'
    }
}
if ($null -ne $latency -and ([double]::IsNaN($latency) -or [double]::IsInfinity($latency) -or $latency -lt 0)) {
    throw 'Network latency out of range'
}

$receipt = [ordered]@{
    schema = 'orqevia.host-metrics.v1'
    host_id = $env:COMPUTERNAME
    boot_id = $os.LastBootUpTime.ToUniversalTime().ToString('o')
    collector_id = 'abex-host-metrics-v1'
    captured_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    cpu_percent = $cpu
    memory_percent = $memory
    disk_percent = $diskPercent
    network_latency_ms = $latency
}
$json = $receipt | ConvertTo-Json -Compress -Depth 3
$temporary = Join-Path $OutputDirectory ([System.IO.Path]::GetRandomFileName())
try {
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.UTF8Encoding]::new($false))
    if ([System.IO.File]::Exists($OutputPath)) {
        # Replace the directory entry in one filesystem operation. File.Replace
        # is unsupported on this bridged/NTFS path shape, while a copy exposes a
        # transient partial JSON receipt to the canary reader.
        [OrqeviaAtomicFile]::Replace($temporary, $OutputPath)
    } else {
        [System.IO.File]::Move($temporary, $OutputPath)
    }
} finally {
    if ([System.IO.File]::Exists($temporary)) { [System.IO.File]::Delete($temporary) }
}
