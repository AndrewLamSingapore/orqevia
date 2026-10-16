# Verifier re-pin closure — 16 October 2026

Decision record: the ABEX-side resolution of `ABEX-REPIN-CHANGE-PACKAGE-20261015`
(proposing to re-pin `MAIN` and the fixture `REVISION` from `d9a4e0bd…` to the
current canonical main and to update 87 `verifier_code_revision` fields).

Authority: Owner instruction of 2026-10-16 ("DELL CANNOT RESOLVE THE VERIFIER
REPIN, YOU NEED TO RESOLVE IT") and the standing ABEX co-owner mandate. Dell did
not apply the package; the forensic record already warned against mechanical
application without exact provenance.

## Finding — no valid re-pin target exists newer than `d9a4e0bd`

The protected verifier closure (`CODE_FILES` in `scripts/sign_admitted_agent_cases.py`)
changed between `d9a4e0bd` and current canonical main in **8 files**; the runtime/oracle
closure changed in 7 of those same files relative to `ORIGINAL` (`61335a96…`). The
changes are the three 12 October 2026 fix commits (`bb99929`, `18ec939`, `b77a594`),
which arrived after `d9a4e0bd` (9 October 2026) and are part of current main.

| File | d9a4e0bd sha256 (16) | canonical main sha256 (16) | bytes |
|---|---|---|---|
| `scripts/agent_cert_reviewed_signing.py` | `905131902e37fe2c` | `a81bd8607e9f43a3` | 42173 → 42237 |
| `app/agent_cert_role_review.py` | `b8f76462d828cd91` | `f6e4a42e6f0aa179` | 12182 → 12466 |
| `app/objective_api.py` | `193c782a3726935a` | `9e0684ce093cf94a` | 38091 → 39695 |
| `app/agent_dispatch_api.py` | `cc0bcda1fbc2e017` | `3dc65e0a9eba52c7` | 48670 → 51872 |
| `app/cloud_execution.py` | `ad9743435bddeba3` | `d00edf5c832ddf4e` | 11700 → 13760 |
| `app/hf_admission.py` | `a308d57b51ea8c38` | `5a7facff33370bb3` | 7987 → 8009 |
| `app/compute_catalog.py` | `6e44c679804b6213` | `1f358907ef731c43` | 5554 → 7856 |
| `app/provider_runtime.py` | `ea64723b815a5ffe` | `1d3ee5951bf15928` | 20817 → 23201 |

Consequences, executed and observed locally on 2026-10-16:

- With `MAIN`/fixture `REVISION` re-pinned to current main: the three
  `historical_custody` tests **fail** (3 failed) — the frozen archive and the
  re-pinned revision no longer agree on the closure.
- With the existing pins: custody selection passes (3 passed, 34 deselected) and
  the default suites pass (185 passed). `unchanged_reviewer_code` against a newer
  revision denies because the archive (frozen at `d9a4e0bd`) differs from main in
  the 8 files above; `unchanged_runtime_reviewer_code(root, 61335a96…)` also
  denies on any current checkout for the same set.
- The one-shot protected fresh29 workflow must **not** be dispatched for this
  purpose: on drifted main its guarded closure would reject and permanently
  consume the batch by design.

## Decision

1. `d9a4e0bd` **is the maximal valid pin**: it is the latest revision at which the
   verifier closure and the original runtime/oracle closure are simultaneously
   byte-consistent. No newer re-pin target exists.
2. The re-pin request is **closed as not viable / superseded**. `MAIN`, the fixture
   `REVISION` and `ORIGINAL` all remain unchanged; the 87 `verifier_code_revision`
   fields keep their `d9a4e0bd` anchor.
3. Advancing initialization certification requires **re-executing** the 29 cases
   under the current verifier as a new dated evidence batch with its own
   certification — not re-pinning historical evidence.

Recorded by Codex (ABEX); not independently verified by Lam.
