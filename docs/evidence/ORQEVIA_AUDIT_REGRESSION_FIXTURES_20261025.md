# Audit regression fixtures, 25 October 2026

Scope: four pre-existing test failures found in the wider ORQEVIA audit. Base
source: `dd68e54000576621079fe8f9d63608abfd7fca5b`. This change edits tests and
this evidence note. Production runtime, signing guards, dated evidence,
certification workflows and STATUS history are unchanged.

| Failure | Cause | Correction |
| --- | --- | --- |
| 16 October initialization dry run | A fixed historical verifier/runtime closure was compared with today's source tree | Materialize the original Git blobs and run the current dated harness against its historical domain code |
| 19 October initialization dry run | The same moving-checkout assumption; current registry semantics also differ from the original evidence | Use its own exact verifier pin and raw registry bytes, without altering evidence or current validation |
| External interface route inventory | The test omitted six existing public metadata routes | Admit exactly GET `/api/public/{jarvis,orqevia}/{agent-trace,models,platforms}` and retain the owner/other API exclusion |
| Public trace publisher signature | The test expected retired JARVIS transport headers | Check current ORQEVIA timestamp/publisher headers and recompute HMAC from the actual request body |

The dated harnesses are later than their code pins. The fixture archives the
pinned `app`, `scripts`, `config` and verifier pin file, then copies the current
dated harness, audit helper and original case evidence unchanged. A temporary
Git repository reads historical objects through an alternate to the existing
object store. It does not modify the shared repository. Raw blob writes and an
LF-only alternates file preserve bytes on Windows.

The dry run executes in a separate Python process so historical imports and
registry caches cannot contaminate current tests. Only its local data and queue
paths point at temporary fixture storage. GitHub responses are explicit test
fixtures. The real 47-file verifier and 46-file runtime closure checks, case
digests and all 29 original event oracles still execute. No signing callback,
network request, live agent dispatch, certification installation or deployment
is performed. The result remains `signature: NOT_PERFORMED`, `installed: false`
and `l7_awarded: false`.

The original tests correctly rejected today's code against old pins. Fixture
validation also exposed an LF/CRLF alternates-file problem and the current
registry's newer lead-projection validation. These failures are preserved in local audit
logs; they were resolved in test-fixture ownership rather than by weakening
production guards or rewriting old evidence.

Verification evidence is retained on ABEX under
`operations/system-security-20261025/`:

- `audit-historical-pins-v5.log` and XML: both dated modules, 5 tests passed.
- `audit-regressions-final.log` and XML: 430 passed; 12 interface setup failures
  because the command omitted the suite-required `ORQEVIA_DATA_DIR` environment.
- `audit-regressions-final-v2.log` and XML: focused changes plus adjacent
  initialization, signer, registry, interface and public-error regressions:
  **442 passed, 2 historical-custody tests deselected, 62.38 seconds**, with fresh
  `ORQEVIA_DATA_DIR` and `ORQEVIA_COMPUTE_QUEUE_DB` fixture paths.
- Strict Ruff E9/F checks on all changed Python files and `git diff --check`.

These are offline regression results. They do not renew historical admissions,
establish production health or certify operational model quality. The broader
combined platform regression and production acceptance remain separate work.
