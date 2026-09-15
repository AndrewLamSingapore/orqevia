[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [switch]$NoFetch
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $InstallRoot 'config.json'
$statePath = Join-Path $InstallRoot 'state'
$eventsPath = Join-Path $statePath 'events.jsonl'
$statusPath = Join-Path $statePath 'status.json'
$lockPath = Join-Path $statePath 'reconciler.lock'
New-Item -ItemType Directory -Path $statePath -Force | Out-Null

$lock = $null
try {
    $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch [System.IO.IOException] {
    exit 0
}

try {
    $askPass = Join-Path $InstallRoot 'scripts\github_credential_askpass.cmd'
    if (Test-Path -LiteralPath $askPass) {
        $env:GIT_ASKPASS = $askPass
        $env:GIT_TERMINAL_PROMPT = '0'
    }
    $pythonCandidates = @(
        (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $pythonCandidates) { throw 'No supported Python runtime is available.' }
    $python = $pythonCandidates[0]
    $arguments = @('-m', 'tools.dell_truth_reconciler', '--config', $configPath, '--output', $statusPath, '--repair')
    if (-not $NoFetch) { $arguments += '--fetch' }
    $started = (Get-Date).ToUniversalTime().ToString('o')
    & $python @arguments | Out-Null
    $exitCode = $LASTEXITCODE
    $event = [ordered]@{ timestamp = $started; event = 'reconciliation_completed'; exit_code = $exitCode; status_path = $statusPath }
    Add-Content -LiteralPath $eventsPath -Value ($event | ConvertTo-Json -Compress) -Encoding utf8
    exit $exitCode
} catch {
    $event = [ordered]@{ timestamp = (Get-Date).ToUniversalTime().ToString('o'); event = 'reconciliation_failed'; error_type = $_.Exception.GetType().Name }
    Add-Content -LiteralPath $eventsPath -Value ($event | ConvertTo-Json -Compress) -Encoding utf8
    exit 3
} finally {
    if ($lock) { $lock.Dispose() }
}
