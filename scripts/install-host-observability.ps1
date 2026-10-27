# Update the existing scheduled sampler and its fixed hook; register no task.
param([Parameter(Mandatory=$true)][string]$PublicCaPath)
$ErrorActionPreference = 'Stop'
$CollectorRoot = 'C:\ProgramData\ABEX\PrimeHostMetrics'
$CheckpointParent = 'C:\Users\Admin\AppData\Local\ORQEVIA\checkpoints'
$Checkpoint = Join-Path $CheckpointParent ('collector-install-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
$OwnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$WriterSids = @($OwnerSid, 'S-1-5-18', 'S-1-5-32-544') | Select-Object -Unique
$RequiredFiles = @('collect-host-metrics.ps1', 'collect-operational-health.ps1', 'collect_operational_health.py')

function Set-ScopedAcl([string]$Path, [bool]$PublicRead) {
    $item = Get-Item -LiteralPath $Path
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point not allowed in sampler installation' }
    $inheritance = if ($item.PSIsContainer) { 'OICI' } else { '' }
    $sddl = 'D:P'
    foreach ($sid in $WriterSids) {
        $sddl += "(A;${inheritance};FA;;;$sid)"
    }
    if ($PublicRead) {
        $sddl += "(A;${inheritance};FRFX;;;BU)"
    }
    # Apply only the DACL. Set-Acl can also request SACL privileges on a second
    # protected-path installation; auditing and owner/group are unchanged here.
    [OrqeviaCollectorInstallFile]::SetAccess($Path, $sddl)
}

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class OrqeviaCollectorInstallFile {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 private static extern bool MoveFileEx(string from, string to, int flags);
 [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl, uint revision, out IntPtr descriptor, out uint size);
 [DllImport("advapi32.dll", SetLastError=true)]
 private static extern bool GetSecurityDescriptorDacl(IntPtr descriptor, out bool present, out IntPtr dacl, out bool defaulted);
 [DllImport("advapi32.dll", CharSet=CharSet.Unicode)]
 private static extern uint SetNamedSecurityInfo(string path, int kind, uint info, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);
 [DllImport("kernel32.dll")]
 private static extern IntPtr LocalFree(IntPtr value);
 public static void SetAccess(string path, string sddl) {
  IntPtr descriptor, dacl; uint size; bool present, defaulted;
  if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl,1,out descriptor,out size)) throw new Win32Exception(Marshal.GetLastWin32Error());
  try {
   if (!GetSecurityDescriptorDacl(descriptor,out present,out dacl,out defaulted) || !present) throw new Win32Exception(Marshal.GetLastWin32Error());
   uint error=SetNamedSecurityInfo(path,1,0x80000004u,IntPtr.Zero,IntPtr.Zero,dacl,IntPtr.Zero);
   if (error!=0) throw new Win32Exception((int)error);
  } finally { LocalFree(descriptor); }
 }
 public static void Replace(string from, string to) {
  if (!MoveFileEx(from,to,9)) throw new Win32Exception(Marshal.GetLastWin32Error());
 }
}
'@
function Install-Atomic([string]$Destination, [byte[]]$Bytes) {
    $temporary = Join-Path $CollectorRoot ([IO.Path]::GetRandomFileName())
    try {
        [IO.File]::WriteAllBytes($temporary, $Bytes)
        Set-ScopedAcl $temporary $true
        [OrqeviaCollectorInstallFile]::Replace($temporary, $Destination)
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

foreach ($name in $RequiredFiles) {
    $source = Get-Item -LiteralPath (Join-Path $PSScriptRoot $name)
    if ($source.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source reparse point forbidden' }
}
$ca = Get-Item -LiteralPath $PublicCaPath
if ($ca.Extension -ne '.crt' -or $ca.Length -gt 32768 -or ($ca.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Public CA certificate required' }
$null = [Security.Cryptography.X509Certificates.X509Certificate2]::new($ca.FullName)
New-Item -ItemType Directory -Path $Checkpoint -ErrorAction Stop | Out-Null
Set-ScopedAcl $Checkpoint $false
$targets = @('C:\ProgramData\ABEX', $CollectorRoot, (Join-Path $CollectorRoot 'receipt'))
$targets += @(Get-ChildItem -LiteralPath $CollectorRoot -Recurse -Force | ForEach-Object FullName)
$targets = @($targets | Select-Object -Unique)
$priorAcls = @()
foreach ($target in $targets) {
    $prior = Get-Acl -LiteralPath $target
    $priorAcls += @{path=$target; sddl=$prior.Sddl}
}
$priorAcls | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Checkpoint 'prior-acls.json') -Encoding UTF8
foreach ($name in @($RequiredFiles) + @('collector-integrity.json', 'orqevia-ca.crt')) {
    $previous = Join-Path $CollectorRoot $name
    if (Test-Path -LiteralPath $previous -PathType Leaf) { Copy-Item -LiteralPath $previous -Destination (Join-Path $Checkpoint $name) }
}
foreach ($target in $targets) { Set-ScopedAcl $target $true }
foreach ($name in $RequiredFiles) {
    Install-Atomic (Join-Path $CollectorRoot $name) ([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot $name)))
}
Install-Atomic (Join-Path $CollectorRoot 'orqevia-ca.crt') ([IO.File]::ReadAllBytes($ca.FullName))
$inventory = @($RequiredFiles | ForEach-Object { @{name=$_; sha256=(Get-FileHash -LiteralPath (Join-Path $CollectorRoot $_) -Algorithm SHA256).Hash.ToLowerInvariant()} })
$integrity = @{schema_version='orqevia.collector-integrity.v1'; allowed_writer_sids=@($WriterSids); files=$inventory;
    ca_sha256=(Get-FileHash -LiteralPath (Join-Path $CollectorRoot 'orqevia-ca.crt') -Algorithm SHA256).Hash.ToLowerInvariant()}
$json = $integrity | ConvertTo-Json -Depth 6
Install-Atomic (Join-Path $CollectorRoot 'collector-integrity.json') ([Text.UTF8Encoding]::new($false).GetBytes($json))
foreach ($file in $inventory) {
    if ((Get-FileHash -LiteralPath (Join-Path $CollectorRoot $file.name) -Algorithm SHA256).Hash -ne $file.sha256) { throw 'Installed file digest mismatch' }
}
@{status='INSTALLED_EXISTING_SAMPLER_NO_NEW_TASK'; installed_at=[DateTime]::UtcNow.ToString('o'); checkpoint=$Checkpoint;
  native_host=[Environment]::MachineName; scripts=$inventory; task_registration_changed=$false;
  configured_runtime_writers_preserved=$true; public_ca_only=$true} | ConvertTo-Json -Depth 6
