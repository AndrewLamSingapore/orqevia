# Fixed sibling hook invoked by the existing host sampler, never a new task.
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'Collector accepts no caller arguments' }
$CollectorRoot = 'C:\ProgramData\ABEX\PrimeHostMetrics'
if ($PSScriptRoot -ne $CollectorRoot) { throw 'Fixed installed collector required' }
$Python = 'C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe'
$IntegrityPath = Join-Path $CollectorRoot 'collector-integrity.json'
$RequiredFiles = @('collect-host-metrics.ps1', 'collect-operational-health.ps1', 'collect_operational_health.py')
$IntegrityStatus = 'FAIL'
$IntegrityReason = 'COLLECTOR_INTEGRITY_UNAVAILABLE'
$CaVerified = $false

function Test-ScopedProtectedPath([string]$Path, [string[]]$AllowedSids) {
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    if (-not $acl.AreAccessRulesProtected) { return $false }
    $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($AllowedSids -notcontains $owner) { return $false }
    $writeRights = [Security.AccessControl.FileSystemRights]::Write -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            ($rule.FileSystemRights -band $writeRights) -and
            $AllowedSids -notcontains $rule.IdentityReference.Value) { return $false }
    }
    return $true
}

try {
    $integrityItem = Get-Item -LiteralPath $IntegrityPath
    if ($integrityItem.Length -gt 32768 -or ($integrityItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Invalid integrity file'
    }
    $integrity = [IO.File]::ReadAllText($IntegrityPath) | ConvertFrom-Json
    $allowed = @($integrity.allowed_writer_sids)
    if ($integrity.schema_version -ne 'orqevia.collector-integrity.v1' -or
        $allowed.Count -lt 2 -or $allowed.Count -gt 3 -or
        $allowed -notcontains 'S-1-5-18' -or $allowed -notcontains 'S-1-5-32-544' -or
        @($allowed | Where-Object { $_ -notmatch '^S-1-5-(18|32-544|21-[0-9-]+)$' }).Count) {
        throw 'Invalid scoped writer identities'
    }
    $files = @($integrity.files)
    if ($files.Count -ne $RequiredFiles.Count -or
        @($files | Group-Object name | Where-Object Count -ne 1).Count -or
        @($files | Where-Object { $_.name -notin $RequiredFiles }).Count) { throw 'Invalid digest inventory' }
    foreach ($path in @('C:\ProgramData\ABEX', $CollectorRoot, (Join-Path $CollectorRoot 'receipt'), $IntegrityPath)) {
        if (-not (Test-ScopedProtectedPath $path $allowed)) { throw 'Writer ACL not scoped/protected' }
    }
    foreach ($file in $files) {
        if ($file.sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid expected digest' }
        $path = Join-Path $CollectorRoot $file.name
        if (-not (Test-ScopedProtectedPath $path $allowed) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $file.sha256) {
            throw 'Installed digest or writer ACL mismatch'
        }
    }
    $caPath = Join-Path $CollectorRoot 'orqevia-ca.crt'
    if ($integrity.ca_sha256) {
        if ($integrity.ca_sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
            -not (Test-ScopedProtectedPath $caPath $allowed) -or
            (Get-FileHash -LiteralPath $caPath -Algorithm SHA256).Hash -ne $integrity.ca_sha256) {
            throw 'Public CA digest or ACL mismatch'
        }
        $CaVerified = $true
    }
    $IntegrityStatus = 'PASS'
    $IntegrityReason = 'INSTALLED_DIGESTS_AND_PROTECTED_WRITER_ACLS_MATCH'
} catch {
    # No exception text, ACL dump, credentials or environment enters the receipt.
    $IntegrityReason = 'INSTALLED_DIGEST_OR_PROTECTED_WRITER_ACL_INVALID'
}

$bootId = $null
try {
    $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3
    $bootId = $os.LastBootUpTime.ToUniversalTime().ToString('o')
} catch { $bootId = $null }
$hostReceipt = @{}
try {
    $path = Join-Path $CollectorRoot 'receipt\host-metrics.json'
    $item = Get-Item -LiteralPath $path
    if ($item.Length -gt 131072 -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid host receipt' }
    $record = [IO.File]::ReadAllText($path) | ConvertFrom-Json
    $hostReceipt = @{schema=$record.schema; host_id=$record.host_id; boot_id=$record.boot_id;
        captured_at=$record.captured_at; collector_id=$record.collector_id; cadence_seconds=$record.cadence_seconds}
} catch { $hostReceipt = @{} }
$context = @{schema_version='orqevia.operational-collector-context.v1';
    native_identity=@{host_id=[Environment]::MachineName; boot_id=$bootId}; host_receipt=$hostReceipt;
    integrity=@{status=$IntegrityStatus; reason=$IntegrityReason; observed_at=[DateTime]::UtcNow.ToString('o')};
    ca_verified=$CaVerified}
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$context | ConvertTo-Json -Compress -Depth 6 | & $Python -I -B (Join-Path $CollectorRoot 'collect_operational_health.py')
if ($LASTEXITCODE -ne 0) { throw 'Operational collector did not complete' }
