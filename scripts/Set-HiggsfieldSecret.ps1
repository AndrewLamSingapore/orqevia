[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$secretDirectory = 'C:\Users\Admin\Documents\ABEX\secrets'
$secretPath = Join-Path $secretDirectory 'higgsfield_api_key.txt'

if (-not (Test-Path -LiteralPath $secretDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $secretDirectory | Out-Null
}
if (-not (Test-Path -LiteralPath $secretPath -PathType Leaf)) {
    New-Item -ItemType File -Path $secretPath | Out-Null
}

$secure = Read-Host 'Paste the Higgsfield API key (key-id:key-secret); input will not echo' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plain = $null
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if (
        [string]::IsNullOrEmpty($plain) -or
        $plain.Length -gt 4096 -or
        $plain.Contains("`r") -or
        $plain.Contains("`n") -or
        $plain.Contains(' ') -or
        $plain.Split(':').Count -ne 2 -or
        -not [Text.Encoding]::ASCII.GetString([Text.Encoding]::ASCII.GetBytes($plain)).Equals($plain)
    ) {
        throw 'Invalid API-key format; expected one ASCII key-id:key-secret value without whitespace'
    }

    [IO.File]::WriteAllText($secretPath, $plain, [Text.UTF8Encoding]::new($false))

    $directoryAcl = New-Object System.Security.AccessControl.DirectorySecurity
    $directoryAcl.SetAccessRuleProtection($true, $false)
    $fileAcl = New-Object System.Security.AccessControl.FileSecurity
    $fileAcl.SetAccessRuleProtection($true, $false)
    foreach ($identity in @('NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators', 'DESKTOP-27LKJ2V\Admin')) {
        $directoryAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
        )))
        $fileAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity, 'FullControl', 'None', 'None', 'Allow'
        )))
    }
    Set-Acl -LiteralPath $secretDirectory -AclObject $directoryAcl
    Set-Acl -LiteralPath $secretPath -AclObject $fileAcl

    Write-Output "Higgsfield API key stored without echoing at: $secretPath"
    Write-Output 'Higgsfield remains disabled until an explicit validation and enablement step.'
}
finally {
    $plain = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}
