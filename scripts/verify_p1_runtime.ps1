param(
    [Parameter(Mandatory=$true)][string]$ExpectedImageTag,
    [string]$LocalBase = "http://127.0.0.1:8000",
    [string]$Container = "prime-main-prime-1",
    [string]$RollbackContainer = "prime-github-ready1-prime-1",
    [string]$PublicBase = ""
)
$ErrorActionPreference = "Stop"
if ($ExpectedImageTag -notmatch '^sha-[0-9a-f]{7}$') { throw "ExpectedImageTag must be an immutable sha-xxxxxxx tag" }
$image = docker inspect --format '{{.Config.Image}}' $Container
if ($LASTEXITCODE -ne 0 -or $image -notmatch ":$([regex]::Escape($ExpectedImageTag))$") { throw "Running container is not pinned to $ExpectedImageTag" }
$health = Invoke-RestMethod "$LocalBase/health"
$manifest = Invoke-RestMethod "$LocalBase/api/control-surface/manifest"
if (-not $health.ok) { throw "PRIME health failed" }
if ($manifest.mode -ne "approval-gated" -or $manifest.boundaries.approval_executes_action -ne $false) { throw "P1 Control Surface contract failed" }
if ($manifest.boundaries.autonomous_actions -ne $false -or $manifest.boundaries.physical_actuation -ne $false) { throw "No-actuation boundary failed" }
$rollback = docker inspect --format '{{.Name}}' $RollbackContainer 2>$null
if ($LASTEXITCODE -ne 0) { throw "Rollback container is not preserved" }
if ($PublicBase) {
    foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest")) {
        try { Invoke-WebRequest "$PublicBase$path" -UseBasicParsing -ErrorAction Stop | Out-Null; throw "Public path unexpectedly reachable: $path" }
        catch { if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw } }
    }
}
[ordered]@{ ok=$true; image=$image; container=$Container; health="passed"; control_surface="passed"; public_block=if($PublicBase){"passed"}else{"not_run"}; rollback=$RollbackContainer; volumes_mutated=$false } | ConvertTo-Json
