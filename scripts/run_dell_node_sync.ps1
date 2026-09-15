[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\DellNodeSync'),
    [switch]$NoFetch
)

$ErrorActionPreference = 'Stop'
$config = Join-Path $InstallRoot 'config.json'
$status = Join-Path $InstallRoot 'state\status.json'
$events = Join-Path $InstallRoot 'state\runner-events.jsonl'
New-Item -ItemType Directory -Path (Split-Path -Parent $events) -Force | Out-Null

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
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$InstallRoot;$env:PYTHONPATH" } else { $InstallRoot }
    $arguments = @('-m', 'tools.dell_node_sync', '--config', $config, '--output', $status)
    if ($NoFetch) { $arguments += '--no-fetch' }
    & @($pythonCandidates)[0] @arguments | Out-Null
    $exitCode = $LASTEXITCODE
    Add-Content -LiteralPath $events -Encoding utf8 -Value (([ordered]@{
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        event = 'dell_node_sync_completed'
        exit_code = $exitCode
    }) | ConvertTo-Json -Compress)
    exit $exitCode
} catch {
    Add-Content -LiteralPath $events -Encoding utf8 -Value (([ordered]@{
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        event = 'dell_node_sync_failed'
        error_type = $_.Exception.GetType().Name
    }) | ConvertTo-Json -Compress)
    exit 3
}
