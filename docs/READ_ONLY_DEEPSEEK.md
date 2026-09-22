> Portfolio authority: [one current JARVIS status source](https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md). This document describes this repository only; it cannot override STATUS.md, the canonical architecture, or establish live deployment status.

# Read-only DeepSeek handoff

One small helper, no service and no daemon: `scripts/read-only-deepseek.ps1`.
It asks the DeepSeek API to read repository content and answer questions, while
being unable to change anything.

## What it does

- reads only files inside the repository you point it at;
- refuses secret-like paths (`.env*`, `*.key`, `*.pem`, `id_rsa*`, `*credential*`,
  `*secret*`, `auth.json`, `hosts.yml`, `config.toml`);
- sends the selected text to the DeepSeek API as a read-only review question;
- prints DeepSeek's answer as advisory text.

## What it cannot do

- modify, create, move or delete files;
- commit, push, merge or rewrite Git history;
- run shell commands, including any command suggested by the model;
- read or reveal API keys, tokens or credentials (the key is read from the
  existing Codex config and is never printed);
- change operating-system state.

The system prompt states these limits explicitly, and nothing in the script turns
model output into an action.

## How Lam invokes it

From any terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\User\Documents\JARVIS\repos\prime\scripts\read-only-deepseek.ps1 -RepoPath C:\Users\User\Documents\JARVIS\repos\prime -Question "Explain what scripts/check_canonical_state.py enforces."
```

Review specific files (comma-separated, relative to `-RepoPath`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\User\Documents\JARVIS\repos\prime\scripts\read-only-deepseek.ps1 -RepoPath C:\Users\User\Documents\JARVIS\repos\prime -Path STATUS.md,docs/ARCHITECTURE_V1.md -Question "Do these contradict each other? Propose a patch as text only."
```

Preview exactly what would be sent, without calling the API:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\User\Documents\JARVIS\repos\prime\scripts\read-only-deepseek.ps1 -Question "review" -DryRun
```

Useful optional parameters: `-Model` (default `deepseek-flash`), `-MaxFiles`
(default 8), `-MaxCharsPerFile` (default 6000), `-TimeoutSeconds` (default 180).

## Configuration

The helper reuses the existing persistent Codex/DeepSeek configuration at
`%USERPROFILE%\.codex\config.toml` (`[model_providers.deepseek]`). No credential
is stored in this repository and none is embedded in the script.

## Honest status

The path is configured and a direct read-only call has been exercised from this
Dell. Provider-side usage evidence is still pending Lam's own check on the
DeepSeek Usage dashboard, so this is **CLAIMED / NOT LAM-VERIFIED**, not Verified.
The DeepSeek Codex provider is intentionally separate from CC Switch, which is not
part of the intended architecture and must be left unused.
