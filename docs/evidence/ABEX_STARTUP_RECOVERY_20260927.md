# ABEX Docker recovery and installed startup dependency

Observed 27 September 2026 on ABEX. Scope: restore the existing accepted runtime
and repair the Windows startup package. No production image, database, identity,
firmware, disk configuration, or PRIME.RUNTIME acceptance change.

## Failure and causal evidence

Docker Desktop's 09:33 UTC backend log records failure while renaming
`Docker/run/sailor-ingest.sock` to its `.stale` sibling (Windows error 1920).
Deleting the exact socket and deleting its reparse point also failed. A zero-byte
AF_UNIX reparse endpoint and this error do not establish SSD/NTFS corruption.
Microsoft documents that AF_UNIX bind creates a custom NTFS reparse point:
<https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/>.

The independent startup failure was a missing installed dependency. The old
guard loaded `docker-engine-probe.ps1` from the legacy runtime checkout, where
the file was absent. Its preserved startup log records that exact fail-closed
exit on 25 September at 09:57 and 13:38, and 27 September at 17:27 local time.
It therefore never reached the established socket-directory preservation path.
Earlier startup log entries preserve several successful executions of that path.

## Bounded recovery observation

The recovery operator preserved ephemeral directories by renaming them intact:

- `Docker/run.owner-access-quarantine-20260927-1800`
- `docker-secrets-engine.owner-access-quarantine-20260927-1801`
- The earlier secrets-engine `1800` preservation remains retained.

The single subsequent Docker start restored existing containers at approximately
`2026-09-27T09:59:45Z`. Original socket evidence was preserved; no deletion,
factory reset, production redeployment, re-enrollment, or Windows reboot occurred.

Root-agent read-only recovery checks reported the following. The installing
verifier additionally re-observed container identities and health independently:

- PRIME and Interface source: `b171253566e7c879283d2aacf699ae6c1ec8988e`.
- Image: `prime:phase2-audio-diagnostic-b171253`.
- Image ID: `sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5`.
- PRIME, Interface and Ollama healthy; restart counts zero; OOM false.
- Nine SQLite `quick_check` results `ok`.
- One active durable Owner device/account and one Member device preserved.
  Owner short sessions were expired; durable renewal remained available.
- Six PWA receipt asset hashes matched shell `jarvis-shell-v14`.
- TLS validated using the canonical CA; refreshed signed runtime attestation
  reported VERIFIED with the current container start time.

Physical Owner retest remains pending; server observations are not physical
phone acceptance. Read Aloud/iOS audio retains its existing parked acceptance
classification; this work makes no audio claim.

## Startup package repair and tests

Canonical source base: `0819c515d768af6c4c0189e2bddbb4a4a4a247de` (`origin/main`).
The older declared supreme branch at `135ac4a562a96e54c0c42b0c771bfa1cfd072735`
lacked newer attestation/portfolio evidence and was not used to replace source.

`deploy/windows/Start-ABEX-Survival.ps1` and the existing bounded probe are now
one sibling-file package. The guard uses `$PSScriptRoot`, not a legacy production
checkout or disposable worktree. It also rejects directory reparse targets and
an existing evidence destination before renaming. Original guard bytes were
preserved under the local private checkpoint
`recovery-records/startup-dependency-repair-20260927/` before installation.

Original guard SHA-256:
`3e84b96229d62becf44c90bcda19178568ca733b044a3909a566faa463eef3ad`.

Installed hashes independently compared with qualified source artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Start-ABEX-Survival.ps1 | 4,647 | cbe627cc56aaf7feb6498570e5d8818b58ed02e242f9dd1bf236dd7006ac64f7 |
| docker-engine-probe.ps1 | 1,110 | f00f3400fdcb9bcd7f09f3b6d7be244d6e738cdac7b6535ab5f5708d092a8cd3 |

- `pytest tests/test_windows_survival_guard.py -q`: **5 passed** on Windows.
  Includes relocated installation/healthy fixture and missing probe negative
  cases, with recovery operations forbidden in those fixtures.
- Source and installed PowerShell parsing: PASS.
- Installed healthy-engine no-op: exit 0, 18:05:32–18:05:33 +08:00.
- Receipt: `OK Docker engine was already healthy`.
- Before/after container IDs, images, start timestamps, restart counts and
  health: identical. No service restart occurred during package verification.
- `git diff --check`: PASS.

The first fixture run exposed process execution-policy handling in the test
harness (3 pass / 2 fail). The harness now uses the same process-local policy
argument as the existing Startup entry and fails on shell errors. Windows policy
was not changed. All five tests then passed; no assertion was removed.

This verifies package installation and healthy no-op behavior, not a future boot.

## Remaining host boundaries

The root-agent read-only host audit separately observed Secure Boot disabled,
two broad Docker Public-profile inbound rules, and Windows Time reporting
unsynchronized despite a measured offset below 0.2 seconds. These findings were
preserved, not repaired or silently closed. Host hardening remains subject to
the existing stop-before-repair boundary. Firmware/security settings were unchanged.

Golden Gen 2 and Golden Gen 1 rollback are preserved. The upstream socket
condition is mitigated by bounded preservation/recovery, not declared fixed.

## Later Owner connection confirmation — 18:22 +08:00

The earlier physical-retest-pending checkpoint above remains historical evidence.
After the bounded close/reopen action, the Owner reported **connected**. The
root-agent read-only canonical database check at
`2026-09-27T18:22:16+08:00` independently correlated this with one valid Owner
session, where the preceding checkpoint had zero valid Owner short sessions.

| Canonical observation | Owner | Member |
| --- | ---: | ---: |
| Total retained sessions | 6 | 4 |
| Currently valid sessions | 1 | 1 |
| Distinct accounts in those sessions | 1 | 1 |
| Durable devices, total/currently valid/distinct accounts | 1 / 1 / 1 | 1 / 1 / 1 |

The canonical Owner account count remained one; live unused enrollment codes
remained zero. This supports recovery through the existing durable enrollment
and governed session renewal. No replacement account, new enrollment code, or
diagnostic session impersonation was used.

The same check found the accepted `b171253566e7c879283d2aacf699ae6c1ec8988e`
runtime and image ID
`sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5`
unchanged. PRIME, Interface and Ollama were healthy with restart counters zero,
and their start timestamps still belonged to the 09:59:45 UTC recovery.

Scope: physical Owner **Connected** confirmation plus server-side session
correlation. No new objective round-trip or audible-output acceptance is claimed.
Earlier acceptance evidence and the parked audio classification remain intact.
