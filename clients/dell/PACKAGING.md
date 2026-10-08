> PRIME component reference: [dated operational manifest](https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json). Source, package bytes, identity and observed deployment retain their separate authority boundaries; this packaging document and the manifest do not establish current runtime state.

# Reproducible Dell client package

Requires Python 3.10+ and Node 20+ already installed. No third-party dependencies or installation step. From this directory:

```
python -B tools/test_package_client.py
python -B tools/package_client.py --build --archive client.zip --evidence build
```

Use a new archive filename for every build; existing files are never overwritten. Omit `--build` to verify an existing archive. Both canonical and URL/security tests execute against extracted archive bytes before PASS. Archive entries use fixed timestamps, permissions, ordering and uncompressed storage, making bytes independent of local filesystem timestamps and compression-library versions. Evidence directories have unique names and are excluded from the archive and Git.

`SOURCE-SHA256.json` is the reviewed source lock; `lib/upstream.mjs` additionally has a fixed approval hash in the tooling. Source changes require review and an explicit lock update. The URL regression corrects a historical root-path join that could discard the ABEX origin, and denies redirects. Runtime credentials are supplied only through `JARVIS_CLIENT_TOKEN`; no credentials, deployment certificates, private configuration, DPAPI files or ABEX workspace paths belong in this package. `.env.example` contains placeholders only.

Historical physical-integration bundles remain separate immutable evidence. This portable package is a deterministic source release, not a regeneration of those sealed ZIP bytes and not a fresh enrollment mechanism.

## Historical README

README.md is hash-pinned historical initial-delivery documentation. Its locked/unconfigured/TAP descriptions do not define current production. Root Architecture v1 supersedes those assumptions; enrollment and deployment are proved by separate evidence.
