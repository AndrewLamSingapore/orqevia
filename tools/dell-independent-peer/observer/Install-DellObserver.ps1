[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'JARVIS\DellIndependentPeer'),
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$TaskName = 'JARVIS Dell Independent Observer'

# Refuse cloud/Linux/WSL and non-Dell hosts before installing anything.
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or $env:WSL_DISTRO_NAME) {
    throw 'BLOCKED: native Windows Dell is required; no installation performed.'
}
$Computer = Get-CimInstance Win32_ComputerSystem
if ($Computer.Manufacturer -notmatch '^Dell(\s|$)') {
    throw 'BLOCKED: native host manufacturer is not Dell; no installation performed.'
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'BLOCKED: observer task already exists. Preserve it; inspect or uninstall explicitly before replacing.'
}
if (-not $PythonPath) {
    $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$Interpreter = & $PythonPath -c 'import sys; assert sys.platform == "win32"; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not $Interpreter) { throw 'BLOCKED: native Windows Python required.' }
$PythonPath = ($Interpreter | Select-Object -Last 1).Trim()
$Source = Join-Path $PSScriptRoot 'observer.py'
$CodeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash.ToLowerInvariant()
$Release = Join-Path $InstallRoot ('releases\' + $CodeHash)
$State = Join-Path $InstallRoot 'state'
$Entry = Join-Path $Release 'observer.py'
New-Item -ItemType Directory -Path $Release -Force | Out-Null
New-Item -ItemType Directory -Path $State -Force | Out-Null
if (Test-Path -LiteralPath $Entry) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Entry).Hash.ToLowerInvariant() -ne $CodeHash) {
        throw 'BLOCKED: installed release content differs; evidence preserved.'
    }
} else {
    # Exclusive create avoids silently replacing a concurrently installed release.
    $InputFile = [System.IO.File]::OpenRead($Source)
    try {
        $OutputFile = [System.IO.File]::Open($Entry, [System.IO.FileMode]::CreateNew)
        try { $InputFile.CopyTo($OutputFile) } finally { $OutputFile.Dispose() }
    } finally { $InputFile.Dispose() }
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Entry).Hash.ToLowerInvariant() -ne $CodeHash) {
    throw 'BLOCKED: copied observer digest does not match selected release; no code executed or task registered.'
}
& $PythonPath -B $Entry --bind-host --state-dir $State
if ($LASTEXITCODE -ne 0) { throw 'BLOCKED: host binding failed; no scheduled task registered.' }

# Existing native git/gh credentials stay in their existing credential store.
# No execution-policy override, stored password, elevated run level, or ABEX endpoint.
$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Arguments = '-B "' + $Entry + '" --once --state-dir "' + $State + '"'
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $Arguments
$Login = New-ScheduledTaskTrigger -AtLogOn -User $User
$Hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($Login, $Hourly) -Settings $Settings -Principal $Principal -Description 'Passive independent Dell source-ref observation; never executes candidates or promotes PRIME.' | Out-Null
Write-Output ('REGISTERED: ' + $TaskName)
Write-Output ('HOST BINDING: ' + (Join-Path $State 'host-binding.json'))
Write-Output 'Observation is scheduled while this user is logged in. Candidate verification and physical acceptance remain separate.'

# First-run observation may be BLOCKED by remote access; this is never a verification PASS.
& $PythonPath -B $Entry --once --state-dir $State
if ($LASTEXITCODE -ne 0) { Write-Warning 'Initial remote observation BLOCKED. Scheduled retries remain enabled; no verification or promotion approval was issued.' }
