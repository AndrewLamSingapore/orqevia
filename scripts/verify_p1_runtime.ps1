param(
    [Parameter(Mandatory=$true)][string]$ExpectedImageTag,
    [string]$LocalBase = "http://127.0.0.1:8000",
    [string]$Container = "",
    [string]$RollbackContainer = "prime-github-ready1-prime-1",
    [string]$PublicBase = ""
)
$ErrorActionPreference = "Stop"
if ($ExpectedImageTag -notmatch '^sha-[0-9a-f]{7}$') { throw "ExpectedImageTag must be an immutable sha-xxxxxxx tag" }
if (-not $Container) {
    $containers = @(docker ps --filter "label=com.docker.compose.project=prime" --filter "label=com.docker.compose.service=prime" --format '{{.Names}}' | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0 -or $containers.Count -ne 1) { throw "Expected exactly one running canonical PRIME container; found $($containers.Count)" }
    $Container = $containers[0]
}
$image = docker inspect --format '{{.Config.Image}}' $Container
if ($LASTEXITCODE -ne 0 -or $image -notmatch ":$([regex]::Escape($ExpectedImageTag))$") { throw "Running container is not pinned to $ExpectedImageTag" }
$mountsBefore = @(docker inspect --format '{{range .Mounts}}{{.Name}}|{{.Destination}}{{println}}{{end}}' $Container | Where-Object { $_ })
if ($LASTEXITCODE -ne 0 -or -not ($mountsBefore | Where-Object { $_ -match '\|/data$' })) { throw "PRIME persistent /data mount is missing" }
$health = Invoke-RestMethod "$LocalBase/health"
$manifest = Invoke-RestMethod "$LocalBase/api/control-surface/manifest"
$statusBefore = Invoke-RestMethod "$LocalBase/api/status"
if (-not $health.ok) { throw "PRIME health failed" }
if ($manifest.mode -ne "approval-gated" -or $manifest.boundaries.approval_executes_action -ne $false) { throw "P1 Control Surface contract failed" }
if ($manifest.boundaries.autonomous_actions -ne $false -or $manifest.boundaries.physical_actuation -ne $false) { throw "No-actuation boundary failed" }
$rollback = docker inspect --format '{{.Name}}' $RollbackContainer 2>$null
if ($LASTEXITCODE -ne 0) { throw "Rollback container is not preserved" }
docker restart $Container | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PRIME restart failed" }
$ready = $false
foreach ($attempt in 1..40) {
    try { if ((Invoke-RestMethod "$LocalBase/health" -TimeoutSec 3).ok) { $ready = $true; break } } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw "PRIME did not recover after restart" }
$mountsAfter = @(docker inspect --format '{{range .Mounts}}{{.Name}}|{{.Destination}}{{println}}{{end}}' $Container | Where-Object { $_ })
if (Compare-Object $mountsBefore $mountsAfter) { throw "Persistent mounts changed across restart" }
$statusAfter = Invoke-RestMethod "$LocalBase/api/status"
foreach ($field in @("facts", "memories", "datasets", "artifacts", "pending_approvals")) {
    if ($statusBefore.$field -ne $statusAfter.$field) { throw "Persistent status field changed across restart: $field" }
}
if ($PublicBase) {
    foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest")) {
        try { Invoke-WebRequest "$PublicBase$path" -UseBasicParsing -ErrorAction Stop | Out-Null; throw "Public path unexpectedly reachable: $path" }
        catch { if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw } }
    }
}
[ordered]@{ ok=$true; image=$image; container=$Container; health="passed"; control_surface="passed"; persistence="passed"; mounts=$mountsAfter; public_block=if($PublicBase){"passed"}else{"not_configured"}; rollback=$RollbackContainer; volumes_deleted=$false } | ConvertTo-Json
