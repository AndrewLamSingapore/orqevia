[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this helper on Windows under the dedicated Dell reviewer identity.' }
$secretDir = Join-Path $env:LOCALAPPDATA 'JARVIS-DellPeer\secrets'
$secretPath = Join-Path $secretDir 'deepseek.credential.xml'
if (Test-Path -LiteralPath $secretPath) {
    throw 'A credential already exists. Preserve it; rotate deliberately outside this first-time setup helper.'
}
New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
$secret = Read-Host 'Enter DeepSeek API key locally (hidden; never paste it into chat)' -AsSecureString
if ($secret.Length -eq 0) { throw 'Empty credential rejected.' }
try {
    $credential = New-Object System.Management.Automation.PSCredential ('deepseek-dell', $secret)
    # Windows Export-Clixml encrypts this credential for this Windows user/machine.
    $credential | Export-Clixml -LiteralPath $secretPath -NoClobber
} finally {
    if ($secret) { $secret.Dispose() }
    Remove-Variable credential -ErrorAction SilentlyContinue
}
Write-Output 'Credential stored for the current Windows identity. No API call was made.'

