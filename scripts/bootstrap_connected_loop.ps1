[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$PrimePublicUrl,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CloudflareTunnelToken,

    [ValidatePattern('^https://')]
    [string]$PortalResultUrl = 'https://the-portal-ten.vercel.app/api/experiment-result'
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

$integrationToken = New-SecureToken
$portalToken = New-SecureToken

Set-DotEnvValue -EnvPath $envPath -Key 'PRIME_INTEGRATION_TOKEN' -Value $integrationToken
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_URL' -Value $PortalResultUrl
Set-DotEnvValue -EnvPath $envPath -Key 'PORTAL_RESULT_TOKEN' -Value $portalToken
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
Write-Host ''
Write-Host 'Next owner-controlled secret handoffs:'
Write-Host '1. Copy PORTAL_RESULT_TOKEN from .env into The Portal production environment.'
Write-Host '2. Store PRIME_INTEGRATION_TOKEN in the VELYQUA owner runtime; never expose it as EXPO_PUBLIC_.'
Write-Host '3. Configure the Cloudflare tunnel hostname to send traffic to http://integration-gateway:8080.'
Write-Host ''
Write-Host 'After the handoffs, start the connected stack with:'
Write-Host 'docker compose --profile tunnel up -d --build'
