[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status", "doctor", "repair", "open", "update", "contract")]
    [string]$Action = "start",
    [string]$Image = "",
    [switch]$Tunnel,
    [switch]$NoOpen,
    [ValidateRange(30, 900)]
    [int]$TimeoutSeconds = 240
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "docker-compose.yml"
$EnvFile = Join-Path $Root ".env"
$Project = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { "orqevia" }
$LocalBase = "http://127.0.0.1:8000"
$ExpectedVersion = "7.3.1.1-evidence-grounded"
$script:Checkpoint = $null

function Write-Step([string]$Message) {
    Write-Host "[ORQEVIA] $Message" -ForegroundColor Cyan
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
    $base = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "ORQEVIA\checkpoints"
    if (-not $base.Trim()) { $base = Join-Path $env:TEMP "ORQEVIA-checkpoints" }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmssZ")
    $script:Checkpoint = Join-Path $base $stamp
    New-Item -ItemType Directory -Force -Path $script:Checkpoint | Out-Null
    (Invoke-Docker -Arguments @("ps", "-a", "--no-trunc") -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "containers.txt")
    (Invoke-Docker -Arguments @("volume", "ls") -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "volumes.txt")
    (Invoke-Docker -Arguments @("network", "ls") -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "networks.txt")
    $ids = @(Get-ContainerRows -All | ForEach-Object { $_.Id })
    if ($ids.Count -gt 0) {
        (Invoke-Docker -Arguments (@("inspect") + $ids) -AllowFailure) | Set-Content (Join-Path $script:Checkpoint "containers.inspect.json")
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
    if (-not (Get-EnvValue "ORQEVIA_DATA_VOLUME")) {
        # "prime" is kept in the adoption match only, to recover volumes from pre-rename stacks.
        $source = $rows | Where-Object { $_.Service -in @("backend", "prime") } | Select-Object -First 1
        if ($source) {
            $volume = Get-VolumeForContainer $source.Id "/data"
            if ($volume) { Set-EnvValue "ORQEVIA_DATA_VOLUME" $volume; Write-Step "Adopted the existing ORQEVIA data volume." }
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

function Assert-PersistentVolumes {
    $primeVolume = Get-EnvValue "ORQEVIA_DATA_VOLUME"
    $ollamaVolume = Get-EnvValue "OLLAMA_DATA_VOLUME"
    if (-not $primeVolume -or -not $ollamaVolume) {
        throw "ORQEVIA_DATA_VOLUME and OLLAMA_DATA_VOLUME must identify recovered, independently verified volumes. ORQEVIA will not invent recovery state."
    }
    $required = @($primeVolume, $ollamaVolume)
    $existing = @(Invoke-Docker -Arguments @("volume", "ls", "--format", "{{.Name}}"))
    foreach ($volume in $required) {
        if ($volume -notin $existing) {
            throw "Required recovered volume '$volume' does not exist. ORQEVIA will not create a blank replacement."
        }
    }
}

function Assert-NoConflictingCoreContainers {
    $legacy = @(Get-ContainerRows | Where-Object {
        # "prime" is the legacy service name, kept for detection of pre-rename stacks.
        $_.Project -ne $Project -and $_.Service -in @("backend", "prime", "ollama", "model-init")
    })
    if ($legacy.Count -eq 0) { return }
    throw "Conflicting containers require explicit owner review; nothing was stopped or removed: $($legacy.Name -join ', ')"
}

function Assert-NoConflictingEdgeContainers {
    $legacy = @(Get-ContainerRows | Where-Object {
        $_.Project -ne $Project -and $_.Service -in @("integration-gateway", "cloudflared")
    })
    if ($legacy.Count -eq 0) { return }
    throw "Conflicting edge containers require explicit owner review; nothing was stopped or removed: $($legacy.Name -join ', ')"
}

function Assert-PortAvailable {
    $rows = @(Get-ContainerRows | Where-Object { $_.Ports -match "127\.0\.0\.1:8000->|0\.0\.0\.0:8000->|\[::\]:8000->" })
    $unexpected = @($rows | Where-Object { $_.Project -ne $Project -and $_.Service -notin @("backend", "prime") })
    if ($unexpected.Count -gt 0) {
        throw "Port 8000 belongs to unrelated container $($unexpected[0].Name). ORQEVIA left it untouched."
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
    $logs = Invoke-Docker -Arguments (Get-ComposeArgs @("logs", "--tail", "80", "backend")) -AllowFailure
    throw "ORQEVIA backend did not become healthy within $TimeoutSeconds seconds.`n$($logs -join [Environment]::NewLine)"
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

    $public = Get-EnvValue "ORQEVIA_PUBLIC_URL"
    if ($public) {
        $public = $public.TrimEnd("/")
        if ((Get-HttpStatus "$public/health") -ne 200) { $failures.Add("public /health is not HTTP 200") }
        foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest")) {
            if ((Get-HttpStatus "$public$path") -ne 404) { $failures.Add("public $path is not blocked with HTTP 404") }
        }
    }
    if ($failures.Count -gt 0) { throw "ORQEVIA contract failed:`n- $($failures -join "`n- ")" }
    if (-not $Quiet) { Write-Host "ORQEVIA is healthy, local-only, approval-gated and no-actuation." -ForegroundColor Green }
}

function Resolve-TunnelMode {
    return $Tunnel.IsPresent -or ((Get-EnvValue "ORQEVIA_INTEGRATION_TOKEN") -and (Get-EnvValue "CLOUDFLARE_TUNNEL_TOKEN"))
}

function Start-OrqeviaStack([switch]$RepairOnly) {
    Assert-Docker
    Invoke-Docker -Arguments (Get-ComposeArgs @("config", "--quiet")) | Out-Null
    Adopt-PersistentVolumes
    Assert-PersistentVolumes
    Assert-PortAvailable
    Assert-NoConflictingCoreContainers
    if ($RepairOnly) { return }

    $useTunnel = [bool](Resolve-TunnelMode)
    $primeImage = Get-EnvValue "ORQEVIA_IMAGE"
    if ($primeImage) {
        Write-Step "Pulling the exact ORQEVIA image."
        Invoke-Docker -Arguments (Get-ComposeArgs @("pull", "backend")) | Out-Null
        $up = @("up", "-d", "--remove-orphans", "--no-build")
    } else {
        Write-Step "No ORQEVIA_IMAGE is pinned; building the checked-out source."
        $up = @("up", "-d", "--remove-orphans", "--build")
    }
    Write-Step "Starting the canonical ORQEVIA project."
    Invoke-Docker -Arguments (Get-ComposeArgs $up $useTunnel) | Out-Null
    Wait-ForPrime | Out-Null
    Test-PrimeContract -Quiet
    if ($useTunnel) { Assert-NoConflictingEdgeContainers }
    Write-Host "ORQEVIA READY - $LocalBase/control" -ForegroundColor Green
    if (-not $NoOpen) { Start-Process "$LocalBase/control" }
}

function Show-Status {
    Assert-Docker
    Invoke-Docker -Arguments (Get-ComposeArgs @("ps", "--all")) | Write-Host
    try { Test-PrimeContract } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
}

function Invoke-Doctor {
    Assert-Docker
    Write-Step "Validating Compose."
    Invoke-Docker -Arguments (Get-ComposeArgs @("config", "--quiet")) | Out-Null
    $rows = Get-ContainerRows -All
    # Legacy pre-rename service names are included so foreign stacks are still detected.
    $runningLegacy = @($rows | Where-Object { $_.Project -ne $Project -and $_.Status -match '^Up ' -and $_.Service -in @("backend", "prime", "ollama", "model-init", "integration-gateway", "cloudflared") })
    if ($runningLegacy.Count -gt 0) {
        Write-Host "Running legacy containers: $($runningLegacy.Name -join ', ')" -ForegroundColor Yellow
    } else { Write-Host "No running legacy (pre-rename) containers." -ForegroundColor Green }
    Show-Status
}

function Update-OrqeviaStack {
    if (-not $Image) { throw "Use -Image ghcr.io/andrewlamsingapore/orqevia:sha-<verified-commit>." }
    if ($Image -notmatch '^ghcr\.io/andrewlamsingapore/orqevia:sha-[0-9a-f]{7,40}$') {
        throw "The image must be a commit-addressable AndrewLamSingapore/orqevia GHCR image."
    }
    Save-Checkpoint | Out-Null
    Set-EnvValue "ORQEVIA_IMAGE" $Image
    Write-Step "Pinned the verified ORQEVIA image without changing secrets or volumes."
    Start-OrqeviaStack
}

function Test-SourceContract {
    if (-not (Test-Path $ComposeFile)) { throw "docker-compose.yml is missing." }
    $source = Get-Content $ComposeFile -Raw
    foreach ($required in @('name: ${COMPOSE_PROJECT_NAME:-orqevia}', '${ORQEVIA_BIND_ADDRESS:-127.0.0.1}', 'com.orqevia.managed', '${ORQEVIA_DATA_VOLUME:-orqevia-data}', '${OLLAMA_DATA_VOLUME:-orqevia-ollama-data}')) {
        if (-not $source.Contains($required)) { throw "Compose contract is missing: $required" }
    }
    Write-Host "PASS: ORQEVIA source operations contract." -ForegroundColor Green
}

Set-Location $Root
switch ($Action) {
    "start" { Start-OrqeviaStack }
    "stop" { Assert-Docker; Invoke-Docker -Arguments (Get-ComposeArgs @("down", "--remove-orphans")) | Out-Null; Write-Host "ORQEVIA stopped. Volumes retained." -ForegroundColor Yellow }
    "status" { Show-Status }
    "doctor" { Invoke-Doctor }
    "repair" { Assert-Docker; Save-Checkpoint | Out-Null; Invoke-Doctor; Write-Host "Repair is inventory-only until recovered state is independently accepted." -ForegroundColor Yellow }
    "open" { Start-Process "$LocalBase/control" }
    "update" { Update-OrqeviaStack }
    "contract" { Test-SourceContract }
}
