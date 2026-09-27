param(
    [string]$LogRoot = "C:\Users\Admin\Documents\ABEX\recovery-records\evidence\survival-startup"
)

$ErrorActionPreference = "Stop"

$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$dockerCli = "C:\Program Files\Docker\Docker\DockerCli.exe"
$probeModule = Join-Path $PSScriptRoot "docker-engine-probe.ps1"
$logPath = Join-Path $LogRoot "latest.log"
$mutex = New-Object System.Threading.Mutex($false, "Local\ABEX-Survival-Startup")

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

function Write-StartupLog([string]$message) {
    "$(Get-Date -Format o) $message" | Add-Content -LiteralPath $logPath
}

if (-not (Test-Path -LiteralPath $probeModule -PathType Leaf)) {
    Write-StartupLog "FAIL bounded Docker probe module is missing"
    $mutex.Dispose()
    exit 2
}
. $probeModule

if (-not $mutex.WaitOne(0)) {
    Write-StartupLog "SKIP another startup guard instance is active"
    $mutex.Dispose()
    exit 0
}

try {
    Write-StartupLog "BEGIN bounded Docker/PRIME survival startup"

    if (Test-DockerEngine) {
        Write-StartupLog "OK Docker engine was already healthy"
        exit 0
    }

    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        Write-StartupLog "FAIL Docker Desktop executable is missing"
        exit 2
    }

    if (Test-Path -LiteralPath $dockerCli) {
        & $dockerCli -Shutdown *> $null
        Start-Sleep -Seconds 3
    }

    Get-Process -Name "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $socketDirs = @(
        "C:\Users\Admin\AppData\Local\Docker\run",
        "C:\Users\Admin\AppData\Local\docker-secrets-engine"
    )
    foreach ($source in $socketDirs) {
        if (Test-Path -LiteralPath $source) {
            $item = Get-Item -LiteralPath $source -Force
            if (-not $item.PSIsContainer -or
                ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
                [System.IO.Path]::GetFullPath($item.FullName) -ne $source) {
                throw "Refusing to preserve an unexpected socket-directory target: $source"
            }
            $leaf = Split-Path -Leaf $source
            $destinationName = "$leaf.survival-quarantine-$stamp"
            $destination = Join-Path (Split-Path -Parent $source) $destinationName
            if (Test-Path -LiteralPath $destination) {
                throw "Refusing to overwrite preserved socket evidence: $destination"
            }
            Rename-Item -LiteralPath $source -NewName $destinationName
            Write-StartupLog "PRESERVED ephemeral socket directory $source as $destinationName"
        }
    }

    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    Write-StartupLog "START Docker Desktop requested once"

    $deadline = (Get-Date).AddSeconds(90)
    $healthy = $false
    do {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) {
            $healthy = $true
            break
        }
    } while ((Get-Date) -lt $deadline)

    if (-not $healthy) {
        Write-StartupLog "FAIL Docker engine did not become healthy within 90 seconds; no retry will be attempted"
        exit 3
    }

    Write-StartupLog "OK Docker engine healthy"
    $requiredContainers = @(
        "prime-epoch-20260919-prime-1",
        "prime-epoch-20260919-interface-1",
        "prime-epoch-20260919-ollama-1"
    )
    $primeReady = $false
    $containerDeadline = (Get-Date).AddSeconds(60)
    do {
        $states = @{}
        foreach ($name in $requiredContainers) {
            $state = docker inspect $name --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2>$null
            $states[$name] = $state
        }
        if (@($states.Values | Where-Object { $_ -ne "healthy" }).Count -eq 0) {
            try {
                $health = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 5
                if ($health.ok) {
                    $primeReady = $true
                    break
                }
            } catch {}
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $containerDeadline)

    foreach ($name in $requiredContainers) {
        Write-StartupLog "CONTAINER $name=$($states[$name])"
    }
    if ($primeReady) {
        Write-StartupLog "OK PRIME health verified"
    } else {
        Write-StartupLog "WARN Docker recovered but PRIME readiness was not verified within 60 seconds"
        exit 4
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
