# PRIME off-host backup transport (source-only candidate)

`scripts/offhost_backup.py` encrypts an already coherent, write-fenced directory. It does not stop PRIME/Interface, capture Docker volumes, manage Azure, or prove that a backup can restore production. Never point it at live `/data`. Its repeated hash/identity checks reject detected source changes and hardlinks; they do **not** establish a write fence.

Generate an X25519 keypair on an **offline recovery device**, keeping the passphrase-protected PKCS#8 private PEM and passphrase off ABEX and off Azure. Compute the public-key fingerprint on that device with `python -B -m scripts.offhost_backup fingerprint PUBLIC.pem`; it hashes canonical DER SubjectPublicKeyInfo, not PEM text. Transfer only the public PEM and independently pinned fingerprint to ABEX. A mismatched public key is rejected before capture. Keep the exact utility source and pinned ciphertext SHA-256 with recovery instructions outside ABEX. The Azure verifier signing key is unrelated and cannot decrypt these bundles.

After the fenced snapshot and private-parent ACL are independently verified:

```text
python -B -m scripts.offhost_backup encrypt FENCED_SNAPSHOT PUBLIC.pem NEW_CIPHERTEXT.bin PINNED_RECIPIENT_SHA256
```

The command prints only `ciphertext_sha256=<hex>`. Pin that value in an independently protected recovery record. Transfer only the ciphertext to a private, versioned off-host destination. On an isolated recovery machine with the offline private key:

```text
python -B -m scripts.offhost_backup restore CIPHERTEXT.bin PRIVATE.pem NEW_RESTORE_DIRECTORY PINNED_CIPHERTEXT_SHA256
```

The command always prompts for the encrypted private-key passphrase. The restore parent must already be access-restricted: on Windows the utility checks the resolved parent and newly created staging directory through the security descriptor API, allowing only the current user, SYSTEM, Administrators, and owner rights; on POSIX it requires ownership and no group/other permissions. It rejects linked/junction ancestors. A crash may leave plaintext in that private parent; use an isolated recovery device and protect/clean its storage. A real-host ACL review is still required before production use.

The encrypted bundle contains a file/directory manifest and per-file SHA-256 values. AES-256-GCM authenticates each 1 MiB chunk and a final count/digest frame; restore also requires the separately pinned ciphertext hash. Paths, reparse points, duplicates, truncation, and detected source-tree changes are rejected. File and directory publication are atomic no-replace operations; a failed restore publishes no destination directory.

After restore, separately run SQLite integrity checks, application artifact checks, and authenticated Golden Owner/Member canaries. A byte-exact restore does not prove that Golden understands data written by a later candidate. An off-host download and isolated restore are required before calling Azure storage a recoverable backup.
