[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\TruthReconciler'),
    [string]$ConfigPath,
    [switch]$RegisterTask
)

$ErrorActionPreference = 'Stop'
if (-not $ConfigPath) { $ConfigPath = Join-Path $SourceRoot 'config\dell-truth-reconciler.example.json' }
if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "Configuration not found: $ConfigPath" }

if ($PSCmdlet.ShouldProcess($InstallRoot, 'Install JARVIS PRIME Dell Truth Reconciler')) {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'tools') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'scripts') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'tools\__init__.py') -Destination (Join-Path $InstallRoot 'tools\__init__.py') -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'tools\dell_truth_reconciler') -Destination (Join-Path $InstallRoot 'tools') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts\run_dell_truth_reconciler.ps1') -Destination (Join-Path $InstallRoot 'scripts\run_dell_truth_reconciler.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'scripts\github_credential_askpass.cmd') -Destination (Join-Path $InstallRoot 'scripts\github_credential_askpass.cmd') -Force
    Copy-Item -LiteralPath $ConfigPath -Destination (Join-Path $InstallRoot 'config.json') -Force
}

if ($RegisterTask) {
    $taskName = 'JARVIS PRIME Dell Truth Reconciler'
    $runner = Join-Path $InstallRoot 'scripts\run_dell_truth_reconciler.ps1'
    $argument = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -InstallRoot `"$InstallRoot`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $InstallRoot
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $periodic = New-ScheduledTaskTrigger -Daily -At '00:17'
    $periodic.Repetition.Interval = 'PT6H'
    $periodic.Repetition.Duration = 'P1D'
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon, $periodic) -Settings $settings -Description 'Independent bounded JARVIS PRIME truth reconciliation on Dell' -Force | Out-Null
}

[pscustomobject]@{
    installed = $true
    install_root = $InstallRoot
    task_registered = [bool]$RegisterTask
    config = (Join-Path $InstallRoot 'config.json')
}
