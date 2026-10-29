# Host-owned Windows sampler. Accepts no caller arguments or network URLs.
# The receipt is an observation, not an assertion about its writer's ACLs.
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'Collector accepts no caller arguments' }

$Root = 'C:\ProgramData\ABEX\PrimeHostMetrics'
$OutputDirectory = Join-Path $Root 'receipt'
$OutputPath = Join-Path $OutputDirectory 'host-metrics.json'
$MaximumReceiptBytes = 131072
# The existing producer runs every minute. Allow scheduling/completion jitter
# without changing the original sample times or the producer cadence.
$MaximumRateIntervalSeconds = 150

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

function Get-EpochNow {
    return [double]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0)
}

function Get-CollectionReason($record) {
    if ($record.Exception -is [UnauthorizedAccessException] -or
        $record.CategoryInfo.Category -eq 'PermissionDenied') {
        return 'PERMISSION_DENIED'
    }
    return 'COLLECTION_FAILED'
}

function New-Observation([string]$source) {
    return [ordered]@{
        collection_status = 'UNAVAILABLE'
        reason = 'COLLECTION_FAILED'
        source = $source
        captured_at = Get-EpochNow
    }
}

foreach ($path in @($Root, $OutputDirectory)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Pre-provisioned directory required: $path"
    }
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Collector directory reparse point forbidden'
    }
}

# A previous receipt is only a same-boot counter baseline. Reboot, reset or an
# unreadable/absent baseline leaves rates unknown instead of reporting zero.
$previous = $null
try {
    if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
        $item = Get-Item -LiteralPath $OutputPath
        if ($item.Length -le $MaximumReceiptBytes -and
            -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $previous = [IO.File]::ReadAllText($OutputPath) | ConvertFrom-Json
        }
    }
} catch { $previous = $null }

$os = $null
$osFailure = 'COLLECTION_FAILED'
try { $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop }
catch { $osFailure = Get-CollectionReason $_ }
$osCapturedAt = Get-EpochNow
$bootId = if ($os -and $os.LastBootUpTime) { $os.LastBootUpTime.ToUniversalTime().ToString('o') } else { $null }

$cpu = New-Observation 'Win32_Processor.LoadPercentage'
$cpu.percent = $null
$cpu.logical_processors = $null
try {
    $processors = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
    $loads = @($processors | Where-Object { $null -ne $_.LoadPercentage } | ForEach-Object { [double]$_.LoadPercentage })
    if ($processors.Count -eq 0 -or $loads.Count -ne $processors.Count -or
        @($loads | Where-Object { $_ -lt 0 -or $_ -gt 100 -or [double]::IsNaN($_) -or [double]::IsInfinity($_) }).Count) {
        $cpu.reason = 'METRIC_NOT_REPORTED'
    } else {
        $cpu.percent = [double](($loads | Measure-Object -Average).Average)
        $cpu.logical_processors = [int](($processors | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
        $cpu.collection_status = 'OBSERVED'
        $cpu.reason = $null
    }
} catch { $cpu.reason = Get-CollectionReason $_ }
$cpu.captured_at = Get-EpochNow

$memory = New-Observation 'Win32_OperatingSystem.TotalVisibleMemorySize/FreePhysicalMemory'
$memory.total_bytes = $null
$memory.used_bytes = $null
$memory.available_bytes = $null
$memory.percent = $null
if ($os -and $null -ne $os.TotalVisibleMemorySize -and $null -ne $os.FreePhysicalMemory -and
    $os.TotalVisibleMemorySize -gt 0 -and $os.FreePhysicalMemory -ge 0 -and
    $os.FreePhysicalMemory -le $os.TotalVisibleMemorySize) {
    $memory.total_bytes = [long]$os.TotalVisibleMemorySize * 1024
    $memory.available_bytes = [long]$os.FreePhysicalMemory * 1024
    $memory.used_bytes = $memory.total_bytes - $memory.available_bytes
    $memory.percent = [double](100.0 * $memory.used_bytes / $memory.total_bytes)
    $memory.collection_status = 'OBSERVED'
    $memory.reason = $null
} else { $memory.reason = if ($os) { 'METRIC_NOT_REPORTED' } else { $osFailure } }
$memory.captured_at = $osCapturedAt
$wslRuntime = New-Observation 'Get-Process/vmmemWSL.WorkingSet64'
$wslRuntime.working_set_bytes = $null
$wslRuntime.process_count = 0
$wslRuntime.boot_id = $bootId
try {
    $wslProcesses = @(Get-Process -Name 'vmmemWSL' -ErrorAction Stop)
    $wslRuntime.process_count = $wslProcesses.Count
    if ($wslProcesses.Count -eq 1 -and $wslProcesses[0].WorkingSet64 -gt 0) {
        $wslRuntime.working_set_bytes = [long]$wslProcesses[0].WorkingSet64
        $wslRuntime.collection_status = 'OBSERVED'
        $wslRuntime.reason = $null
    } else { $wslRuntime.reason = 'SINGLE_WSL_VM_NOT_OBSERVED' }
} catch { $wslRuntime.reason = Get-CollectionReason $_ }
$wslRuntime.captured_at = Get-EpochNow

$disk = New-Observation 'Win32_LogicalDisk.Size/FreeSpace'
$disk.device = if ($env:SystemDrive) { [string]$env:SystemDrive } else { 'C:' }
$disk.total_bytes = $null
$disk.used_bytes = $null
$disk.available_bytes = $null
$disk.percent = $null
try {
    $volume = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($disk.device)'" -ErrorAction Stop
    if ($volume -and $null -ne $volume.Size -and $null -ne $volume.FreeSpace -and
        $volume.Size -gt 0 -and $volume.FreeSpace -ge 0 -and $volume.FreeSpace -le $volume.Size) {
        $disk.total_bytes = [long]$volume.Size
        $disk.available_bytes = [long]$volume.FreeSpace
        $disk.used_bytes = $disk.total_bytes - $disk.available_bytes
        $disk.percent = [double](100.0 * $disk.used_bytes / $disk.total_bytes)
        $disk.collection_status = 'OBSERVED'
        $disk.reason = $null
    } else { $disk.reason = 'METRIC_NOT_REPORTED' }
} catch { $disk.reason = Get-CollectionReason $_ }
$disk.captured_at = Get-EpochNow

$network = New-Observation 'Get-NetAdapter/Get-NetAdapterStatistics'
$network.interfaces = @()
$network.latency_ms = $null
$network.latency_status = 'UNAVAILABLE'
$network.latency_reason = 'GATEWAY_NOT_AVAILABLE'
$network.latency_source = 'Test-Connection/default IPv4 gateway'
$network.latency_captured_at = $null
try {
    $adapters = @(Get-NetAdapter -ErrorAction Stop)
    $statistics = @{}
    foreach ($statistic in @(Get-NetAdapterStatistics -Name '*' -ErrorAction Stop)) {
        $statistics[[string]$statistic.Name] = $statistic
    }
    $network.captured_at = Get-EpochNow
    $baselineReason = 'RATE_BASELINE_UNAVAILABLE'
    $baselineValid = $false
    $interval = $null
    if ($previous -and $previous.schema -eq 'orqevia.host-metrics.v1' -and
        $previous.collector_id -eq 'abex-host-metrics-v1' -and $previous.host_id -eq $env:COMPUTERNAME) {
        if ($previous.boot_id -ne $bootId) { $baselineReason = 'RATE_BASELINE_BOOT_CHANGED' }
        elseif ($previous.network -and $null -ne $previous.network.captured_at) {
            $interval = [double]$network.captured_at - [double]$previous.network.captured_at
            if ($interval -gt 0 -and $interval -le $MaximumRateIntervalSeconds) { $baselineValid = $true }
            else { $baselineReason = 'RATE_BASELINE_INTERVAL_INVALID' }
        }
    }
    $counterFields = [ordered]@{
        received_bytes = 'ReceivedBytes'
        sent_bytes = 'SentBytes'
        received_packet_errors = 'ReceivedPacketErrors'
        outbound_packet_errors = 'OutboundPacketErrors'
        received_discarded_packets = 'ReceivedDiscardedPackets'
        outbound_discarded_packets = 'OutboundDiscardedPackets'
    }
    $rows = @()
    foreach ($adapter in $adapters) {
        $row = [ordered]@{
            name = [string]$adapter.Name
            interface_index = [int]$adapter.ifIndex
            description = [string]$adapter.InterfaceDescription
            status = [string]$adapter.Status
            link_speed = [string]$adapter.LinkSpeed
            hardware_interface = [bool]$adapter.HardwareInterface
            collection_status = 'UNAVAILABLE'
            reason = 'INTERFACE_COUNTERS_UNAVAILABLE'
            source = 'Get-NetAdapter/Get-NetAdapterStatistics'
            captured_at = $network.captured_at
            received_bytes_per_second = $null
            sent_bytes_per_second = $null
            rate_interval_seconds = $null
            rate_status = 'UNAVAILABLE'
            rate_reason = $baselineReason
        }
        $stat = $statistics[[string]$adapter.Name]
        $validCounters = 0
        foreach ($field in $counterFields.Keys) {
            $value = if ($stat) { $stat.($counterFields[$field]) } else { $null }
            $row[$field] = if ($null -ne $value -and $value -ge 0) { [uint64]$value } else { $null }
            if ($null -ne $row[$field]) { $validCounters++ }
        }
        if ($baselineValid -and $null -ne $row.received_bytes -and $null -ne $row.sent_bytes) {
            $prior = @($previous.network.interfaces | Where-Object {
                $_.interface_index -eq $row.interface_index -and $_.name -eq $row.name -and $_.description -eq $row.description
            }) | Select-Object -First 1
            if (-not $prior -or $null -eq $prior.received_bytes -or $null -eq $prior.sent_bytes) {
                $row.rate_reason = 'RATE_BASELINE_INTERFACE_CHANGED'
            } elseif ($row.received_bytes -lt $prior.received_bytes -or $row.sent_bytes -lt $prior.sent_bytes) {
                $row.rate_reason = 'RATE_COUNTER_RESET'
            } else {
                $row.received_bytes_per_second = [double](($row.received_bytes - $prior.received_bytes) / $interval)
                $row.sent_bytes_per_second = [double](($row.sent_bytes - $prior.sent_bytes) / $interval)
                $row.rate_interval_seconds = $interval
                $row.rate_status = 'OBSERVED'
                $row.rate_reason = $null
            }
        }
        if ($validCounters -eq $counterFields.Count) {
            $row.collection_status = if ($row.rate_status -eq 'OBSERVED') { 'OBSERVED' } else { 'PARTIAL' }
            $row.reason = $row.rate_reason
        } elseif ($validCounters -gt 0) {
            $row.collection_status = 'PARTIAL'
            $row.reason = 'INTERFACE_COUNTERS_INCOMPLETE'
        }
        $rows += $row
    }
    $network.interfaces = @($rows)
    if ($rows.Count -eq 0) { $network.reason = 'NO_NETWORK_INTERFACES' }
    elseif (@($rows | Where-Object { $_.collection_status -ne 'OBSERVED' }).Count -eq 0) {
        $network.collection_status = 'OBSERVED'
        $network.reason = $null
    } else {
        $network.collection_status = 'PARTIAL'
        $network.reason = 'INTERFACE_MEASUREMENTS_INCOMPLETE'
    }
} catch {
    $network.reason = Get-CollectionReason $_
    $network.captured_at = Get-EpochNow
}

# Gateway latency remains a separate measurement from interface throughput.
try {
    $gateway = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Sort-Object RouteMetric | Select-Object -First 1
    if ($gateway -and $gateway.NextHop -and $gateway.NextHop -ne '0.0.0.0') {
        $ping = @(Test-Connection -ComputerName ([string]$gateway.NextHop) -Count 2 -ErrorAction SilentlyContinue)
        $responses = @($ping | Where-Object { $null -ne $_.ResponseTime } | ForEach-Object { [double]$_.ResponseTime })
        if ($responses.Count) {
            $latency = [double](($responses | Measure-Object -Average).Average)
            if (-not [double]::IsNaN($latency) -and -not [double]::IsInfinity($latency) -and $latency -ge 0) {
                $network.latency_ms = $latency
                $network.latency_status = 'OBSERVED'
                $network.latency_reason = $null
            } else { $network.latency_reason = 'METRIC_NOT_REPORTED' }
        } else { $network.latency_reason = 'GATEWAY_PROBE_FAILED' }
    }
} catch { $network.latency_reason = Get-CollectionReason $_ }
$network.latency_captured_at = Get-EpochNow

$fieldStatus = [ordered]@{}
foreach ($mapping in @(
    @('cpu_percent', $cpu), @('memory_percent', $memory), @('disk_percent', $disk)
)) {
    $observation = $mapping[1]
    $fieldStatus[$mapping[0]] = [ordered]@{
        collection_status = $observation.collection_status
        reason = $observation.reason
        source = $observation.source
        captured_at = $observation.captured_at
    }
}
$fieldStatus.network_latency_ms = [ordered]@{
    collection_status = $network.latency_status
    reason = $network.latency_reason
    source = $network.latency_source
    captured_at = $network.latency_captured_at
}
$resourceSensors = $null
$resourceSensorHelper = Join-Path $PSScriptRoot 'Get-ResourceSensors.ps1'
if (Test-Path -LiteralPath $resourceSensorHelper -PathType Leaf) {
    try {
        . $resourceSensorHelper
        $resourceSensors = Get-OrqeviaResourceSensors -ProbeThermal:($env:ORQEVIA_RESOURCE_THERMAL_PROBE -eq '1')
        $memory.commit_available_bytes = $resourceSensors.memory.commit_available_bytes
        $memory.committed_bytes = $resourceSensors.memory.committed_bytes
        $memory.commit_limit_bytes = $resourceSensors.memory.commit_limit_bytes
        $disk.busy_percent = $resourceSensors.disk.busy_percent
        $disk.queue_length = $resourceSensors.disk.queue_length
    } catch { $resourceSensors = $null }
}
$receipt = [ordered]@{
    schema = 'orqevia.host-metrics.v1'
    host_id = $env:COMPUTERNAME
    boot_id = $bootId
    collector_id = 'abex-host-metrics-v1'
    captured_at = Get-EpochNow
    cadence_seconds = 60
    cpu_percent = $cpu.percent
    memory_percent = $memory.percent
    disk_percent = $disk.percent
    network_latency_ms = $network.latency_ms
    field_status = $fieldStatus
    cpu = $cpu
    memory = $memory
    wsl_runtime = $wslRuntime
    disk = $disk
    network = $network
    gpu = if ($resourceSensors) { $resourceSensors.gpu } else { @{ collection_status='UNAVAILABLE'; available_bytes=$null } }
    thermal = if ($resourceSensors) { $resourceSensors.thermal } else { @{ collection_status='UNAVAILABLE'; maximum_c=$null } }
    resource_sensors = $resourceSensors
}
$json = $receipt | ConvertTo-Json -Compress -Depth 8
$encoding = [System.Text.UTF8Encoding]::new($false)
if ($encoding.GetByteCount($json) -gt $MaximumReceiptBytes) { throw 'Host receipt exceeds bounded file size' }
$temporary = Join-Path $OutputDirectory ([System.IO.Path]::GetRandomFileName())
try {
    [System.IO.File]::WriteAllText($temporary, $json, $encoding)
    if ([System.IO.File]::Exists($OutputPath)) {
        # Replace the directory entry atomically. File.Replace is unsupported
        # on this bridged/NTFS path; copying exposes transient partial JSON.
        [OrqeviaAtomicFile]::Replace($temporary, $OutputPath)
    } else {
        [System.IO.File]::Move($temporary, $OutputPath)
    }
} finally {
    if ([System.IO.File]::Exists($temporary)) { [System.IO.File]::Delete($temporary) }
}

# An optional fixed sibling produces operational receipts in the same existing
# scheduled invocation. No caller-controlled command, path or URL enters it.
$operationalCollector = Join-Path $Root 'collect-operational-health.ps1'
if (Test-Path -LiteralPath $operationalCollector -PathType Leaf) {
    try {
        if ((Get-Item -LiteralPath $operationalCollector).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Operational collector reparse point forbidden'
        }
        $null = & $operationalCollector
    } catch {
        Write-Warning ('Operational health collector failed; host receipt preserved (' + $_.Exception.GetType().Name + ')')
    }
}
