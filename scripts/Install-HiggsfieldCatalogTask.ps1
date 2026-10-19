[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'ORQEVIA-Higgsfield-Catalog'
$publisher = 'C:\Users\Admin\Documents\ABEX\runtime\orqevia-epoch-20261016\scripts\Publish-HiggsfieldCatalog.ps1'
if (-not (Test-Path -LiteralPath $publisher -PathType Leaf)) {
    throw 'Higgsfield catalog publisher is missing'
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File `"$publisher`"" `
    -WorkingDirectory 'C:\Users\Admin\Documents\ABEX'
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
    -RepetitionInterval (New-TimeSpan -Hours 6) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Publish authenticated, sanitized Higgsfield CLI catalog snapshots; never performs generation.' `
    -Force | Out-Null

Get-ScheduledTask -TaskName $taskName |
    Select-Object TaskName, State |
    ConvertTo-Json -Compress
