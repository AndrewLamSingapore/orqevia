# Optional enrichment for the existing host sampler. Read-only native Windows
# facilities; no daemon, installation, network probe, or process mutation.
function Get-OrqeviaResourceSensors {
    param([switch]$ProbeThermal)
    $taskSensors = [ordered]@{
        schema = 'abex.resource-sensors.v1'
        observed_at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
        gpu = [ordered]@{ collection_status='UNAVAILABLE'; source='Win32_PerfFormattedData_GPUPerformanceCounters'; available_bytes=$null; dedicated_usage_bytes=$null; shared_usage_bytes=$null; busiest_engine_percent=$null; scope='OBSERVED_ENGINES_NOT_TOTAL_SHARED_GPU_BUDGET' }
        thermal = [ordered]@{ collection_status='UNAVAILABLE'; source='MSAcpi_ThermalZoneTemperature'; maximum_c=$null; scope='ACPI_ZONES_NOT_CPU_DIE_OR_GPU_JUNCTION' }
        memory = [ordered]@{ collection_status='UNAVAILABLE'; source='Win32_PerfFormattedData_PerfOS_Memory'; commit_available_bytes=$null; committed_bytes=$null; commit_limit_bytes=$null; pages_per_second=$null }
        disk = [ordered]@{ collection_status='UNAVAILABLE'; source='Win32_PerfFormattedData_PerfDisk_PhysicalDisk'; busy_percent=$null; queue_length=$null }
        processes = @()
    }
    try {
        $taskGpuMemory = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory -ErrorAction Stop)
        $taskEngines = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop)
        if ($taskGpuMemory.Count -gt 0) {
            $taskSensors.gpu.dedicated_usage_bytes = [long](($taskGpuMemory | Measure-Object DedicatedUsage -Sum).Sum)
            $taskSensors.gpu.shared_usage_bytes = [long](($taskGpuMemory | Measure-Object SharedUsage -Sum).Sum)
            $taskSensors.gpu.busiest_engine_percent = if ($taskEngines.Count) { [double](($taskEngines | Measure-Object UtilizationPercentage -Maximum).Maximum) } else { $null }
            $taskSensors.gpu.collection_status = 'OBSERVED_USAGE_CAPACITY_UNKNOWN'
        }
    } catch {}
    try {
        # ABEX's read-only audit found no qualified ACPI sensor. Avoid an
        # expensive unsupported WMI query every minute; retain an explicit
        # on-demand qualification path when a sensor becomes available.
        if (-not $ProbeThermal) { throw 'No qualified thermal provider configured' }
        $taskZones = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | Select-Object -First 16)
        $taskTemperatures = @($taskZones | ForEach-Object { [double]$_.CurrentTemperature / 10.0 - 273.15 } | Where-Object { $_ -gt 0 -and $_ -lt 150 })
        if ($taskTemperatures.Count) {
            $taskSensors.thermal.maximum_c = [double](($taskTemperatures | Measure-Object -Maximum).Maximum)
            $taskSensors.thermal.collection_status = 'OBSERVED_ACPI_ONLY'
        }
    } catch {}
    try {
        $taskCommit = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -ErrorAction Stop
        if ($taskCommit.CommitLimit -gt 0 -and $taskCommit.CommittedBytes -le $taskCommit.CommitLimit) {
            $taskSensors.memory.committed_bytes = [long]$taskCommit.CommittedBytes
            $taskSensors.memory.commit_limit_bytes = [long]$taskCommit.CommitLimit
            $taskSensors.memory.commit_available_bytes = [long]$taskCommit.CommitLimit - [long]$taskCommit.CommittedBytes
            $taskSensors.memory.pages_per_second = [double]$taskCommit.PagesPersec
            $taskSensors.memory.collection_status = 'OBSERVED'
        }
    } catch {}
    try {
        $taskDisk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'" -ErrorAction Stop
        if ($null -ne $taskDisk) {
            $taskSensors.disk.busy_percent = [math]::Max(0, [math]::Min(100, 100 - [double]$taskDisk.PercentIdleTime))
            $taskSensors.disk.queue_length = [double]$taskDisk.CurrentDiskQueueLength
            $taskSensors.disk.collection_status = 'OBSERVED'
        }
    } catch {}
    try {
        $taskSensors.processes = @(Get-Process -ErrorAction Stop | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 Id,ProcessName,WorkingSet64)
    } catch {}
    return $taskSensors
}
