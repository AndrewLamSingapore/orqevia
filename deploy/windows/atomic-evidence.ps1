function Write-AtomicJsonEvidence(
    [Parameter(Mandatory=$true)]$Value,
    [Parameter(Mandatory=$true)][string]$Path,
    [int]$Depth = 25
) {
    $directory = Split-Path -Parent $Path
    $temporary = Join-Path $directory ((Split-Path -Leaf $Path) + '.tmp')
    $json = $Value | ConvertTo-Json -Depth $Depth -ErrorAction Stop
    $json | Set-Content -LiteralPath $temporary -Encoding utf8 -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $temporary) -or (Get-Item -LiteralPath $temporary).Length -eq 0) {
        throw 'Evidence temporary file was not written'
    }
    Move-Item -LiteralPath $temporary -Destination $Path -Force -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $Path) -or (Get-Item -LiteralPath $Path).Length -eq 0) {
        throw 'Evidence result file was not committed'
    }
}
