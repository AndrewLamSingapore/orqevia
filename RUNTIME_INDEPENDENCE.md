# PRIME runtime identity and continuity

Current status authority is [STATUS.md](STATUS.md). Architecture is described by `docs/ARCHITECTURE_V1.md` and the machine-readable component references in `governance/operational-manifest.json`, which cannot establish current status. This replaces the former Dell-hosted, local-only and universal approval-gate description.

- ABEX is the intended PRIME runtime host. Dell, PWA and voice are authenticated clients; a client cannot increase authority.
- Persistent task, artifact and evidence stores survive application lifecycle changes. Never delete durable state to make an acceptance check pass.
- Ordinary bounded work follows direct observed execution. Consequential actions retain specific authentication, ownership and policy controls.
- Runtime identity requires an independently observed receipt tying the host, Git revision and immutable product manifest together. Source publication, relay activity and historical Dell records do not prove ABEX deployment.
- Model failure may degrade service; it must not silently increase authority or change policy.

Current ABEX acceptance is unverified. This documentation update performs no host restart, reinstall, provider change or baseline mutation. Deployment inputs are defined in `deploy/product-runtime-v1.json`; historical procedures remain recoverable from Git.
