# Isolated Azure Blob transport candidate

This helper is source-only. It has made no Azure call and is not a backup,
recovery, deployment, or production acceptance receipt. It transports only a
generated synthetic canary or a file beginning with the encrypted `PRIMEBKP1`
format. The latter still requires independent backup fencing, encryption,
key custody, restore validation, and operator authorization.

Install the official `azure-storage-blob` Python SDK in a task-local environment
before a separately authorized live run. The helper itself never creates SAS
tokens, logs in, reads Azure configuration, or handles an account key. It fixes
the destination to `abexrecovery20261006/abex-recovery` and accepts only a
container SAS (`sr=c`) with exactly `sp=rcw`, `spr=https`, and an expiry 5–60
minutes away. It rejects account SAS and stored access policy identifiers.

Provide the SAS query on stdin, for example from the local Windows clipboard.
First set `$pythonExe` to the full path of a verified task-local Python runtime
(Codex reports its bundled path through workspace dependencies); do not rely on
the Microsoft Store `python` PATH alias on ABEX:

```powershell
$pythonExe = Read-Host 'Full path to verified task-local python.exe'
Get-Clipboard -Raw | & $pythonExe -B scripts/offhost_blob_transport.py canary
```

To retrieve a previously uploaded encrypted bundle, use its independently
pinned SHA-256 and exact known blob name. The destination is an absolute path
to a **new** isolated directory; the helper creates it and places only the
verified ciphertext there:

```powershell
$digest = Read-Host 'Pinned ciphertext SHA-256'
$blobName = "encrypted/$digest.primebkp"
$newDir = Read-Host 'Absolute path to a NEW isolated directory'
Get-Clipboard -Raw | & $pythonExe -B scripts/offhost_blob_transport.py download-ciphertext $newDir --blob-name $blobName --expected-sha256 $digest
```

The download streams at most 4 MiB per chunk and refuses ciphertext above
16 GiB. It publishes the final file only after the downloaded bytes match the
pinned hash and format prefix; an existing directory or final file is never
overwritten. Interrupted runs may leave an unverified temporary ciphertext
file, never a success receipt. Decryption and isolated restore are separate
operations on a recovery device, with their own validation gate.

For a protected local file, pipe its contents into stdin instead; the helper
does not validate that file's ACL, so the operator must establish protection
before use. Never put the SAS in a command argument, URL, environment variable,
shell history, issue, PR, log, or receipt. An encrypted-file run takes only the
non-secret ciphertext path and a previously pinned SHA-256 as arguments; a
magic prefix alone is not proof of valid encryption. Each upload uses
`overwrite=False` and independently hashes streamed download bytes before a
success result is printed. A failed or interrupted transfer does not issue a
success result; it may leave an unverified blob that requires separate review.
