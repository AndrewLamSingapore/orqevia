# ORQEVIA independent product audit — 21 October 2026

Completion classification: **PARTIALLY COMPLETE**.

This is a dated engineering observation, not an Owner promotion into STATUS.md
Verified. Core standalone operation, process reopen and local database recovery
were executed. Full model-role, physical-device and operational acceptance remain
open. A candidate, a successful test and a deployed release are distinct records.

## Identity and evidence boundary

| Item | Observed identity |
|---|---|
| Canonical repository | `AndrewLamSingapore/orqevia` |
| Canonical local directory | `C:\Users\Admin\Documents\ABEX\repos\prime` (legacy directory name) |
| Audited source baseline | `9703c9b5df92ba266acf56bfb19d85f3e10bc739` |
| Isolated candidate | `work\sovereign-five-20261021-091215\orqevia`, branch `codex/sovereign-five-20261021-091215` |
| Initial ABEX image revision | `40129767c501c1879b6deac6bb5bcd5f5d8abf6c` |
| Initial backend/interface image ID | `sha256:3e466a2d6787abc3ce306dbbe8025ccb10c24ef4e5773db82243b8053b789ef3` |
| Active Compose epoch | `orqevia-epoch-20261016`, `runtime\orqevia-epoch-20261016\docker-compose.yml` |
| Shared data volume | `orqevia-epoch-20261016-data` at `/data` |

Root coordination independently resolved canonical remote main to the baseline.
Read-only Docker identity/health/mount projections observed both backend and
interface healthy. No full container inspection, environment dump, credential
file read, restart or production objective creation was used for this audit.
`git diff --stat 4012976 9703c9b` contains only STATUS.md and the portfolio
reconciliation test: it does not establish a newer deployed application.

A subsequent read-only helper validation at 02:08:47Z observed both processes
running image `sha256:e49df199869e339100d85afdab9484016eb3710e0ca70cbd1fed1435c9607094`,
with new container IDs and the same data volume/read-only bind destinations.
`orqevia-safe-live-inventory.json` records this externally concurrent state change.
The coordinated runtime receipt must establish full source/runtime binding; the initial image is
dated history, and the audit helper did not cause a restart or deployment.
A further selected-field read observed both healthy, with OCI revision
`727562063a81d4e99ef4a5675d73d4a0447c4d78`. Local git shows this is a separate
20-file runtime change adding explicit unrestricted `ORQEVIA_OPEN_ACCESS` mode.
The original tests below exercised source9703/default controls. Source integration
has since preserved7275620 through merge `c75323b3588471c387df020a727025b51b8f55bd`,
combining the nine-file release/audit commit `b74c01b` without removing the
deployed runtime changes. The integrated candidate was retested in separate
default and explicit open-mode fixture processes, as recorded below. It has not
replaced the live image or established its actual active access configuration.

Task evidence is under
`C:\Users\Admin\Documents\ABEX\operations\sovereign-five-20261021-091215`.
The fresh test environment and scratch data are separate from the live epoch.
VELYQUA, other product source and live data were not modified in this lane.

## Actual product and implementation

README.md describes a governed operations-intelligence workspace: objectives,
bounded orchestration, durable memory, operational evidence and an authenticated
PWA. The audit follows implemented routes rather than treating that description
as acceptance evidence.

| Area | Source-backed implementation and limits |
|---|---|
| Runtime entrypoint | Dockerfile starts `app.production_entry:app`; its lifespan enters `app.direct_entry.lifespan`. The large legacy `app.main` is not this production entrypoint. |
| Core execution | `app/objective_api.py`, `app/agent_dispatch_api.py`, `app/compute_queue_api.py`, `app/project_workflows.py`: deterministic paths, bounded provider jobs, durable workflow state and recovery. Direct lifespan starts/stops workers and recovers pending workflows. |
| Interfaces | `app/interface_server.py` mounts the narrow HTTPS/PWA, session, knowledge, intelligence, workflow and product-handoff routes. `clients/pwa` contains the actual HTML/CSS/modules, recovery, service worker and local state adapters. Docker copies these assets into `app/pwa_static`. |
| Persistence | SQLite task/queue/ledger/memory/interface/workflow/session stores and artifact files under externally selected data paths. `app/action_records.py` provides hash-linked action evidence. This is not proof that every record is cryptographically signed. |
| Local/cloud intelligence | Queue/catalog/settings modules select configured local or qualified cloud providers. Cloud jobs require priced, bounded admission. Optional knowledge/media providers have their own inputs and entitlement requirements. |
| Offline behavior | `app/offline_survival.py` and `app/production_survival.py` preserve local memory and deferred work. Returning online is not authority to execute a deferred consequential operation; supported executors remain explicitly bounded. |
| Deployment | Dockerfile, docker-compose.yml and deploy/product-runtime-v1.json define independent backend/interface processes, external persistent volumes, secret/TLS references and optional profiles. No other sovereign repository is required for the tested deterministic core. |
| Observability | `app/observability.py`: opt-in telemetry, credential-free loopback OTLP, attribute filtering and disabled body/prompt capture. Compose rotates service logs. Health is narrower than product acceptance. |

Optional Portal/portfolio handoffs and public ecosystem links do not establish a
mandatory Authority Engine/Portal dependency. Local knowledge, remote model
hosting, identity, DNS/TLS and provider entitlements remain operational inputs;
independence from another repository does not remove those dependencies.

## Reproducible installation and executable evidence

Python is constrained to `>=3.12,<3.13` in pyproject.toml. A new task-local .venv
was created using installed Python 3.12.15 and the frozen uv.lock, all groups,
with automatic Python downloads disabled. Fifty-six packages installed; `uv pip
check --python .venv/Scripts/python.exe` passed. The lock SHA-256 is
`0e38e41462bc962ca2d6427c521755d394779ef3303d0375ca43af7d5fb38300`.
No global runtime or package installation was replaced.

Executed installation command, from the isolated worktree:

```powershell
uv sync --frozen --all-groups --python C:\Users\Admin\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\python.exe --no-python-downloads --cache-dir C:\Users\Admin\Documents\ABEX\operations\sovereign-five-20261021-091215\orqevia-uv-cache
uv pip check --python .venv/Scripts/python.exe
```

| Check | Result | Actual evidence |
|---|---|---|
| Baseline canonical source/security suite | PASS | `orqevia-canonical-baseline.log`, receipt: 5,184 passed and 92 subtests in 301.83s; root used isolated data at source `9703c9b`. |
| Fresh independently installed dependency closure | PASS | Frozen uv sync: 56 packages; uv pip check compatible. This checks installation consistency, not CVE absence. |
| New standalone isolation/recovery test | PASS | `orqevia-independent-pytest.xml`, one test in 11.63s. |
| Final release/isolation/runtime/workflow identity selection | PASS | `orqevia-release-verified-pytest.xml` and `orqevia-release-verified.log`: 38 passed in 16.15s, including the generated sanitized isolation receipt. |
| Integrated release/recovery plus benchmark identity | PASS | `orqevia-integrated-focused-pytest.xml` and log: 47 passed in 16.10s after preserving7275620. |
| Integrated default-security suites | PASS | `orqevia-integrated-default-pytest.xml` and log: 115 passed in 22.04s, ORQEVIA_OPEN_ACCESS absent. |
| Explicit unrestricted-mode fixtures | PASS | `orqevia-integrated-open-pytest.xml` and log: six passed in 2.80s; actions mocked and data isolated, live mode unchanged. |
| New harness strict lint | PASS | `ruff check --select E9,F` on both new regression files. |
| Integrated repository changed-file gate | PASS | scripts/check_ruff_changed.py: 24 changed Python files, four new files strictly linted/formatted. Formatting of the two preserved open-access files and removal of an unused test import do not change runtime behavior. |
| Existing image identity and health | PASS | Initial selected-field health observation above; later safe helper validated the new image/mount inventory. Root owns exact rollout/source reconciliation. |
| Candidate container build and exact-source live rollout | NOT TESTED | Root coordinates merged-source image/CI/deployment receipts. No update/publish/restart command was executed by this audit. |
| Real local model diagnostic | FAIL | Root's `orqevia-local-model-benchmark.json`: gemma3:4b passed 7/8 prompts, strict JSON failed, median 8.286s. This small diagnostic is not 21-role acceptance. |
| Full accepted model-role operation | NOT TESTED | STATUS.md records 12/21 at prior exact image; nine remain open. No new qualification is inferred. |
| Actual physical owner/member device and TLS journey | NOT TESTED | ASGI tests cannot establish physical device, browser certificate or owner usability acceptance. |
| Encrypted off-device restore and prelogon recovery | NOT TESTED | Nine local scratch DB restores do not establish these operational gates. |

The baseline suite uses an explicit list in scripts/run_canonical_ci.py. The new
files and explicit open-mode suite therefore have a CI quality step in .github/workflows/ci.yml.
The checkpoint fixture uses installed pwsh/Windows PowerShell and clearly skips
if neither exists. It never sources the operator's top-level start/update switch.

## Standalone isolation and recovery exercised

`tests/test_sovereign_isolation_20261021.py` can be rerun with:

```powershell
.venv\Scripts\python.exe -B tests/test_sovereign_isolation_20261021.py --root C:\path\to\a\new\task-only-directory
```

The root must not already exist. The harness never deletes/reuses data. It
creates an empty provider catalog, supplies only synthetic local credentials,
removes inherited service credentials, disables optional handoffs/telemetry/media,
and rejects real httpx and urllib HTTP transports. The host network settings are
unchanged. Both independent child processes recorded zero outbound attempts.

The first process runs the actual production ASGI lifespan, computes a SHA-256
objective and downloads the real generated artifact. It checks untrusted Host,
private API and missing/wrong-origin mutation rejection. With external services
unavailable it writes local semantic memory and defers a fixture remote operation
without executing it. Separate source PWA ASGI clients exercise owner/member/
anonymous authorization, replay rejection, secure HttpOnly SameSite cookies,
owned-upload isolation, filename traversal denial and trusted-device restoration.
Pairing is deliberately selected in this fixture; it does not represent the
default live access configuration.

A fresh second process imports the application again, starts its lifecycle and
verifies task state, artifact digest, memory, deferred queue and session persistence.
This is a process reopen, not merely reentering the same worker-pool object.
The backup helper then uses SQLite's online backup API and scratch restore,
checking integrity, foreign keys and exact row counts for all nine created DBs:

`agent-authority.db`, `compute-ledger.db`, `compute-queue.db`, `interface.db`,
`objectives.db`, `offline-queue.db`, `orqevia-memory.db`,
`project-workflows.db`, `pwa-sessions.db`.

This proves a bounded useful standalone workflow and recoverable test data. It
does not prove model inference, arbitrary tool execution, all UI workflows,
browser offline behavior, total data backup or independent commercial readiness.

| Sovereignty isolation gate | Result | Scope |
|---|---|---|
| Independent install | PASS | Fresh locked Python environment; no sibling repository installation. |
| Independent start | PASS | Real ASGI lifespan in two separate processes, task-only state. |
| Primary workflow | PASS | Deterministic objective → execution → artifact, not full generative workflow. |
| Data/state verification | PASS | Persisted task/artifact/memory/queue/session evidence. |
| Failure behavior | PASS | Host/auth/origin/member/cross-user-upload rejection; unavailable services. |
| Optional integrations disabled | PASS | Empty catalog, no HTTP and no portfolio handoff. |
| Core still available | PASS | Deterministic work, local memory and safe deferral remain available. |
| Independent deployment | NOT TESTED | Packaging/deployment definitions inspected; candidate image gate pending. |
| Independent recovery | PASS | Nine task DBs restored; no encrypted off-device or entire-host claim. |
| Full product sovereignty acceptance | NOT TESTED | Remaining model/device/deployment gates must retain their individual status. |

## Security findings and changes

1. **Fixed release identity defect.** publish-image.yml published `/prime`, while
   the operator accepted canonical `/orqevia:sha-*`. It also omitted the Docker
   `ORQEVIA_RUNTIME_REVISION` build arg, whose Dockerfile default is UNKNOWN.
   The workflow now publishes the canonical path and passes exact github.sha.
   Existing immutable tags, SBOM/provenance and pinned actions are preserved.
2. **Fixed credential duplication defect.** Save-Checkpoint previously saved
   unrestricted Docker inspect output, including Config.Env and command/argument
   values. It now stores selected container summary, image identity and mount
   destination/name/read-write metadata only. Host bind source paths and Config,
   Env, Cmd, Args, arbitrary labels and health output are never requested by its
   inspection helper. Volume lookup also uses a narrow mount projection. Raw
   `docker ps --no-trunc` output is replaced with selected JSON records.
3. **Executable regression.** A PowerShell AST fixture extracts reviewed
   functions only, mocks Docker and writes only to pytest's scratch directory.
   The actual Save-Checkpoint function is executed. Credential sentinels in raw
   process Command/arbitrary labels are excluded from all four saved files and
   messages; unrestricted inspect is rejected by the mock. Compose validation
   remains `config --quiet`; fully expanded Compose is not written to logs.
4. **Default perimeter at the audited baseline.** Production local requests require real
   loopback/explicit trusted peer, exact local Host and origin agreement for
   mutations. Uvicorn does not trust proxy headers. Sensitive capability checks
   require explicit owner credentials. This lane did not disable a control.
   The subsequently observed7275620 source adds explicit unrestricted-mode
   bypasses. Integrated default and open fixtures were run separately; neither
   is evidence that default-denial controls apply to a deployed open-mode instance.
   Its active mode and live permission posture must be recorded by the
   coordinated operational verification, in the context of the Owner's request.
5. **Access-mode boundary requiring operational validation.**
   app/pwa_sessions.py defaults to `ORQEVIA_PWA_ACCESS_MODE=open` with automatic
   OWNER admission. This implements the existing direct-workspace order; it is
   not anonymous-public owner authorization proof. README requires Cloudflare
   Access, TLS and server sessions. Public origin exposure and actual access
   policy must be checked together before a claim of secure deployment. This
   audit did not change live access mode, permissions or credentials.
6. **Residual risk.** Fresh dependency compatibility and regression security
   tests are not a complete vulnerability scan/penetration test. The Docker base
   tag remains mutable. Private credentials and live checkpoint retention remain
   operations responsibilities; historical checkpoints were not opened, printed
   or deleted by this repair.

## Product gaps, operations and economics

| Area | Current evidence / remaining gate |
|---|---|
| Model execution | Historical role coverage 12/21; fresh diagnostic JSON failure remains. Do not replace models or lower acceptance to hide this. |
| PWA/navigation | Real source routes and session fixture verified; current browser/physical device/TLS end-to-end acceptance is separate and pending. |
| Knowledge/intelligence | Local bridges and optional host/remote dependencies exist; this bounded harness does not certify the full corpus, FAISS service, live geospatial feeds or semantic truth. Parked forensic items remain labelled unverified. |
| Media/coaching | Implemented APIs are not proof of provider entitlement, new generation or a completed normal-work cohort. No paid calls or invented outputs. |
| Recovery | SQLite backup tooling and local restores verified; encrypted off-device backup, full artifact/config restoration, host restart/prelogon and actual owner recovery remain unverified. |
| Reliability | Actual image observed healthy; no sustained load, P95/P99, hardware power or crash/reboot qualification performed here. Health cannot certify intelligence readiness. |
| Operations | Existing CI includes canonical/offline, PWA, packaging, Docker and browser lanes. Exact candidate remote CI and rollout receipts remain separate. |
| Cost/value | Queue source has per-job/daily cost admission and priced-provider selection. Actual infrastructure bills, model/provider entitlements and electricity were not measured. No savings/ROI claim is made. |
| Commercial | Local operations/evidence value is demonstrated on a bounded task. Customer onboarding, support response, licensing of all optional assets/providers and paid reliability have not been accepted. |

## Retired names and optimization decisions

The product and active publication are ORQEVIA. Old epoch containers/volumes,
frozen manifests, signed closure bytes, historical evidence and negotiated wire
identifiers are compatibility/audit records. `app/protected_env.py` provides a
one-way ORQEVIA-to-legacy bridge for pinned modules. This audit did not blanket
rename them or create a mandatory cross-repository orchestrator. The parent
change separately repairs active retired-brand model benchmark prompts.

No lookup-table replacement for generative reasoning, consensus removal,
medical capability, mining-as-AI equivalence or new centralized runtime is
supported by these results. No speculative optimization was integrated. The
measured benefit of this change is reproducible recovery evidence and corrected
release/security behavior, not a CPU/GPU performance speedup.

## Release and rollback boundary

The user has authorized deployment of validated work. Root coordination owns
the combined commit, required CI/merge, immutable image publication and live
rollout. The lane committed the original nine files as b74c01b, preserved7275620
through merge c75323b, and prepares a reviewed PR rather than changing live state.
See the task evidence `orqevia-release-plan.md` for exact observed live identities,
additive staging and rollback precautions. No default operator start/update was
invoked: it can affect the whole stack and remove orphans. Preserve existing data,
models, TLS, provider references and historical rollback resources.

Until exact-source deployment, device/model and recovery gates are observed, the
single overall classification remains **PARTIALLY COMPLETE**.
