# PRIME off-host backup transport (source-only candidate)

`scripts/offhost_backup.py` encrypts an already coherent, write-fenced directory. It does not stop PRIME/Interface, capture Docker volumes, manage Azure, or prove that a backup can restore production. Never point it at live `/data`. Use an access-restricted parent for ciphertext staging and isolated restores; Windows files inherit that parent's ACL.

Generate an X25519 keypair on an **offline recovery device**, keeping the passphrase-protected PKCS#8 private PEM and passphrase off ABEX and off Azure. Transfer only the SubjectPublicKeyInfo public PEM to ABEX. Keep the exact utility source and pinned ciphertext SHA-256 with recovery instructions outside ABEX. The Azure verifier signing key is unrelated and cannot decrypt these bundles.

After the fenced snapshot and private-parent ACL are independently verified:

```text
python -B -m scripts.offhost_backup encrypt FENCED_SNAPSHOT PUBLIC.pem NEW_CIPHERTEXT.bin
```

The command prints only `ciphertext_sha256=<hex>`. Pin that value in an independently protected recovery record. Transfer only the ciphertext to a private, versioned off-host destination. On an isolated recovery machine with the offline private key:

```text
python -B -m scripts.offhost_backup restore CIPHERTEXT.bin PRIVATE.pem NEW_RESTORE_DIRECTORY PINNED_CIPHERTEXT_SHA256 --ask-passphrase
```

The encrypted bundle contains a file/directory manifest and per-file SHA-256 values. AES-256-GCM authenticates each 1 MiB chunk and a final count/digest frame; restore also requires the separately pinned ciphertext hash. Paths, reparse points, duplicates, truncation, and source-tree changes detected during capture are rejected. A failed restore publishes no destination directory. The staged restore is plaintext, so its parent must remain private.

After restore, separately run SQLite integrity checks, application artifact checks, and authenticated Golden Owner/Member canaries. A byte-exact restore does not prove that Golden understands data written by a later candidate. An off-host download and isolated restore are required before calling Azure storage a recoverable backup.
