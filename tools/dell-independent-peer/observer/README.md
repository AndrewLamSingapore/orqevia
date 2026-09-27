# Passive Dell observer

This is an installable starting point, not an installed service or candidate verifier.
It has not been installed on Dell from this Linux workspace. Native Windows task
registration and live Dell execution remain unproven until performed on that host.

Run `Install-DellObserver.ps1` in the native Dell user's PowerShell session with
ordinary permissions and an installed native Python 3. Existing PowerShell script
policy applies: this package supplies no policy bypass. The installer refuses a
non-Windows/non-Dell host and an existing same-name task. No administrator, stored
password, remote access credential, or ABEX endpoint is configured.

The per-user task observes at login and hourly while that user is logged in. Native
`git ls-remote` is preferred; existing `gh api` authentication is the fallback.
The fixed repository is `AndrewLamSingapore/prime`. Neither tool writes to GitHub.
Source code is never fetched, checked out, imported, run, repaired, or promoted.
The task's five-minute bound and individual command timeouts bound a run.

The observer records changes for candidate refs, `fix/` branches, phase-2 refs, and
`refs/heads/feat/supreme-integration-20260925`. The known successor reference is
`091e2f919edb1711b5a9e88404818095fa32b537`; matching it is only a reference match.
The first run preserves baseline observations. Later runs preserve discovered,
changed, and deleted refs with full observed SHA values. Ref existence is not a
freeze declaration. Tree content, annotated-tag target type, exact freeze manifest,
image, provenance, regressions, migration, rollback, and physical gates must still
be verified independently before any approval. A deleted ref's SHA is its prior
observed SHA, not a claim that the source remains remotely available.

State defaults to `%LOCALAPPDATA%\JARVIS\DellIndependentPeer\state`:

- `host-binding.json`: native manufacturer/model/computer-name/product-UUID tuple
  plus SHA-256 fingerprint. This is local observational binding, **not cryptographic
  host attestation**. It is rechecked before every remote observation.
- `inbox/*.json` and `*.sha256`: exclusive-create evidence records and digests.
  This program never overwrites them or any prior FAIL. The files are not WORM;
  an actor with filesystem write access can alter them, so retain independent
  backups and verify digests when ingesting them.
- `baseline.json`, `status.json`: replaceable derived state, atomically replaced.
- `observer.lock`: OS-managed single-instance lock, released on process exit.

The observer has no promotion authority and emits `verification=NOT_RUN`,
`promotion_verification=BLOCKED`, `frozen_candidate=false`. Software events cannot
prove audible iPhone speech. Only Owner physical observation closes that gate.
All refs remain observations until separate content and freeze-binding checks.

No raw command output, credential, or token is placed in records. Authentication
errors yield controlled BLOCKED codes and new local blocked-observation records,
without advancing the baseline. If no usable native GitHub authentication
exists, configure the native git/gh credential flow through its normal mechanism.
Do not place tokens in this package or command arguments.

To stop observation, run `Uninstall-DellObserver.ps1` on the native host. It removes
only the matching task; it retains all files and historical evidence. It does not
roll back PRIME. The observer never connects to ABEX production.

Local self-check: `python -m unittest discover -s observer -p 'test_*.py'` from
the parent package. Mocked checks validate observer behavior, not Windows Task
Scheduler operation, native Dell installation, or candidate correctness.
