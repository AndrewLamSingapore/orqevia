[CmdletBinding()]
param(
    [string]$BaseUri = 'https://192.168.1.23:8443/pwa',
    [string]$ExpectedSource = '767f9451d42c65eb905f2c3e5f816536c4e17982',
    [string]$ExpectedImageDigest = 'sha256:67af1345345ab8b89b2195507c3ed8343ac1998de79ec81f8494dcaf49346f37',
    [string]$ExpectedGeneration = 'orqevia-golden-gen7-20261019',
    [string]$ExpectedReceiptDigest = 'sha256:74064717221f5948d04ef62e5b0e1f0dee3d17580e3621b4dc7a86bd9bf1955b',
    [switch]$AllowUntrustedTransportCertificate
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$canonicalKey = Join-Path $root 'governance\keys\abex-runtime-attestation-ed25519.pub'
$expectedFingerprint = 'SHA256:qtAf3agqYCAAcBk6n4Tf4fqqAJ3t444NEKD7sxr+QPA'
$temporary = Join-Path $env:TEMP ("jarvis-attestation-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null

try {
    $jsonPath = Join-Path $temporary 'runtime-attestation.json'
    $signaturePath = "$jsonPath.sig"
    if ($AllowUntrustedTransportCertificate -and $PSVersionTable.PSVersion.Major -lt 7) {
        # Windows PowerShell 5.1 has no -SkipCertificateCheck; use the system curl.
        & curl.exe -k -s "$BaseUri/runtime-attestation.json" -o $jsonPath
        & curl.exe -k -s "$BaseUri/runtime-attestation.json.sig" -o $signaturePath
        if ($LASTEXITCODE -ne 0) { throw 'Attestation fetch failed' }
    } else {
        $request = @{ UseBasicParsing = $true }
        if ($AllowUntrustedTransportCertificate) { $request.SkipCertificateCheck = $true }
        Invoke-WebRequest @request -Uri "$BaseUri/runtime-attestation.json" -OutFile $jsonPath
        Invoke-WebRequest @request -Uri "$BaseUri/runtime-attestation.json.sig" -OutFile $signaturePath
    }

    $actualFingerprint = (ssh-keygen -lf $canonicalKey -E sha256).Split(' ')[1]
    if ($actualFingerprint -ne $expectedFingerprint) { throw 'Canonical attestation public-key fingerprint mismatch' }

    $allowedSigners = Join-Path $temporary 'allowed-signers'
    $allowed = "abex-runtime-attestation $(Get-Content -Raw -LiteralPath $canonicalKey)".Trim() + "`n"
    [IO.File]::WriteAllText($allowedSigners, $allowed, [Text.UTF8Encoding]::new($false))
    $command = 'ssh-keygen -Y verify -f "{0}" -I abex-runtime-attestation -n prime-runtime-attestation -s "{1}" < "{2}"' -f $allowedSigners, $signaturePath, $jsonPath
    cmd.exe /d /c $command | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Runtime attestation signature is invalid' }

    $attestation = Get-Content -Raw -LiteralPath $jsonPath | ConvertFrom-Json
    $violations = [System.Collections.Generic.List[string]]::new()
    if ($attestation.status -ne 'VERIFIED') { $violations.Add('attestation_not_verified') }
    if ($attestation.live_runtime.source_sha -ne $ExpectedSource) { $violations.Add('live_source_mismatch') }
    if ($attestation.live_runtime.runtime_revision -ne $ExpectedSource) { $violations.Add('runtime_revision_mismatch') }
    if ($attestation.live_runtime.image_digest -ne $ExpectedImageDigest) { $violations.Add('live_image_mismatch') }
    if ($attestation.accepted_binding.golden_generation -ne $ExpectedGeneration) { $violations.Add('golden_generation_mismatch') }
    if ($attestation.accepted_binding.runtime_receipt_digest -ne $ExpectedReceiptDigest) { $violations.Add('runtime_receipt_mismatch') }
    if ($attestation.accepted_binding.audio_exclusion -ne 'PARKED_NOT_ACCEPTED') { $violations.Add('audio_exclusion_mismatch') }
    if ($attestation.verification.live_docker_inspection -ne $true) { $violations.Add('live_inspection_missing') }
    if ($attestation.verification.mutation_authority_exposed -ne $false) { $violations.Add('mutation_authority_exposed') }
    if ($violations.Count -ne 0) { throw ('Runtime attestation violations: ' + ($violations -join ', ')) }

    [ordered]@{
        verdict = 'PROMOTION_VERIFICATION_PASS'
        signature = 'PASS'
        signer_fingerprint = $actualFingerprint
        source_sha = $attestation.live_runtime.source_sha
        image_digest = $attestation.live_runtime.image_digest
        runtime_revision = $attestation.live_runtime.runtime_revision
        golden_generation = $attestation.accepted_binding.golden_generation
        runtime_receipt_digest = $attestation.accepted_binding.runtime_receipt_digest
        audio = 'PARKED_PHYSICAL_FAIL_NOT_ACCEPTED'
        started_at = $attestation.live_runtime.started_at
        attestation_generated_at = $attestation.generated_at_utc
    } | ConvertTo-Json -Compress
}
finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
