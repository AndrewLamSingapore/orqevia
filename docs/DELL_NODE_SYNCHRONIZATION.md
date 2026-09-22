> Portfolio authority: [one current JARVIS status source](https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md). This document describes this repository only; it cannot override STATUS.md, the canonical architecture, or establish live deployment status.

# Dell Node Synchronization

> **Superseded for activation (22 September 2026).** This synchronizer belongs to the retired SSOT/reconciler apparatus. Do not install or schedule it; `scripts/install_dell_node_sync.ps1` now refuses to install or schedule anything unless an operator explicitly overrides the retirement. It is retained as historical evidence.

The Dell Node Synchronizer is the bounded writer companion to the independent Dell Truth Reconciler. The two roles stay separate:

- the Truth Reconciler observes and reports contradictions;
- the Node Synchronizer moves already-validated Dell work through Git and emits proposals for PRIME reconciliation;
- `STATUS.md` is the sole current status authority; `governance/operational-manifest.json` is a machine-readable component reference only;
- ABEX/PRIME remains the canonical authority.

## Safe automatic behavior

A scheduled run verifies the physical Dell hostname, exact managed repository path, canonical remote, and branch. It then fetches and performs only these automatic transitions:

- clean remote-ahead repository: fast-forward only;
- clean non-conflicting divergence: rebase unpushed Dell commits, then continue only when every commit carries validation provenance;
- validated local-ahead repository: push without force and verify the remote SHA;
- offline fetch/push: preserve local commits and queue a retry;
- dirty tree, unvalidated commit, wrong remote/branch, or semantic conflict: preserve all content and record a bounded pending item.

It never force-pushes, resets a worktree, stages arbitrary dirt, commits secrets, directly edits SSOT, or treats Dell provenance as authority.

## Validated work units

Durable Dell changes are committed only through an explicit JSON work unit containing:

- `repository_id`, `work_unit_id`, and `base_revision`;
- the exact changed `paths`;
- argument-array `validation_commands`;
- a meaningful `commit_message`.

The tool rejects changes outside the listed paths and rejects secret-like filenames or contents. Tests must pass before commit. The resulting commit records Dell origin, work-unit identity, base revision, and validation PASS trailers. A non-secret SSOT proposal is written for PRIME reconciliation after remote verification.

```powershell
python -m tools.dell_node_sync --config C:\path\config.json --work-unit C:\path\work-unit.json
```

## Restart and offline recovery

State files use atomic replacement, events are append-only, identical pending operations are deduplicated, stale process locks are recovered, and an active lock prevents concurrent runs. The installer can register a per-user task at login and every 30 minutes. When nothing changed, Git and source state remain unchanged.

The seven active Dell repositories belong in the Dell-local config only. Machine-specific paths are not committed into the canonical repository registry.
