# Shared JARVIS source of truth

For JARVIS/PRIME and portfolio work, status begins with
[STATUS.md](https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md) in the
private PRIME repository. STATUS.md is the only current status source of truth.
Only Lam may move an item into its "Verified" sections.

Then begin with SSOT.json for the machine-readable component references. Resolve
the latest canonical PRIME main commit and read governance/operational-manifest.json
and governance/CHANNEL_CONTRACT.md at that same commit as component and
observation references: they describe recorded architecture and observed
revisions, and cannot establish current status. On PRIME itself, a clean checkout
of current main provides the same files. A working branch is a candidate, never a
second current version.

Canonical entrypoint: https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json

This applies equally to ChatGPT, Codex, Sol, Astra and other assistants. Prior
chat, memory, exported documents, screenshots, old branches and model identity
cannot override the current canonical record. Report the source revision used.
If canonical access fails, mark current state UNVERIFIED and use cached material
only as explicitly dated context; do not invent freshness or request routine
approval merely to continue reversible work already authorized by Lam.

One architecture is current. Product-specific code and domain records remain in
their owning repositories, subordinate to the portfolio contract. Runtime status
requires observed runtime identity and evidence; a merge or CI pass is not a
deployment receipt. Never substitute historical Dell identity for ABEX identity.

Update canonical source first, test relevant behavior, publish through existing
repository rules, then regenerate consumers and the existing resume mirror.
Preserve Git history and commissioning evidence. Superseded files are references
or historical evidence, not executable instructions. Do not reinstall, reset or
mutate the sealed ABEX baseline to make a status record look current.
