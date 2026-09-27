[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $PacketPath,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[a-fA-F0-9]{64}$')] [string] $InputSHA256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^([a-fA-F0-9]{40}|[a-fA-F0-9]{64})$')] [string] $CandidateSHA,
    [string] $OutputDirectory,
    [switch] $Send
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run on physical Dell Windows.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python is not installed or not on PATH.' }
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $env:LOCALAPPDATA 'JARVIS-DellPeer\advisory-output'
}
$pythonArguments = @(
    '-I',
    (Join-Path $PSScriptRoot 'deepseek_review.py'),
    '--input', $PacketPath,
    '--input-sha256', $InputSHA256,
    '--candidate-sha', $CandidateSHA,
    '--output-dir', $OutputDirectory
)
if (-not $Send) {
    # Dry-run does not decrypt a secret or invoke a network-capable Codex session.
    & python @pythonArguments
    exit $LASTEXITCODE
}
$secretPath = Join-Path $env:LOCALAPPDATA 'JARVIS-DellPeer\secrets\deepseek.credential.xml'
if (-not (Test-Path -LiteralPath $secretPath)) { throw 'Run Set-DeepSeekCredential.ps1 locally first.' }
$priorKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'Process')
try {
    $credential = Import-Clixml -LiteralPath $secretPath
    if ($credential -isnot [System.Management.Automation.PSCredential]) { throw 'Unexpected credential format.' }
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $credential.GetNetworkCredential().Password, 'Process')
    $pythonArguments += '--send'
    & python @pythonArguments
    $reviewExit = $LASTEXITCODE
} finally {
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $priorKey, 'Process')
    Remove-Variable credential, priorKey -ErrorAction SilentlyContinue
}
exit $reviewExit
