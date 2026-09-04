param(
    [Parameter(Mandatory = $false)]
    [string]$SecretFile = (Join-Path $HOME "Downloads\JARVIS_PRIME_PUBLIC_TRACE_PRIVATE.env"),
    [switch]$NoRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvPath = Join-Path $RepoRoot ".env"
$ComposePath = Join-Path $RepoRoot "docker-compose.yml"
$RelayUrl = "https://bksyjvppcwfgwoelnyvp.supabase.co/functions/v1/jarvis-trace-relay"
$PublisherId = "prime-dell-1"
$PrimeImage = "ghcr.io/andrewlamsingapore/prime:latest"

function Read-EnvMap([string]$Path) {
    $map = [ordered]@{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $parts = $trimmed.Split('=', 2)
        $map[$parts[0].Trim()] = $parts[1]
    }
    return $map
}

function Set-EnvValues([string]$Path, [hashtable]$Values) {
    $lines = if (Test-Path $Path) { [System.Collections.Generic.List[string]](Get-Content -LiteralPath $Path -Encoding UTF8) } else { [System.Collections.Generic.List[string]]::new() }
    foreach ($key in $Values.Keys) {
        $replacement = "$key=$($Values[$key])"
        $found = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^\s*$([regex]::Escape($key))=") {
                $lines[$i] = $replacement
                $found = $true
                break
            }
        }
        if (-not $found) { $lines.Add($replacement) }
    }
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllLines($tmp, $lines, [System.Text.UTF8Encoding]::new($false))
    Move-Item -Force -LiteralPath $tmp -Destination $Path
}

function Ensure-DockerVolume([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]+$') {
        throw "Unsafe Docker volume name: $Name"
    }
    Write-Host "Ensuring required persistent Docker volume: $Name"
    # `docker volume create` is deliberately used without an inspect probe.
    # It is idempotent: a missing volume is created, while an existing one is
    # returned unchanged. This also avoids Windows PowerShell treating the
    # stderr from `docker volume inspect <missing>` as a terminating error.
    $created = docker volume create $Name
    if ($LASTEXITCODE -ne 0 -or -not $created) {
        throw "Unable to ensure required Docker volume: $Name"
    }
}

if (-not (Test-Path $ComposePath)) {
    throw "Canonical docker-compose.yml not found: $ComposePath"
}

$existing = Read-EnvMap $EnvPath
$secret = ""
if (Test-Path $SecretFile) {
    $private = Read-EnvMap $SecretFile
    if ($private.Contains('PRIME_PUBLIC_TRACE_SECRET')) {
        $secret = [string]$private['PRIME_PUBLIC_TRACE_SECRET']
    }
}
if (-not $secret -and $existing.Contains('PRIME_PUBLIC_TRACE_SECRET')) {
    $secret = [string]$existing['PRIME_PUBLIC_TRACE_SECRET']
}
if ($secret.Length -lt 32) {
    throw "PRIME_PUBLIC_TRACE_SECRET is missing or too short."
}

$values = @{
    PRIME_IMAGE = $PrimeImage
    PRIME_PUBLIC_AGENT_TRACE = "0"
    PRIME_PUBLIC_TRACE_RELAY_URL = $RelayUrl
    PRIME_PUBLIC_TRACE_PUBLISHER_ID = $PublisherId
    PRIME_PUBLIC_TRACE_SECRET = $secret
    PRIME_PUBLIC_TRACE_INTERVAL_SECONDS = "15"
    PRIME_QUEUE_CONCURRENCY = "2"
}
Set-EnvValues -Path $EnvPath -Values $values
if (Test-Path $SecretFile) {
    Remove-Item -Force -LiteralPath $SecretFile
    Write-Host "JARVIS public-safe trace configuration written to .env; the one-time private bootstrap file was removed."
} else {
    Write-Host "JARVIS public-safe trace configuration verified from the existing private .env."
}

if ($NoRestart) {
    Write-Host "Configuration complete. Restart skipped by request."
    exit 0
}

$effective = Read-EnvMap $EnvPath
$primeDataVolume = if ($effective.Contains('PRIME_DATA_VOLUME') -and $effective['PRIME_DATA_VOLUME']) { [string]$effective['PRIME_DATA_VOLUME'] } else { 'prime-data' }
$ollamaDataVolume = if ($effective.Contains('OLLAMA_DATA_VOLUME') -and $effective['OLLAMA_DATA_VOLUME']) { [string]$effective['OLLAMA_DATA_VOLUME'] } else { 'prime-ollama-data' }

Push-Location $RepoRoot
try {
    Ensure-DockerVolume $primeDataVolume
    Ensure-DockerVolume $ollamaDataVolume

    docker compose -f $ComposePath config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose validation failed." }

    docker compose -f $ComposePath pull prime
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to pull the verified PRIME image. Confirm Docker is authenticated to GHCR, then rerun this command."
    }

    docker compose -f $ComposePath up -d --no-deps --force-recreate prime
    if ($LASTEXITCODE -ne 0) { throw "PRIME container recreation failed." }

    $containerId = (docker compose -f $ComposePath ps -q prime 2>$null).Trim()
    if (-not $containerId) { throw "PRIME container ID could not be resolved after recreation." }

    $deadline = (Get-Date).AddMinutes(3)
    $health = "unknown"
    do {
        Start-Sleep -Seconds 3
        $health = (docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId 2>$null).Trim()
        if ($health -eq 'healthy') { break }
    } while ((Get-Date) -lt $deadline)
    if ($health -ne 'healthy') { throw "PRIME did not become healthy within 3 minutes. Current state: $health" }

    $relayDeadline = (Get-Date).AddSeconds(60)
    $published = $false
    do {
        Start-Sleep -Seconds 5
        try {
            $snapshot = Invoke-RestMethod -Uri $RelayUrl -Method Get -TimeoutSec 10
            if ($snapshot.source_generated_at) {
                $published = $true
                break
            }
        } catch {
            # Keep waiting until the bounded deadline; do not print request internals.
        }
    } while ((Get-Date) -lt $relayDeadline)

    if (-not $published) {
        throw "PRIME is healthy but the signed public trace heartbeat was not observed within 60 seconds. Check 'docker compose logs prime'."
    }

    Write-Host "JARVIS PRIME is healthy and the signed sanitized trace relay is active."
    Write-Host "Public read: https://authority-engine-app.vercel.app/api/jarvis-agent-trace"
} finally {
    Pop-Location
}
