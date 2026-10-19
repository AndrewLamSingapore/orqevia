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

    [switch]$InitializeNewTrustEpoch
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
    throw '.env is missing. Recover the authentic configuration first; this script will not create replacement state.'
}

$integrationToken = Get-DotEnvValue -EnvPath $envPath -Key 'ORQEVIA_INTEGRATION_TOKEN'
$portalToken = Get-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_TOKEN'
$portalPrimeToken = Get-DotEnvValue -EnvPath $envPath -Key 'PORTAL_ORQEVIA_TOKEN'

if ($InitializeNewTrustEpoch) {
    $integrationToken = New-SecureToken
    $portalToken = New-SecureToken
    $portalPrimeToken = New-SecureToken
} elseif ([string]::IsNullOrWhiteSpace($integrationToken) -or [string]::IsNullOrWhiteSpace($portalToken) -or [string]::IsNullOrWhiteSpace($portalPrimeToken)) {
    throw 'Authentic application credentials are missing. Recover them, or explicitly authorize -InitializeNewTrustEpoch as a new trust relationship.'
}

Set-DotEnvValue -EnvPath $envPath -Key 'ORQEVIA_INTEGRATION_TOKEN' -Value $integrationToken
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_URL' -Value $PortalResultUrl
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_TOKEN' -Value $portalToken
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_ORQEVIA_TOKEN' -Value $portalPrimeToken
Set-DotEnvValue -EnvPath $envPath -Key 'CLOUDFLARE_TUNNEL_TOKEN' -Value $CloudflareTunnelToken
Set-DotEnvValue -EnvPath $envPath -Key 'ORQEVIA_PUBLIC_URL' -Value $PrimePublicUrl.TrimEnd('/')

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
if ($InitializeNewTrustEpoch) {
    Write-Host 'A NEW trust epoch was explicitly initialized; this is not recovered historical state.'
}
else {
    Write-Host 'Existing non-empty application tokens were preserved.'
}
Write-Host ''
Write-Host 'Next owner-controlled secret handoffs:'
Write-Host '1. Configure The Portal with both PORTAL tokens, plus ORQEVIA_BASE_URL=<ORQEVIA_PUBLIC_URL> and ORQEVIA_INTEGRATION_TOKEN.'
Write-Host '2. Configure the VELYQUA server bridge with ORQEVIA_BASE_URL=<ORQEVIA_PUBLIC_URL>, ORQEVIA_INTEGRATION_TOKEN and the exact Supabase owner user id.'
Write-Host '3. Set only EXPO_PUBLIC_VELYQUA_BRIDGE_URL=https://velyqua.vercel.app in the VELYQUA public build.'
Write-Host '4. Keep jarvis.lamjarvis.com routed to the HTTPS Interface with origin CA verification and Owner Access JWT enforcement.'
Write-Host '   The legacy integration-gateway is API-only and cannot serve the JARVIS PWA; it needs a separate reviewed route if retained.'
Write-Host ''
Write-Host 'This bootstrap only stages credentials. Do not start the whole tunnel profile from this script.'
Write-Host 'After origin, Access, rollback, and candidate acceptance gates pass, start only the reviewed cloudflared service with its CA mount.'
