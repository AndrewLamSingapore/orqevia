[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\DellNodeSync'),
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [switch]$RegisterTask,
    [switch]$AllowRetiredApparatus
)

# The SSOT synchronizer apparatus is retired: STATUS.md is the only current status
# authority. Installation is refused by default so a dormant authority mechanism
# cannot be silently reactivated. Historical code is kept, not deleted.
if (-not $AllowRetiredApparatus) {
    Write-Error 'The Dell Node Synchronizer apparatus is retired (superseded by STATUS.md on 22 September 2026). Nothing was installed or scheduled. Re-run with -AllowRetiredApparatus only if Lam explicitly revives this historical tool.'
    exit 64
}

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "Configuration not found: $ConfigPath" }

if ($PSCmdlet.ShouldProcess($InstallRoot, 'Install JARVIS Dell Node Synchronizer')) {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'tools') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'scripts') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'tools\__init__.py') -Destination (Join-Path $InstallRoot 'tools\__init__.py') -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'tools\dell_node_sync') -Destination (Join-Path $InstallRoot 'tools') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts\run_dell_node_sync.ps1') -Destination (Join-Path $InstallRoot 'scripts\run_dell_node_sync.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts\github_credential_askpass.cmd') -Destination (Join-Path $InstallRoot 'scripts\github_credential_askpass.cmd') -Force
    Copy-Item -LiteralPath $ConfigPath -Destination (Join-Path $InstallRoot 'config.json') -Force
}

if ($RegisterTask) {
    $taskName = 'JARVIS PRIME Dell Node Synchronizer'
    $runner = Join-Path $InstallRoot 'scripts\run_dell_node_sync.ps1'
    $argument = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -InstallRoot `"$InstallRoot`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $InstallRoot -ErrorAction Stop
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME -ErrorAction Stop
    $periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 30) `
        -RepetitionDuration (New-TimeSpan -Days 3650) -ErrorAction Stop
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -ErrorAction Stop
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon, $periodic) -Settings $settings -Description 'Bounded validated Dell-to-GitHub synchronization; STATUS.md owns current status' -Force -ErrorAction Stop | Out-Null
}

[pscustomobject]@{
    installed = $true
    install_root = $InstallRoot
    task_registered = [bool]$RegisterTask
    config = (Join-Path $InstallRoot 'config.json')
}
