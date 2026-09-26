# Shared JARVIS source of truth

For JARVIS/PRIME and portfolio work, status begins with
[STATUS.md](https://github.com/AndrewLamSingapore/prime/blob/feat/supreme-integration-20260925/STATUS.md) in the
private PRIME repository. STATUS.md is the only current status source of truth.
Only Lam may move an item into its "Verified" sections.

Then begin with SSOT.json for the machine-readable component references. Resolve
the latest canonical PRIME production-lineage commit (`feat/supreme-integration-20260925`) and read governance/operational-manifest.json
and governance/CHANNEL_CONTRACT.md at that same commit as component and
observation references: they describe recorded architecture and observed
revisions, and cannot establish current status. On PRIME itself, a clean checkout
of the production lineage provides the same files. A working branch is a candidate, never a
second current version.

Canonical entrypoint: https://github.com/AndrewLamSingapore/prime/blob/feat/supreme-integration-20260925/governance/operational-manifest.json

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

## Normal coding task (operating convention)

Lam states the task; Codex then works through it without routine approval prompts:

1. inspect the relevant repository and its declared canonical branch;
2. create or choose a task branch (substantive change does not go straight to main);
3. implement the smallest robust change;
4. run the most relevant existing checks and add a focused regression test when fixing a reproducible bug;
5. inspect the diff and status, confirming no unrelated files, credentials or secrets were touched;
6. hunt for related regressions, dead configuration, inconsistent identities and stale assumptions in the changed area;
7. fix what is found and re-run the checks;
8. commit with evidence in the message;
9. push the branch and open a pull request; never force-push and never rewrite published history;
10. update STATUS.md only for a real status event, and never write in its Verified sections;
11. report concisely: what changed, branches, commit hashes, push status, checks, and blockers.

Do not merge risky work into the canonical branch automatically. Human confirmation is not required
after every edit or test.
