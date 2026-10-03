# Isolated PRIME runtime candidate — 2026-10-03 SGT

Status: **SOURCE CANDIDATE ONLY; NOT BUILT OR DEPLOYED**. Branch
`feat/prime-runtime-candidate-20261003` starts at canonical
`main@4806694afd2729761fa108c9d64a48d8a47f54f9`, revalidated against the
remote before work. This main revision has no `app/`, `clients/`, `config/`,
`Dockerfile`, or Compose changes relative to accepted Golden Gen 2 source
`b171253566e7c879283d2aacf699ae6c1ec8988e`.

## Scoped source

- `app/ready_work.py` and `app/objective_api.py`: bounded parallel submission of
  independent objective capabilities. This does not parallelize completed model
  execution or establish a durable objective DAG.
- `app/interface_node.py` and `app/interface_contract.py`: server-issued Owner
  priority on interface submission and continuation.
- `app/job_queue.py` and `app/compute_queue_api.py`: critical-lane ordering,
  local noncritical N−1 reserve if an explicitly qualified N=2/3 is selected,
  and fail-closed N=1 fallback. The mixed-provider admission caveat remains.
- `app/context_pack.py`, `app/skill_router.py`, `config/prime_skill_registry.json`,
  and `app/agent_dispatch_api.py`: bounded, opt-in advisory context and guidance;
  neither grants tools or execution authority. Both Compose switches default off.
- `docker-compose.yml`: mirrors backend parallelism into PRIME for guarded
  admission and exposes optional measured-profile path/SHA-256 variables. All
  concurrency defaults remain N=1. No measured profile is supplied here.
- `.gitattributes`: preserves the byte-exact checkout forms of five Golden
  verification inputs on Windows. Their Git blobs and signed/accepted contents
  are unchanged.

No PWA timing/prewarm feature, benchmark harness, fake-tool fabric proof,
generated capability matrix, PDE, Lens, Cockpit, Orca, or governance status
change was transplanted. The existing Dockerfile already copies `app/` and
`config/`; no package/dependency file changed.

## Verification

- Focused runtime tests: 103 passed and 10 subtests passed.
- Full Python suite: **1,072 passed, 10 subtests passed**, five dependency/API
  deprecation warnings (no failures), on the existing ABEX test virtualenv.
- Existing PWA Node smoke suite: **55 passed**; PWA source is unchanged.
- Static Compose parse: `docker compose config --no-interpolate -q` passed.
- Golden exact-byte acceptance tests: seven targeted tests passed after the
  checkout rules were applied; protected Git blobs were not edited.
- Queue/objective DDL is unchanged. The new claim query uses SQLite
  `ROW_NUMBER`; the tested host SQLite is 3.53.1. Image-runtime SQLite has not
  been independently measured because no image build was run.

## Not yet qualified

`HOST_STABILITY=UNQUALIFIED`. No candidate image build, live PRIME/PWA Owner
journey, sustained thermal/SMART observation, deployment, rollback exercise,
service restart or Windows reboot persistence was performed. N=3 must remain
disabled until a bounded measured profile is recorded, hash-pinned in the
container, and shown compatible with configured workers, context/output limits,
model digests, memory, and observed backend parallelism. SHA-256 pinning is not
a cryptographic signature. The opt-in context/skill paths need live role-specific
quality and latency checks before enablement. The 21-agent registry still does
not prove 21 live competent workers.

Accepted Golden Gen 2 production and Golden Gen 1 rollback remain untouched.

## Thermal-hold follow-up (3 Oct, after the tested source checkpoint)

An independent review identified a mixed-provider Owner-reserve bypass and an
availability risk if an optional measured profile is malformed. A narrow
branch-only follow-up now counts all noncritical active jobs (local or cloud)
against the Owner reserve and makes malformed optional profiles fall back to
baseline N=1. Focused tests were added, and `git diff --check` passed, but the
new tests have **NOT RUN**: the ABEX SSD measured 69°C under normal use, only
1°C below Lexar's specified operating ceiling. Do not carry the prior 1,072
Python/55 PWA pass forward as verification of these new edits. No image build
or production mutation was performed. Objective capability submission still
labels every per-request task Owner/P0, so this source is not evidence of a
global 21-agent Owner-priority scheduler.

## Static-only follow-up while SSD thermal qualification is partial

Static review found that a SHA-pinned optional Compute Profile with valid
`schema`, `normal_concurrency`, and `minimum_available_mib` but missing
`context_tokens`, `output_limit`, or `models` could pass the loader and then
raise during module-level configuration validation. The isolated candidate now
validates the complete required shape before accepting a profile, with a
focused regression test for each missing field. `git diff --check` passed.
These edits and the earlier thermal-hold edits are **UNTESTED**; no Python or
PWA tests, image build, production change, or reboot was run during this
thermal hold. The prior 1,072 Python and 55 PWA passes apply only to the
earlier tested source checkpoint, not to the current branch tip.
