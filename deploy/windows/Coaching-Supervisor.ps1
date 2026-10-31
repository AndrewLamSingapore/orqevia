# Owner-resumed supervisor. An explicit AUTOSTART-DISABLED marker is honored.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$ownerPauseMarker='C:\Users\Admin\Documents\ABEX\operations\pause-resume-20261021\PAUSE.flag'
$startupDisabledMarker='C:\Users\Admin\Documents\ABEX\operations\AUTOSTART-DISABLED'
if((Test-Path -LiteralPath $ownerPauseMarker) -or (Test-Path -LiteralPath $startupDisabledMarker)){exit 0}
$root=$PSScriptRoot
$docker='C:/Program Files/Docker/Docker/resources/bin/docker.exe'
$python='C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$created=$false
$mutex=New-Object Threading.Mutex($true,'Local\ABEX-ORQEVIA-Coaching-Supervisor',[ref]$created)
if(-not $created){exit 0}
$journal=Join-Path $root 'supervisor-events.jsonl'
$retryFile=Join-Path $root 'supervisor-retries.json'
function Record([string]$state,[object]$details){
 if((Test-Path $journal) -and (Get-Item $journal).Length -gt 2097152){
  Move-Item -LiteralPath $journal -Destination (Join-Path $root ('supervisor-events-'+[datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'.jsonl'))
 }
 @{at_utc=[datetime]::UtcNow.ToString('o');state=$state;details=$details;pid=$PID}|ConvertTo-Json -Compress -Depth 5|Add-Content -LiteralPath $journal
}
try{
 Record 'STARTED' @{display_dependency=$false;interactive_codex_dependency=$false;collector_dependency='SEPARATE_PERMANENT_LOOP';restart_limit_per_hour=$null;recovery_spacing_seconds=30}
 while($true){
  try{
   $raw=& $docker inspect orqevia-coaching-coaching-1 2>$null
   if($LASTEXITCODE -ne 0){throw 'EXISTING_DOCKER_ENGINE_OR_CONTROLLER_UNAVAILABLE'}
   $c=@($raw|ConvertFrom-Json)[0]
   $revision=$c.Config.Labels.'org.opencontainers.image.revision'
   $pin=Get-Content (Join-Path $root 'supervisor-pin.json') -Raw|ConvertFrom-Json
   if($revision -ne $pin.implementation_revision){throw 'CONTROLLER_REVISION_CHANGED_REVIEW_SUPERVISOR_PIN'}
   # Owner supersession, 28 October: an explicit background pause persists.
   # The existing compute DB is authoritative. This compatibility marker is
   # never automatically removed, archived or cleared by supervision.
   try{
    $admissionProbe=@'
import json,pathlib,sqlite3
paused=True;generation=None
try:
 with sqlite3.connect('file:/data/compute-queue.db?mode=ro',uri=True,timeout=2) as db:
  db.execute('PRAGMA query_only=ON')
  row=db.execute('SELECT paused,generation FROM compute_background_admission WHERE id=1').fetchone()
  if row is not None:paused=bool(row[0]);generation=row[1]
except sqlite3.Error:pass
if paused:pathlib.Path('/data/coaching.pause').touch(exist_ok=True)
print(json.dumps({'paused':paused,'generation':generation,'legacy_marker_present':pathlib.Path('/data/coaching.pause').exists()}))
'@
    $admissionRaw=$admissionProbe | & $docker exec -i orqevia-coaching-coaching-1 python -B - 2>$null
    if($LASTEXITCODE -ne 0){throw 'BACKGROUND_ADMISSION_READ_UNAVAILABLE_PRESERVING_PAUSE'}
    $admission=($admissionRaw -join '')|ConvertFrom-Json
    if($admission.paused -or $admission.legacy_marker_present){
     Record 'BACKGROUND_ADMISSION_PAUSED' @{generation=$admission.generation;automatic_resume=$false}
    }
   }catch{Record 'ADMISSION_STATE_UNKNOWN' @{background_resume=$false}}
   $health=$c.State.Health.Status
   if($c.State.Status -ne 'running' -or $health -eq 'unhealthy'){
    $retries=@()
    if(Test-Path $retryFile){$retries=@(Get-Content $retryFile -Raw|ConvertFrom-Json)}
    $retries=@($retries|Where-Object {([datetime]$_) -gt [datetime]::UtcNow.AddHours(-1)})
    & {
     $retries+=([datetime]::UtcNow.ToString('o'));ConvertTo-Json -InputObject $retries|Set-Content -LiteralPath $retryFile
     if($c.State.Status -eq 'running'){& $docker restart --time 20 orqevia-coaching-coaching-1 2>$null|Out-Null}
     else{& $docker start orqevia-coaching-coaching-1 2>$null|Out-Null}
     Record 'RECOVERY_ATTEMPT' @{exit_code=$LASTEXITCODE;prior_state=$c.State.Status;prior_health=$health}
    }
   }
   else{Record 'HEARTBEAT' @{controller_id=$c.Id;health=$health;started_at=$c.State.StartedAt}}
  }catch{Record 'DEPENDENCY_UNAVAILABLE' @{reason=$_.Exception.Message}}
  Start-Sleep -Seconds 30
 }
}finally{$mutex.ReleaseMutex();$mutex.Dispose()}
