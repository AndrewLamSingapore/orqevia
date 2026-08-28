[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$PrimePublicUrl,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CloudflareTunnelToken,

    [ValidatePattern('^https://')]
    [string]$PortalResultUrl = 'https://the-portal-ten.vercel.app/api/experiment-result',

    [switch]$RotateTokens
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-SecureToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return ''
    }
    $prefix = $Key + '='
    $line = Get-Content -LiteralPath $EnvPath |
        Where-Object { $_.StartsWith($prefix) } |
        Select-Object -Last 1
    if ($null -eq $line) {
        return ''
    }
    return $line.Substring($prefix.Length).Trim()
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    $lines = if (Test-Path -LiteralPath $EnvPath) {
        @(Get-Content -LiteralPath $EnvPath)
    }
    else {
        @()
    }

    $pattern = '^' + [regex]::Escape($Key) + '='
    $found = $false
    $updated = @(
        foreach ($line in $lines) {
            if ($line -match $pattern) {
                $found = $true
                "$Key=$Value"
            }
            else {
                $line
            }
        }
    )
    if (-not $found) {
        $updated += "$Key=$Value"
    }

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, [string[]]$updated, $utf8)
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envPath = Join-Path $projectRoot '.env'
$examplePath = Join-Path $projectRoot '.env.example'

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$integrationToken = Get-DotEnvValue -EnvPath $envPath -Key 'PRIME_INTEGRATION_TOKEN'
$portalToken = Get-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_TOKEN'
$portalPrimeToken = Get-DotEnvValue -EnvPath $envPath -Key 'PORTAL_PRIME_TOKEN'

if ($RotateTokens -or [string]::IsNullOrWhiteSpace($integrationToken)) {
    $integrationToken = New-SecureToken
}
if ($RotateTokens -or [string]::IsNullOrWhiteSpace($portalToken)) {
    $portalToken = New-SecureToken
}
if ($RotateTokens -or [string]::IsNullOrWhiteSpace($portalPrimeToken)) {
    $portalPrimeToken = New-SecureToken
}

Set-DotEnvValue -EnvPath $envPath -Key 'PRIME_INTEGRATION_TOKEN' -Value $integrationToken
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_URL' -Value $PortalResultUrl
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_TOKEN' -Value $portalToken
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_PRIME_TOKEN' -Value $portalPrimeToken
Set-DotEnvValue -EnvPath $envPath -Key 'CLOUDFLARE_TUNNEL_TOKEN' -Value $CloudflareTunnelToken
Set-DotEnvValue -EnvPath $envPath -Key 'PRIME_PUBLIC_URL' -Value $PrimePublicUrl.TrimEnd('/')

Push-Location $projectRoot
try {
    docker compose --profile tunnel config --quiet
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Connected-loop configuration is valid and stored in .env.'
Write-Host 'The populated .env is intentionally excluded from Git.'
if ($RotateTokens) {
    Write-Host 'Application tokens were rotated; update both remote server environments before testing.'
}
else {
    Write-Host 'Existing non-empty application tokens were preserved.'
}
Write-Host ''
Write-Host 'Next owner-controlled secret handoffs:'
Write-Host '1. Configure The Portal with both PORTAL tokens, plus PRIME_BASE_URL=<PRIME_PUBLIC_URL> and PRIME_INTEGRATION_TOKEN.'
Write-Host '2. Configure the VELYQUA server bridge with PRIME_BASE_URL=<PRIME_PUBLIC_URL>, PRIME_INTEGRATION_TOKEN and the exact Supabase owner user id.'
Write-Host '3. Set only EXPO_PUBLIC_VELYQUA_BRIDGE_URL=https://velyqua.vercel.app in the VELYQUA public build.'
Write-Host '4. Configure the Cloudflare tunnel hostname to send traffic to http://integration-gateway:8080.'
Write-Host ''
Write-Host 'After the handoffs, start the connected stack with:'
Write-Host 'docker compose --profile tunnel up -d --build'
