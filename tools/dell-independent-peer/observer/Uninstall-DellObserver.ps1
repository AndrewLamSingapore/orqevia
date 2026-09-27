[CmdletBinding()]
param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\DellIndependentPeer'))
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'BLOCKED: native Windows required.' }
$TaskName = 'JARVIS Dell Independent Observer'
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Task) { Write-Output 'Observer task absent; all files preserved.'; return }
$ExpectedRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') + '\'
if ($Task.Actions.Count -ne 1 -or $Task.Actions[0].Arguments -notlike ('*"' + $ExpectedRoot + 'releases\*\observer.py" --once --state-dir "' + $ExpectedRoot + 'state"')) {
    throw 'BLOCKED: task action does not match this observer installation; nothing changed.'
}
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output 'Observer task removed. Host binding, releases, inbox, FAIL evidence, and baseline are preserved.'
