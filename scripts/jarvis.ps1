[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "ask", "status", "doctor", "repair", "open", "update", "verify", "contract")]
    [string]$Action = "start",
    [string]$Image = "",
    [string]$Intent = "",
    [switch]$Tunnel,
    [switch]$NoOpen,
    [switch]$Diagnostics,
    [ValidateRange(30, 900)]
    [int]$TimeoutSeconds = 240
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "docker-compose.yml"
$EnvFile = Join-Path $Root ".env"
$Project = "prime"
$LocalBase = "http://127.0.0.1:8000"
$ExpectedVersion = "7.3.1.1-evidence-grounded"
$script:Checkpoint = $null
. (Join-Path $PSScriptRoot 'native-inference-preflight.ps1')

function Write-Step([string]$Message) {
    Write-Host "[JARVIS] $Message" -ForegroundColor Cyan
}

function Invoke-Docker {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $previousErrorAction = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 wraps native stderr (including normal Docker
        # pull progress) as error records. Docker's exit code is authoritative.
        $ErrorActionPreference = "Continue"
        $output = @(& docker @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "docker $($Arguments -join ' ') failed (exit $code).`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is not installed or docker.exe is not on PATH."
    }
    Invoke-Docker -Arguments @("version", "--format", "{{.Server.Version}}") | Out-Null
    Invoke-Docker -Arguments @("compose", "version", "--short") | Out-Null
}

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { return "" }
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    return ($line -split "=", 2)[1].Trim()
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = if (Test-Path $EnvFile) { @(Get-Content $EnvFile) } else { @() }
    $updated = $false
    $next = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Name))=") {
            if (-not $updated) { "$Name=$Value"; $updated = $true }
        } else { $line }
    }
    if (-not $updated) { $next += "$Name=$Value" }
    [IO.File]::WriteAllLines($EnvFile, [string[]]$next, (New-Object Text.UTF8Encoding($false)))
}

function Get-ComposeArgs([string[]]$Tail, [bool]$UseTunnel = $false) {
    $dockerArgs = @("compose", "--project-name", $Project, "--file", $ComposeFile)
    if (Test-Path $EnvFile) { $dockerArgs += @("--env-file", $EnvFile) }
    if ($UseTunnel) { $dockerArgs += @("--profile", "tunnel") }
    return $dockerArgs + $Tail
}

function Get-ContainerRows([switch]$All) {
    $dockerArgs = @("ps")
    if ($All) { $dockerArgs += "-a" }
    $dockerArgs += @("--format", "{{json .}}")
    $rows = Invoke-Docker -Arguments $dockerArgs -AllowFailure
    return @($rows | Where-Object { $_ } | ForEach-Object {
        $item = $_ | ConvertFrom-Json
        $labels = @{}
        foreach ($pair in ("$($item.Labels)" -split ',')) {
            if ($pair -match '^([^=]+)=(.*)$') { $labels[$matches[1]] = $matches[2] }
        }
        [pscustomobject]@{
            Id="$($item.ID)"
            Name="$($item.Names)"
            Project="$($labels['com.docker.compose.project'])"
            Service="$($labels['com.docker.compose.service'])"
            Status="$($item.Status)"
            Ports="$($item.Ports)"
        }
    })
}

function Save-Checkpoint {
    if ($script:Checkpoint) { return $script:Checkpoint }
    $base = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "JARVIS\checkpoints"
    if (-not $base.Trim()) { $base = Join-Path $env:TEMP "JARVIS-checkpoints" }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmssZ")
    $script:Checkpoint = Join-Path $base $stamp
    New-Item -ItemType Directory -Force -Path $script:Checkpoint | Out-Null
    # Never persist container commands or Config.Env: they may contain secrets.
    (Invoke-Docker -Arguments @("ps", "-a", "--no-trunc", "--format", '{{.ID}} {{.Image}} {{.Status}} {{.Names}}') -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "containers.txt")
    (Invoke-Docker -Arguments @("volume", "ls") -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "volumes.txt")
    (Invoke-Docker -Arguments @("network", "ls") -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "networks.txt")
    $ids = @(Get-ContainerRows -All | ForEach-Object { $_.Id })
    if ($ids.Count -gt 0) {
        $safeFormat = '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"mounts":{{json .Mounts}}}'
        (Invoke-Docker -Arguments (@("inspect", "--format", $safeFormat) + $ids) -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "containers.recovery.jsonl")
    }
    Write-Step "Recovery inventory saved to $script:Checkpoint"
    return $script:Checkpoint
}

function Get-VolumeForContainer([string]$ContainerId, [string]$Destination) {
    $json = (Invoke-Docker -Arguments @("inspect", $ContainerId) -AllowFailure) -join [Environment]::NewLine
    if (-not $json.Trim()) { return "" }
    $details = @($json | ConvertFrom-Json)
    $mount = $details[0].Mounts | Where-Object { $_.Destination -eq $Destination } | Select-Object -First 1
    if (-not $mount) { return "" }
    return "$($mount.Name)".Trim()
}

function Adopt-PersistentVolumes {
    $rows = Get-ContainerRows
    if (-not (Get-EnvValue "PRIME_DATA_VOLUME")) {
        $source = $rows | Where-Object { $_.Service -eq "prime" } | Select-Object -First 1
        if ($source) {
            $volume = Get-VolumeForContainer $source.Id "/data"
            if ($volume) { Set-EnvValue "PRIME_DATA_VOLUME" $volume; Write-Step "Adopted the existing PRIME data volume." }
        }
    }
    if (-not (Get-EnvValue "OLLAMA_DATA_VOLUME")) {
        $source = $rows | Where-Object { $_.Name -eq "prime-github-ready1-ollama-1" } | Select-Object -First 1
        if (-not $source) { $source = $rows | Where-Object { $_.Service -eq "ollama" } | Select-Object -First 1 }
        if ($source) {
            $volume = Get-VolumeForContainer $source.Id "/root/.ollama"
            if ($volume) { Set-EnvValue "OLLAMA_DATA_VOLUME" $volume; Write-Step "Adopted the existing Ollama model volume." }
        }
    }
}

function Ensure-PersistentVolumes {
    $primeVolume = Get-EnvValue "PRIME_DATA_VOLUME"
    $ollamaVolume = Get-EnvValue "OLLAMA_DATA_VOLUME"
    if (-not $primeVolume) { $primeVolume = "prime-data" }
    if (-not $ollamaVolume) { $ollamaVolume = "prime-ollama-data" }
    $required = @($primeVolume, $ollamaVolume)
    $existing = @(Invoke-Docker -Arguments @("volume", "ls", "--format", "{{.Name}}"))
    foreach ($volume in $required) {
        if ($volume -notin $existing) {
            Write-Step "Creating protected persistent volume $volume."
            Invoke-Docker -Arguments @("volume", "create", $volume) | Out-Null
        }
    }
}

function Stop-LegacyCoreContainers {
    $legacy = @(Get-ContainerRows | Where-Object {
        $_.Project -ne $Project -and $_.Service -in @("prime", "ollama", "model-init")
    })
    if ($legacy.Count -eq 0) { return }
    Save-Checkpoint | Out-Null
    foreach ($container in $legacy) {
        Write-Step "Superseding legacy container $($container.Name) (volume data is retained)."
        Invoke-Docker -Arguments @("stop", "--time", "30", $container.Id) | Out-Null
        Invoke-Docker -Arguments @("rm", $container.Id) | Out-Null
    }
}

function Remove-LegacyEdgeContainers {
    $legacy = @(Get-ContainerRows | Where-Object {
        $_.Project -ne $Project -and $_.Service -in @("integration-gateway", "cloudflared")
    })
    if ($legacy.Count -eq 0) { return }
    Save-Checkpoint | Out-Null
    foreach ($container in $legacy) {
        Write-Step "Superseding legacy edge container $($container.Name)."
        Invoke-Docker -Arguments @("stop", "--time", "15", $container.Id) | Out-Null
        Invoke-Docker -Arguments @("rm", $container.Id) | Out-Null
    }
}

function Assert-PortAvailable {
    $rows = @(Get-ContainerRows | Where-Object { $_.Ports -match "127\.0\.0\.1:8000->|0\.0\.0\.0:8000->|\[::\]:8000->" })
    $unexpected = @($rows | Where-Object { $_.Project -ne $Project -and $_.Service -ne "prime" })
    if ($unexpected.Count -gt 0) {
        throw "Port 8000 belongs to unrelated container $($unexpected[0].Name). JARVIS left it untouched."
    }
}

function Get-Json([string]$Url, [int]$Timeout = 8) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $Timeout -Headers @{"Cache-Control"="no-cache"}
    if ($response.StatusCode -ne 200) { throw "$Url returned HTTP $($response.StatusCode)." }
    return $response.Content | ConvertFrom-Json
}

function Get-HttpStatus([string]$Url, [int]$Timeout = 8) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $Timeout -MaximumRedirection 0).StatusCode
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

function Wait-ForPrime {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Get-Json "$LocalBase/health" 4
            if ($health.ok -eq $true) { return $health }
        } catch { Start-Sleep -Seconds 3 }
    } while ((Get-Date) -lt $deadline)
    $logs = Invoke-Docker -Arguments (Get-ComposeArgs @("logs", "--tail", "80", "prime")) -AllowFailure
    throw "PRIME did not become healthy within $TimeoutSeconds seconds.`n$($logs -join [Environment]::NewLine)"
}

function Test-PrimeContract([switch]$Quiet) {
    $failures = New-Object System.Collections.Generic.List[string]
    try {
        $health = Get-Json "$LocalBase/health"
        if ($health.ok -ne $true) { $failures.Add("health.ok is not true") }
        if ($health.version -ne $ExpectedVersion) { $failures.Add("unexpected runtime version: $($health.version)") }
        if ($health.integrity -ne "ok") { $failures.Add("runtime integrity is not ok") }
    } catch { $failures.Add("health unavailable: $($_.Exception.Message)") }
    if ((Get-HttpStatus "$LocalBase/control") -ne 200) { $failures.Add("/control is not HTTP 200") }
    try {
        $manifest = Get-Json "$LocalBase/api/control-surface/manifest"
        if ($manifest.mode -ne "approval-gated") { $failures.Add("manifest mode is not approval-gated") }
        if ($manifest.boundaries.approval_decision -ne $true) { $failures.Add("approval decision boundary is not enabled") }
        foreach ($key in @("autonomous_actions", "approval_executes_action", "memory_write", "runtime_mutation", "velyqua_dependency", "physical_actuation")) {
            if ($manifest.boundaries.$key -ne $false) { $failures.Add("boundary $key is not false") }
        }
    } catch { $failures.Add("manifest unavailable: $($_.Exception.Message)") }
    if ((Get-HttpStatus "$LocalBase/api/status") -ne 200) { $failures.Add("/api/status is not HTTP 200") }

    $public = Get-EnvValue "PRIME_PUBLIC_URL"
    if ($public) {
        $public = $public.TrimEnd("/")
        if ((Get-HttpStatus "$public/health") -ne 200) { $failures.Add("public /health is not HTTP 200") }
        foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest")) {
            if ((Get-HttpStatus "$public$path") -ne 404) { $failures.Add("public $path is not blocked with HTTP 404") }
        }
    }
    if ($failures.Count -gt 0) { throw "JARVIS contract failed:`n- $($failures -join "`n- ")" }
    if (-not $Quiet) { Write-Host "JARVIS is healthy, local-only, approval-gated and no-actuation." -ForegroundColor Green }
}

function Resolve-TunnelMode {
    return $Tunnel.IsPresent -or ((Get-EnvValue "PRIME_INTEGRATION_TOKEN") -and (Get-EnvValue "CLOUDFLARE_TUNNEL_TOKEN"))
}

function Start-Jarvis([switch]$RepairOnly) {
    Assert-NativeInferenceIsolated
    Assert-Docker
    Invoke-Docker -Arguments (Get-ComposeArgs @("config", "--quiet")) | Out-Null
    Adopt-PersistentVolumes
    Ensure-PersistentVolumes
    Assert-PortAvailable
    Stop-LegacyCoreContainers
    if ($RepairOnly) { return }

    $useTunnel = [bool](Resolve-TunnelMode)
    $primeImage = Get-EnvValue "PRIME_IMAGE"
    if ($primeImage) {
        Write-Step "Pulling the exact PRIME image."
        Invoke-Docker -Arguments (Get-ComposeArgs @("pull", "prime")) | Out-Null
        $up = @("up", "-d", "--remove-orphans", "--no-build")
    } else {
        Write-Step "No PRIME_IMAGE is pinned; building the checked-out source."
        $up = @("up", "-d", "--remove-orphans", "--build")
    }
    Write-Step "Starting the canonical PRIME project."
    Invoke-Docker -Arguments (Get-ComposeArgs $up $useTunnel) | Out-Null
    Wait-ForPrime | Out-Null
    Test-PrimeContract -Quiet
    if ($useTunnel) { Remove-LegacyEdgeContainers }
    Write-Host "JARVIS READY - $LocalBase/control" -ForegroundColor Green
    if (-not $NoOpen) { Start-Process "$LocalBase/control" }
}

function Show-Status {
    if ($Diagnostics) {
        Assert-Docker
        Invoke-Docker -Arguments (Get-ComposeArgs @("ps", "--all")) | Write-Host
    }
    try {
        $summary = Get-Json "$LocalBase/api/control-surface/trusted/operator-status"
        Write-Host "PRIME: $($summary.state)"
        foreach ($item in $summary.attention) {
            Write-Host $item.what_happened
            Write-Host $item.handled
            Write-Host $item.affected
            Write-Host $item.action
        }
        Write-Host "Production qualification is still pending."
        Write-Host "Open JARVIS to see current and completed work."
        if ($summary.state -ne "HEALTHY") { exit 1 }
    } catch {
        Write-Host "PRIME's current status could not be verified. No successful recovery is claimed." -ForegroundColor Yellow
        Write-Host "Use JARVIS doctor for read-only checks. Do not repeatedly restart or resubmit work."
        if ($Diagnostics) { Write-Host $_.Exception.GetType().Name }
        exit 1
    }
}

function Submit-Intent {
    if (-not $Intent) { $Intent = Read-Host "What would you like JARVIS to check or review?" }
    if (-not $Intent.Trim()) { throw "No request was entered." }
    $ownerToken = Get-EnvValue "PRIME_SPINE_TOKEN"
    if (-not $ownerToken) { throw "JARVIS owner access is not configured. No request was sent." }
    $headers = @{ Authorization = "Bearer $ownerToken" }
    $requestId = [guid]::NewGuid().ToString()
    $body = @{ intent = $Intent; correlation_id = $requestId; idempotency_key = $requestId } | ConvertTo-Json -Compress
    try {
        # Submit once. A lost response is not permission to duplicate work.
        $reply = Invoke-RestMethod -Method Post -Uri "$LocalBase/api/harness/intent" -Headers $headers -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 15
    } catch {
        throw "JARVIS could not confirm this request. Reference: $requestId. Do not resubmit automatically; check status. Unsupported requests need a bounded check or advisory review."
    }
    if ($reply.PSObject.Properties["result"]) { Write-Host $reply.result; return }
    if ($reply.PSObject.Properties["status"]) {
        Write-Host "PRIME: $($reply.status.state)"
        foreach ($item in $reply.status.attention) { Write-Host $item.what_happened; Write-Host $item.action }
        return
    }
    if (-not $reply.PSObject.Properties["job"]) { throw "JARVIS returned no recorded work reference." }
    $jobId = [string]$reply.job.id
    if ($jobId -notmatch '^[a-zA-Z0-9_-]+$') { throw "JARVIS returned an invalid work reference." }
    Write-Host "JARVIS accepted the request. Work reference: $jobId"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $job = Invoke-RestMethod -Method Get -Uri "$LocalBase/api/compute-queue/jobs/$jobId" -Headers $headers -TimeoutSec 8
        } catch { throw "The recorded work could not be checked. Keep reference $jobId; do not submit it again." }
        if ($job.status -eq "completed") { Write-Host $job.result; Write-Host "This is an advisory result, not action approval."; return }
        if ($job.status -in @("failed", "cancelled", "awaiting_approval", "uncertain")) {
            Write-Host "Work is $($job.status). Review its recorded evidence in JARVIS. It was not resubmitted."
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Write-Host "Work remains recorded as $($job.status). Check JARVIS later using reference $jobId."
}

function Restart-Jarvis {
    $summary = Get-Json "$LocalBase/api/control-surface/trusted/operator-status"
    if ($summary.state -ne "HEALTHY" -or $summary.work_available -ne $true) {
        throw "Restart held: safe, idle work state could not be verified."
    }
    foreach ($entry in $summary.work.PSObject.Properties) {
        if ($entry.Name -notin @("completed", "failed", "cancelled") -and [int]$entry.Value -gt 0) {
            throw "Restart held: recorded work is still pending. Let it finish or obtain a recovery review."
        }
    }
    Assert-NativeInferenceIsolated
    Assert-Docker
    Invoke-Docker -Arguments (Get-ComposeArgs @("down", "--remove-orphans")) | Out-Null
    Start-Jarvis
}

function Invoke-Doctor {
    Assert-Docker
    Write-Step "Validating Compose."
    Invoke-Docker -Arguments (Get-ComposeArgs @("config", "--quiet")) | Out-Null
    $rows = Get-ContainerRows -All
    $runningLegacy = @($rows | Where-Object { $_.Project -ne $Project -and $_.Status -match '^Up ' -and $_.Service -in @("prime", "ollama", "model-init", "integration-gateway", "cloudflared") })
    if ($runningLegacy.Count -gt 0) {
        Write-Host "Running legacy containers: $($runningLegacy.Name -join ', ')" -ForegroundColor Yellow
    } else { Write-Host "No running legacy JARVIS containers." -ForegroundColor Green }
    Show-Status
}

function Update-Jarvis {
    Assert-NativeInferenceIsolated
    if (-not $Image) { throw "Use -Image ghcr.io/andrewlamsingapore/prime:sha-<verified-commit>." }
    if ($Image -notmatch '^ghcr\.io/andrewlamsingapore/prime:sha-[0-9a-f]{7,40}$') {
        throw "The image must be a commit-addressable AndrewLamSingapore/prime GHCR image."
    }
    Save-Checkpoint | Out-Null
    Set-EnvValue "PRIME_IMAGE" $Image
    Write-Step "Pinned the verified PRIME image without changing secrets or volumes."
    Start-Jarvis
}

function Test-SourceContract {
    if (-not (Test-Path $ComposeFile)) { throw "docker-compose.yml is missing." }
    $source = Get-Content $ComposeFile -Raw
    foreach ($required in @('name: ${COMPOSE_PROJECT_NAME:-prime}', '${PRIME_BIND_ADDRESS:-127.0.0.1}', 'com.lamjarvis.managed', '${PRIME_DATA_VOLUME:-prime-data}', '${OLLAMA_DATA_VOLUME:-prime-ollama-data}')) {
        if (-not $source.Contains($required)) { throw "Compose contract is missing: $required" }
    }
    Write-Host "PASS: JARVIS source operations contract." -ForegroundColor Green
}

Set-Location $Root
switch ($Action) {
    "start" { Start-Jarvis }
    "ask" { Submit-Intent }
    "restart" { Restart-Jarvis }
    "stop" { Assert-Docker; Invoke-Docker -Arguments (Get-ComposeArgs @("down", "--remove-orphans")) | Out-Null; Write-Host "JARVIS stopped. Volumes retained." -ForegroundColor Yellow }
    "status" { Show-Status }
    "doctor" { Invoke-Doctor }
    "repair" { Start-Jarvis -RepairOnly; Start-Jarvis }
    "open" { Start-Process "$LocalBase/control" }
    "update" { Update-Jarvis }
    "verify" { Test-PrimeContract; Show-Status }
    "contract" { Test-SourceContract }
}
