[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Admin\Documents\ABEX\runtime\orqevia-epoch-20261016'
$python = 'C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe'
$publisher = Join-Path $root 'scripts\Publish-HiggsfieldCatalog.py'
$logDirectory = 'C:\ProgramData\ORQEVIA\logs'
$logPath = Join-Path $logDirectory 'higgsfield-catalog-publisher.log'

if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}

$mutex = [Threading.Mutex]::new($false, 'Local\ORQEVIA-HiggsfieldCatalogPublisher')
if (-not $mutex.WaitOne(0)) {
    "$(Get-Date -Format o)|SKIPPED_ALREADY_RUNNING|snapshot_preserved=true" |
        Add-Content -LiteralPath $logPath -Encoding utf8
    $mutex.Dispose()
    exit 0
}

try {
    $env:PYTHONUTF8 = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $output = & $python -B $publisher 2>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        "$(Get-Date -Format o)|SUCCESS|$($output -join ' ')" |
            Add-Content -LiteralPath $logPath -Encoding utf8
        exit 0
    }
    "$(Get-Date -Format o)|FAILED|exit=$code|interactive_auth_attempted=false|snapshot_preserved=true" |
        Add-Content -LiteralPath $logPath -Encoding utf8
    exit $code
}
catch {
    "$(Get-Date -Format o)|FAILED|$($_.Exception.GetType().Name)|interactive_auth_attempted=false|snapshot_preserved=true" |
        Add-Content -LiteralPath $logPath -Encoding utf8
    exit 1
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
