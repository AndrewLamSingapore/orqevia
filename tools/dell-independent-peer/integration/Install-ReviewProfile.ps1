[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
# Only this named profile is installed. Existing defaults and credentials are not read.
$codexConfigDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$source = Join-Path $PSScriptRoot 'dell-deepseek.config.toml'
$destination = Join-Path $codexConfigDir 'dell-deepseek.config.toml'
if (Test-Path -LiteralPath $destination) {
    throw 'Named profile already exists; preserve and inspect it before making a versioned replacement.'
}
New-Item -ItemType Directory -Path $codexConfigDir -Force | Out-Null
# CreateNew also refuses overwriting when another process wins the race.
$stream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = [IO.File]::ReadAllBytes($source)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
} finally {
    $stream.Dispose()
}
Write-Output ('PROFILE_PREPARED: ' + $destination)
Write-Output 'API connectivity and native Windows sandbox remain unverified.'
Write-Output 'NATIVE_LAUNCH_BLOCKED: this profile does not remove inherited MCP or hook authority.'
