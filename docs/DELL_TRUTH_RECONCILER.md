> Portfolio authority: [one current JARVIS status source](https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md). This document describes this repository only; it cannot override STATUS.md, the canonical architecture, or establish live deployment status.

# Dell Truth Reconciler

> **SUPERSEDED for status purposes (22 September 2026).** The SSOT reconciler apparatus is retired. Do not install, schedule or run this reconciler; `STATUS.md` is the only current status authority. This document and the accompanying tools are retained as historical evidence, and `scripts/install_dell_truth_reconciler.ps1` now refuses to install or schedule anything unless an operator explicitly overrides the retirement.

The Truth Reconciler is an independent, deterministic Dell observer. It does not replace PRIME, ABEX, GitHub, or `STATUS.md`.

Its boundary is deliberately narrow:

- ABEX acts and remains the sole PRIME authority.
- Dell verifies local Git, remote refs, SSOT claims, preserved ABEX observations, and evidence hashes.
- GitHub is the durable software/version ledger.
- `STATUS.md` is the sole current status authority; the operational manifest is a machine-readable component reference only.
- Evidence supports or disputes claims; the reconciler never manufactures agreement.

## Run

Create a Dell-local `config.json` from `config/dell-truth-reconciler.example.json`. Populate repository paths only after each working tree has been objectively selected. Supply ABEX observations produced by the already-enrolled Interface client; a TCP connection alone is never treated as identity, task, or artifact proof.

```powershell
python -m tools.dell_truth_reconciler --config C:\path\to\config.json --fetch --repair
```

Exit code `0` means GREEN or AMBER. Exit code `2` means RED. External unavailability is AMBER when no material contradiction is proved.

`--fetch` performs only `git fetch --prune origin`. `--repair` may replace only the reconciler's derived status file. Neither mode modifies source, commits, branches, evidence, or SSOT history.

## Persistent Dell capability

`scripts/install_dell_truth_reconciler.ps1` copies the versioned implementation into `%LOCALAPPDATA%\JARVIS\TruthReconciler`. With `-RegisterTask`, it creates a per-user Windows Scheduled Task at login and every six hours. The runner has a single-instance lock, bounded runtime, append-only non-secret event records, and recovery by replacement of derived status only.

The example config is intentionally incomplete. An incomplete registry produces AMBER/UNKNOWN rather than guessing a canonical local path.

## A12/A13 readiness

The execution-record contract captures the required task, executor, repository, base/result SHAs, test execution, repair/retry counts, artifacts, hashes, remote SHA, verification state, and Dell reconciliation. It does not declare any future unfamiliar-repository trial successful. The next trial must produce a real record and evidence chain.
