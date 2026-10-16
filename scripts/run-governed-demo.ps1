[CmdletBinding()]
param(
    [ValidateRange(60, 1200)]
    [int]$TimeoutSeconds = 900
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$JarvisOperator = Join-Path $PSScriptRoot "jarvis.ps1"
$LocalReasonUrl = "http://127.0.0.1:8000/api/cognitive/reason"
$PublicTraceUrl = "https://authority-engine-app.vercel.app/api/orqevia-agent-trace"
$PublicConsoleUrl = "https://authority-engine-app.vercel.app/orqevia/agents"
$Intent = "Analyze the JARVIS runtime authority architecture and identify one read-only operational integrity check for its governed agent path."
$Context = "Local verification only. Reasoning and inspection only."

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return "" }
    $line = Get-Content -LiteralPath $EnvFile -Encoding UTF8 | Where-Object {
        $_ -match ("^" + [regex]::Escape($Name) + "=")
    } | Select-Object -Last 1
    if (-not $line) { return "" }
    return ($line -split "=", 2)[1].Trim()
}

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $EnvFile) {
        foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) { [void]$lines.Add($line) }
    }
    $replacement = "$Name=$Value"
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ("^" + [regex]::Escape($Name) + "=")) {
            $lines[$i] = $replacement
            $updated = $true
            break
        }
    }
    if (-not $updated) { [void]$lines.Add($replacement) }
    [IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding($false)))
}

function New-LocalToken {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}

if (-not (Test-Path -LiteralPath $JarvisOperator)) {
    throw "Canonical JARVIS operator not found: $JarvisOperator"
}

Write-Step "Preparing local cognitive authentication"
$token = Get-EnvValue "PRIME_SPINE_TOKEN"
if (-not $token) {
    $token = New-LocalToken
    Set-EnvValue "PRIME_SPINE_TOKEN" $token
    Write-Host "Generated a private local cognitive token. It was stored only in PRIME .env." -ForegroundColor Green
} else {
    Write-Host "Existing private local cognitive token found." -ForegroundColor Green
}

Write-Step "Starting the canonical JARVIS stack"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $JarvisOperator -Action start -NoOpen -TimeoutSeconds $TimeoutSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Canonical JARVIS start operator reported a failure."
}

Write-Step "Submitting one real governed read-only task"
$body = @{
    intent = $Intent
    department = "engineering"
    context = $Context
    allow_frontier = $false
    deep = $false
} | ConvertTo-Json -Compress

$headers = @{
    Authorization = "Bearer $token"
    "Content-Type" = "application/json"
    Accept = "application/json"
}

$response = Invoke-RestMethod -Method Post -Uri $LocalReasonUrl -Headers $headers -Body $body -TimeoutSec $TimeoutSeconds
if (-not $response.ok) { throw "PRIME did not accept the governed task." }
if (-not $response.trace_id) { throw "PRIME returned no authority trace ID." }
if ($response.executed_external_action -ne $false) { throw "Governance invariant failed: external action flag was not false." }
if ($response.approval_required -ne $false) { throw "Governance invariant failed: the read-only demo unexpectedly required approval." }

$traceId = [string]$response.trace_id
$path = @($response.plan.agent_path)
$expectedDecision = if ($response.evaluation.released -eq $true) { "released" } else { "withheld" }
Write-Host ("Real PRIME trace: " + $traceId) -ForegroundColor Green
if ($path.Count -gt 0) {
    Write-Host ("Governed agent path: " + ($path -join " -> ")) -ForegroundColor Green
}
Write-Host ("Expected Stable Spine gate decision: " + $expectedDecision) -ForegroundColor Green

Write-Step "Waiting for the exact trace and release gate to reach Authority Engine"
$deadline = (Get-Date).AddSeconds(150)
$verified = $false
$verifiedGate = $null
do {
    Start-Sleep -Seconds 5
    try {
        $public = Invoke-RestMethod -Method Get -Uri $PublicTraceUrl -TimeoutSec 10
        $matches = @($public.events | Where-Object { $_.trace_id -eq $traceId })
        $terminal = @($matches | Where-Object { $_.stage -eq "reasoning" -and $_.status -in @("completed", "withheld") -and $_.gate }) | Select-Object -Last 1
        if ($public.state -eq "verified_events" -and $matches.Count -gt 0 -and $terminal) {
            if ([string]$terminal.gate.decision -ne $expectedDecision) {
                throw "Public gate decision does not match PRIME's local evaluator decision."
            }
            $verified = $true
            $verifiedGate = $terminal.gate
            Write-Host ("Authority Engine verified " + $matches.Count + " sanitized event(s) for this trace.") -ForegroundColor Green
            break
        }
    } catch {
        # Bounded retry; no secrets or request internals are printed.
    }
} while ((Get-Date) -lt $deadline)

if (-not $verified) {
    throw "The governed task completed, but its exact sanitized trace plus release-gate metadata did not reach Authority Engine within 150 seconds."
}

Write-Step "GOVERNED EXECUTION AND RELEASE GATE VERIFIED END TO END"
Write-Host "PRIME performed real local reasoning through the canonical authority path." -ForegroundColor Green
Write-Host ("Stable Spine public gate: " + $verifiedGate.decision + " at " + [math]::Round(([double]$verifiedGate.score * 100), 1) + "%") -ForegroundColor Green
if (@($verifiedGate.blocking_metrics).Count -gt 0) {
    Write-Host ("Public blocking checks: " + (@($verifiedGate.blocking_metrics) -join ", ")) -ForegroundColor Yellow
}
Write-Host "Authority Engine received only sanitized aggregate release-gate metadata." -ForegroundColor Green
Write-Host "No evaluator rationale, prompt, model answer, claim text or evidence text was published." -ForegroundColor Green
Write-Host "No external action was executed." -ForegroundColor Green
Write-Host "Opening the J Console Execution view..."
Start-Process $PublicConsoleUrl
