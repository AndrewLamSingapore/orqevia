[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\DellNodeSync'),
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [switch]$RegisterTask
)

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
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $InstallRoot
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $periodic = New-ScheduledTaskTrigger -Daily -At '00:11'
    $periodic.Repetition.Interval = 'PT30M'
    $periodic.Repetition.Duration = 'P1D'
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon, $periodic) -Settings $settings -Description 'Bounded validated Dell-to-GitHub synchronization under PRIME SSOT authority' -Force | Out-Null
}

[pscustomobject]@{
    installed = $true
    install_root = $InstallRoot
    task_registered = [bool]$RegisterTask
    config = (Join-Path $InstallRoot 'config.json')
}
