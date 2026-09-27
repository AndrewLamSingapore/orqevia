# Portable Read Aloud challenge

`voice-regression.test.mjs` runs against an independently obtained frozen checkout and writes observations only to stdout. It never writes into the candidate or the historical evidence directory. The independently authored original reproductions remain preserved under `voice-091e2f9`; read its `ERRATUM.md` before its historical report.

Required inputs:

- `PRIME_CANDIDATE_ROOT`: absolute path to the frozen checkout.
- `EXPECTED_VOICE_SHA256`: SHA-256 of `clients/pwa/voice.mjs`, supplied by the independent verifier after source/tree verification. Do not accept a candidate self-claim or hash an unchecked checkout and call it independent provenance verification.
- Optional `PRIME_CANDIDATE_SHA`: full Git revision for log correlation; the challenge labels this a caller claim and does not replace Git/source verification.
- Optional `PRIME_INCLUDE_SYNCHRONOUS_FAULT=1`: include DV-09 reentrant callbacks. Native WebKit delivery of this sequence is UNPROVEN, so it is skipped by default.

The main suite preserves DV-01 through DV-08. It also checks the source digest before import, after import, and after the challenges. The surrounding runner must keep the whole checkout frozen and verify dependencies and source provenance. These file checks alone do not protect an actively hostile mutable filesystem or authenticate a Git repository.

This suite imports candidate JavaScript; it is not a security sandbox. The surrounding verifier must run it in an isolated test environment without ABEX production credentials or production connectivity. The commands below describe source acquisition and invocation, not installation of that isolation boundary.

All suite receipts say **PROVEN_BY_AUTOMATION; independently authored outside ABEX; native Dell UNPROVEN**. Running the file on Windows does not by itself establish host provenance: an independent machine receipt must establish that it was the physical Dell. Speech APIs are mocked even when Node runs on Dell; physical iPhone audibility remains **REQUIRES_PHYSICAL_DEVICE**. Only Owner observation can close that gate.

## Windows PowerShell

Keep the verifier package and candidate checkout separate. Example paths:

```powershell
$PeerRoot = 'C:\JARVIS-Dell-Peer'
$env:PRIME_CANDIDATE_ROOT = 'C:\JARVIS-Dell-Peer\checkouts\091e2f919edb1711b5a9e88404818095fa32b537'
$env:PRIME_CANDIDATE_SHA = '091e2f919edb1711b5a9e88404818095fa32b537'
$env:EXPECTED_VOICE_SHA256 = 'db8fd83608eae5848cb0ba07c15d078f09e804bee72c175cfc16649f89f20c61'
$RunRoot = Join-Path $PeerRoot ('runs\voice-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $RunRoot -ErrorAction Stop | Out-Null
node --test --test-reporter=tap (Join-Path $PeerRoot 'challenges\voice-regression.test.mjs') > (Join-Path $RunRoot 'voice.tap') 2>&1
$Result = $LASTEXITCODE
Get-Content (Join-Path $RunRoot 'voice.tap')
Get-FileHash -Algorithm SHA256 (Join-Path $RunRoot 'voice.tap')
Write-Output "VOICE_EXIT_CODE=$Result"
```

Those digest/revision values reproduce the preserved historical candidate. For every successor, the surrounding independent runner must supply the successor checkout, exact revision, and independently verified source digest. Never reuse the historical digest for a successor.

If the independent runner has not already obtained the checkout, the following reads from the existing private source remote using Git's existing credential helper and creates a fresh local directory. It never pushes or connects to ABEX production. Stop if any command fails; do not reuse an occupied destination or discard local changes.

```powershell
$FrozenSha = '091e2f919edb1711b5a9e88404818095fa32b537'
$Checkout = Join-Path 'C:\JARVIS-Dell-Peer\checkouts' ($FrozenSha + '-' + [guid]::NewGuid().ToString('N'))
git clone --no-checkout 'https://github.com/AndrewLamSingapore/prime.git' $Checkout
if ($LASTEXITCODE -ne 0) { throw 'Source clone failed.' }
git -C $Checkout fetch origin $FrozenSha
if ($LASTEXITCODE -ne 0) { throw 'Frozen revision fetch failed.' }
git -C $Checkout -c core.autocrlf=false checkout --detach $FrozenSha
if ($LASTEXITCODE -ne 0) { throw 'Frozen revision checkout failed.' }
$ObservedSha = (git -C $Checkout rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $ObservedSha -ne $FrozenSha) { throw 'Revision mismatch.' }
$Dirty = git -C $Checkout status --porcelain --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $Dirty) { throw 'Candidate checkout is not clean.' }
$env:PRIME_CANDIDATE_ROOT = $Checkout
```

The full verifier must still validate tree/manifest/provenance, canonical regressions, migrations, rollback, and every other required gate. A voice-suite pass cannot authorize promotion.

## WSL / Linux

Use a Linux path visible to the Node process. For a Windows checkout, WSL commonly exposes `C:\JARVIS-Dell-Peer` as `/mnt/c/JARVIS-Dell-Peer`. Prefer a fresh Linux checkout if filesystem case or line-ending behavior differs. Do not have two runtimes mutate one candidate directory.

```bash
export PRIME_CANDIDATE_ROOT='/mnt/c/JARVIS-Dell-Peer/checkouts/091e2f919edb1711b5a9e88404818095fa32b537'
export PRIME_CANDIDATE_SHA='091e2f919edb1711b5a9e88404818095fa32b537'
export EXPECTED_VOICE_SHA256='db8fd83608eae5848cb0ba07c15d078f09e804bee72c175cfc16649f89f20c61'
node --test --test-reporter=tap /mnt/c/JARVIS-Dell-Peer/challenges/voice-regression.test.mjs
```

For a fresh local checkout using existing Git credentials:

```bash
set -e
frozen_sha='091e2f919edb1711b5a9e88404818095fa32b537'
checkout_root=$(mktemp -d "$HOME/prime-voice-checkout.XXXXXXXX")
git clone --no-checkout 'https://github.com/AndrewLamSingapore/prime.git' "$checkout_root"
git -C "$checkout_root" fetch origin "$frozen_sha"
git -C "$checkout_root" -c core.autocrlf=false checkout --detach "$frozen_sha"
test "$(git -C "$checkout_root" rev-parse HEAD)" = "$frozen_sha"
test -z "$(git -C "$checkout_root" status --porcelain --untracked-files=all)"
export PRIME_CANDIDATE_ROOT="$checkout_root"
```

Capture stdout/stderr into a newly allocated run directory and preserve its exit code and digest. Keep failed runs. Missing input, invalid digest, digest mismatch, or source path escaping the checkout fails before the challenges. Tested in this workspace with Node `v24.19.0`; native Windows and WSL execution are UNPROVEN until machine receipts exist.
