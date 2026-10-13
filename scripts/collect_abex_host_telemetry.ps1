param(
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$')][string]$HostId,
    [switch]$Continuous,
    [ValidateRange(15,600)][int]$IntervalSeconds = 30,
    [ValidateRange(1,10000)][int]$MaxSamples = 1
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$destination = [IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $destination
New-Item -ItemType Directory -Path $parent -Force | Out-Null

function Measure-HostMetric([string]$Name, [string]$Unit, [string]$Producer, [string]$Scope, [scriptblock]$Read) {
    $row = [ordered]@{metric_id=$Name;unit=$Unit;producer=$Producer;scope=$Scope;event_timestamp=$null;value=$null;collection_status='UNAVAILABLE';failure_code='COLLECTION_FAILED'}
    try {
        $value = & $Read
        $maximum = if ($Unit -eq 'percent') { 100 } else { 5000 }
        if ($null -eq $value -or $value -is [bool]) { throw 'INVALID_SAMPLE' }
        $number = [double]$value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number) -or $number -lt 0 -or $number -gt $maximum) { throw 'INVALID_SAMPLE' }
        $row.value = [math]::Round($number, 3)
        $row.collection_status = 'OBSERVED'
        $row.Remove('failure_code')
    } catch {
        # Only fixed failure categories are retained; no exception/URL/credential text.
        if ($_.Exception.Message -in @('DEPENDENCY_UNAVAILABLE','HTTP_UNHEALTHY','INVALID_SAMPLE')) { $row.failure_code = $_.Exception.Message }
        elseif ($_.Exception -is [Net.WebException]) { $row.failure_code = if ($null -ne $_.Exception.Response) { 'HTTP_UNHEALTHY' } else { 'DEPENDENCY_UNAVAILABLE' } }
    }
    $row.event_timestamp = [datetime]::UtcNow.ToString('o')
    return $row
}

$sample = 0
do {
    $metrics = @()
    $metrics += Measure-HostMetric 'cpu' 'percent' 'WINDOWS_CIM_CPU' 'HOST_CPU_LOAD' {
        $rows = @(Get-CimInstance Win32_Processor -OperationTimeoutSec 3)
        if (-not $rows.Count -or @($rows | Where-Object {$null -eq $_.LoadPercentage -or $null -eq $_.NumberOfLogicalProcessors}).Count) { throw 'DEPENDENCY_UNAVAILABLE' }
        $weight = 0; $total = 0.0
        foreach ($processor in $rows) {
            $load = [double]$processor.LoadPercentage; $logical = [int]$processor.NumberOfLogicalProcessors
            if ([double]::IsNaN($load) -or [double]::IsInfinity($load) -or $load -lt 0 -or $load -gt 100 -or $logical -le 0) { throw 'INVALID_SAMPLE' }
            $weight += $logical; $total += $load * $logical
        }
        if ($weight -le 0) { throw 'INVALID_SAMPLE' }
        $total / $weight
    }
    $metrics += Measure-HostMetric 'memory' 'percent' 'WINDOWS_CIM_MEMORY' 'HOST_PHYSICAL_MEMORY_USED' {
        $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3
        if ($null -eq $os.TotalVisibleMemorySize -or $null -eq $os.FreePhysicalMemory) { throw 'DEPENDENCY_UNAVAILABLE' }
        $total = [double]$os.TotalVisibleMemorySize; $free = [double]$os.FreePhysicalMemory
        if ($total -le 0 -or $free -lt 0 -or $free -gt $total) { throw 'INVALID_SAMPLE' }
        100.0 * ($total - $free) / $total
    }
    $metrics += Measure-HostMetric 'disk' 'percent' 'WINDOWS_CIM_C_VOLUME' 'C_VOLUME_CAPACITY_USED' {
        $volume = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" -OperationTimeoutSec 3
        if ($null -eq $volume -or $null -eq $volume.Size -or $null -eq $volume.FreeSpace) { throw 'DEPENDENCY_UNAVAILABLE' }
        $total = [double]$volume.Size; $free = [double]$volume.FreeSpace
        if ($total -le 0 -or $free -lt 0 -or $free -gt $total) { throw 'INVALID_SAMPLE' }
        100.0 * ($total - $free) / $total
    }
    $metrics += Measure-HostMetric 'network_latency' 'ms' 'WINDOWS_HTTP_STOPWATCH' 'LOCAL_LOOPBACK_HTTP_HEALTH' {
        # Fixed local liveness GET only: elapsed HTTP time is not global network latency.
        $request = [Net.HttpWebRequest]::Create('http://127.0.0.1:8000/health')
        $request.Proxy = $null; $request.AllowAutoRedirect = $false
        $request.Timeout = 2000; $request.ReadWriteTimeout = 2000; $request.Method = 'GET'
        $timer = [Diagnostics.Stopwatch]::StartNew(); $response = $null
        try {
            $response = $request.GetResponse()
            if ([int]$response.StatusCode -ne 200) { throw 'HTTP_UNHEALTHY' }
            $stream = $response.GetResponseStream()
            try {
                $buffer = New-Object byte[] 64
                $read = 0
                do { $count = $stream.Read($buffer, $read, $buffer.Length - $read); $read += $count } while ($count -gt 0 -and $read -lt $buffer.Length)
                if ($read -ge $buffer.Length) { throw 'HTTP_UNHEALTHY' }
                $body = [Text.Encoding]::UTF8.GetString($buffer, 0, $read) | ConvertFrom-Json
                if ($body.ok -ne $true) { throw 'HTTP_UNHEALTHY' }
            } finally { $stream.Dispose() }
            $timer.Stop(); $timer.Elapsed.TotalMilliseconds
        } finally {
            if ($null -ne $response) { $response.Close() }
            $request.Abort()
        }
    }
    $receipt = [ordered]@{schema_version='orqevia.host-telemetry.v1';source=@{system='WINDOWS_HOST';instance=$HostId;collector='windows-cim-http-v1'};collected_at_utc=[datetime]::UtcNow.ToString('o');metrics=$metrics}
    $temporary = Join-Path $parent ('.host-telemetry-'+[guid]::NewGuid().ToString('N')+'.tmp')
    try {
        [IO.File]::WriteAllText($temporary, ($receipt | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
        # A same-directory replacement keeps the visible receipt parseable.
        if ([IO.File]::Exists($destination)) { [IO.File]::Replace($temporary,$destination,[NullString]::Value) }
        else { [IO.File]::Move($temporary,$destination) }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
    $sample++
    if ($Continuous -or $sample -lt $MaxSamples) { Start-Sleep -Seconds $IntervalSeconds }
} while ($Continuous -or $sample -lt $MaxSamples)
$destination
