param(
    [Parameter(Mandatory=$true)][string]$ExpectedImageTag,
    [string]$LocalBase = "http://127.0.0.1:8000",
    [string]$Container = "",
    [string]$RollbackImage = "",
    [string]$LegacyRollbackContainer = "",
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
# Rollback readiness.
#
# This check used to require a standing container from the superseded
# `prime-github-ready1` stack. That topology no longer exists: the stack was
# replaced by the canonical `prime` project, and its stopped containers were
# removed by the 2026-09-23 clean-up. The old assertion therefore failed
# permanently while a perfectly good rollback path was available.
#
# PRIME rollback is image-based and non-destructive: replace the container from
# an immutable, already-present image while the external `prime-data` volume is
# left untouched. That is what the deployment contract calls "bounded rollback"
# ("data preservation"), so it is what readiness is verified against.
$rollbackCandidates = @(docker images --format '{{.Repository}}:{{.Tag}}' |
    Where-Object { $_ -match '^ghcr\.io/andrewlamsingapore/prime:sha-[0-9a-f]{7}$' } |
    Where-Object { $_ -notmatch [regex]::Escape($ExpectedImageTag) } | Sort-Object)
if (-not $RollbackImage) {
    if ($rollbackCandidates.Count -eq 0) { throw "No rollback image available: expected at least one other immutable prime sha- image present locally" }
    $RollbackImage = $rollbackCandidates[0]
}
if ($RollbackImage -notmatch '^ghcr\.io/andrewlamsingapore/prime:sha-[0-9a-f]{7}$') { throw "RollbackImage must be an immutable prime sha-xxxxxxx image reference" }
if ($RollbackImage -match [regex]::Escape($ExpectedImageTag)) { throw "RollbackImage must differ from the running image tag" }
$rollbackImageId = docker image inspect --format '{{.Id}}' $RollbackImage 2>$null
if ($LASTEXITCODE -ne 0 -or -not $rollbackImageId) { throw "Rollback image is not present locally: $RollbackImage" }
$runningImageId = docker image inspect --format '{{.Id}}' $image 2>$null
if (-not $runningImageId) { throw "Running image is not present locally, so the container could not be recreated: $image" }
foreach ($volume in @("prime-data")) {
    if ($volume -notin @(docker volume ls --format '{{.Name}}')) { throw "Rollback would lose data: persistent volume '$volume' is missing" }
}
if ($LegacyRollbackContainer) {
    $legacy = docker inspect --format '{{.Name}}' $LegacyRollbackContainer 2>$null
    if ($LASTEXITCODE -ne 0) { throw "LegacyRollbackContainer was supplied but is not preserved" }
}
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
[ordered]@{ ok=$true; image=$image; container=$Container; health="passed"; control_surface="passed"; persistence="passed"; mounts=$mountsAfter; public_block=if($PublicBase){"passed"}else{"not_configured"}; rollback_mode="image"; rollback_image=$RollbackImage; rollback_image_id=$rollbackImageId; rollback_candidates=$rollbackCandidates; volumes_deleted=$false } | ConvertTo-Json
