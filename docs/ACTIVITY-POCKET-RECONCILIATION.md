# Activity Pocket Factory reconciliation

Source baseline: `20bdad87a97e649eb751dd6c7add53d3fb9d65fe` (main fetched
26 October 2026). Candidate branch: `codex/activity-pocket-factory-20261026`.
This report concerns source and isolated execution, not deployed production.

## Baseline and ownership

| Component and exact owning paths | Observed implementation and integration | Reuse / missing work | Executed baseline evidence |
| --- | --- | --- | --- |
| Academy: `app/academy.py` | Ten rooms; separate training/assessment lists; in-memory only | Extend persistence and pocket feedback here; do not create another Academy | `tests/test_academy.py` |
| Persistent coaching: `app/agent_coaching.py`, `app/coaching_observation.py`, `app/coaching_exercises.py` | SQLite cohorts and bounded inference practice; does not handle extraction artifacts | Preserve this controller; Academy pocket extension shares ownership, does not launch another inference service | `tests/test_agent_coaching.py` |
| Library definitions: `app/agent_registry.py`, `config/agent_registry.json`, `config/agent_registry_migration.json` | Canonical immutable specialist IDs; aliases and frozen historical identifiers remain | Adapt canonical definitions; add artifact version storage, not another agent registry | `tests/test_agent_registry.py` |
| Skill discovery: `app/skill_router.py`, `config/prime_skill_registry.json` | Prompt guidance only; explicitly grants no tools | Preserve advisory scope; add declarative extraction artifact through Library adapter | `tests/test_skills_registry.py` |
| Skill package declarations: `skills/manifest.json`, `skills/*/SKILL.md` | Draft/advisory declarations, not runtime qualification | Preserve evidence state; do not infer qualification from manifest existence | Same registry tests; not live activation |
| Tools: `app/connector_sdk.py`, `app/sink_guard.py`, `app/action_records.py` | Handler discovery, agent eligibility and hash-chained action journal; open-access mode can bypass eligibility | Reuse dispatch/journal; enforce pocket ownership and capability intersection before dispatch, irrespective of open-access setting | `tests/test_agent_tool_library.py` |
| Qualification: `app/agent_certification.py`, `app/agent_cert_*` | Existing domain evidence projection; requires an injected authenticated verifier; registration defaults to L0 | Reuse read-only projection. Factory must never issue certifications | `tests/test_agent_certification.py` |
| Agent runtime: `app/agent_runtime.py`, `app/agent_dispatch_api.py` | Hierarchical handoffs and direct inference dispatch | Preserve; Factory does not need an inference server for deterministic extraction | Source inspected; no fresh runtime acceptance |
| Task executor: `app/workflow_engine.py` | Validated DAG, observed handlers, bounded executor, failure propagation | Reuse for extraction steps; Factory owns lifecycle and durable attempts only | `tests/test_workflow_engine.py` |
| Existing scheduling: `app/job_queue.py`, `app/compute_queue_api.py`, `app/ready_work.py`, `app/objective_api.py` | Durable compute journal and direct objective execution | Preserve production scheduling; no queue guard, consumer pool or duplicate inference engine | Source inspected; targeted Factory adapter tests needed |
| Evaluation: `app/evaluation.py`, `app/answer_evaluator.py`, `app/uief.py`, `app/repository_evaluation.py` | Domain-specific deterministic answer/score/repository measurements | Extraction exact-record acceptance belongs in Academy adapter, not a competing evaluator authority | Source inspected; Factory integration missing |
| State/memory: `app/memory.py`, `app/hybrid_memory.py`, `app/workspace_observation.py` | Existing application memory and read-only work observations | Preserve data ownership; pocket records are separate task-scoped state | Source inspected; not independently accepted here |
| API composition: `app/production_entry.py`, `app/direct_entry.py`, `app/pwa_sessions.py` | Production shell, direct execution and persistent authenticated sessions | Reuse session identity; standalone Factory app and optional ORQEVIA router adapter | Source inspected; Factory routes absent |
| Infrastructure: `Dockerfile`, `docker-compose.yml`, `scripts/run_canonical_ci.py`, `.github/workflows/ci.yml` | Python 3.12 runtime and canonical offline checks | Extend existing CI; do not change deployed service settings | Locked local Python 3.12.15 environment installed |
| Activity pockets | No existing Factory, pocket schemas, lifecycle store or extraction promotion loop found by tracked-source search | Build missing lifecycle, contracts and adapters | NOT IMPLEMENTED at baseline |

Fresh baseline command: `uv run --frozen pytest -q tests/test_academy.py
tests/test_agent_registry.py tests/test_agent_tool_library.py
tests/test_agent_coaching.py tests/test_skills_registry.py
tests/test_workflow_engine.py tests/test_agent_certification.py`.
Result: **103 passed, 1 skipped, 63 subtests passed**, 7.77 seconds.
The skipped existing test is not counted as verified. Local JUnit receipt:
`.baseline-data/baseline.xml` (untracked). No live inference or production
mutation was needed.

## Reconciliation decisions

`PLAN.md` is a dated control specification, not executable orchestration.
`docs/forensics/20261015/ARCHITECTURE_COMPONENT_INVENTORY.md` and
`AGENT_ACADEMY_RECONCILIATION.md` explicitly distinguish source presence from
deployment; their old runtime receipts are retained as history.
`governance/operational-manifest.json` and `governance/CHANNEL_CONTRACT.md`
are dated references, not a new status authority.

The existing registry and manifests contain historical PRIME/JARVIS/SSOT
identifiers and file names. The Factory uses canonical specialist definitions
without invoking a retired orchestrator, reading SSOT.json, or restoring a
retired service. Historical bytes remain intact. REA and MiroFish remain
excluded. No source is deleted merely because it is old or overlaps by name.

No second Academy, tool registry, qualification authority or task executor is
needed. Library version storage is an adapter over the current registry and
skills. A durable Factory store is needed because the existing compute journal
does not represent pockets, retention, artifact promotion or recovery fencing.

## Target topology and authority

ORQEVIA objective adapter -> Factory lifecycle -> Library canonical agent +
existing qualification projection -> existing ConnectorRegistry and workflow
executor -> structured evidence -> persistent Academy feedback and held-out
evaluation -> authenticated owner promotion -> Library artifact version ->
continued Factory execution. A standalone API and worker use the same Factory
without importing ORQEVIA orchestration.

Only trusted application composition registers sources and tool handlers.
Retrieved text and coaching artifacts cannot grant capabilities or change
policy. Candidate improvements are declarative parser settings; no generated
code, package installation or mandatory sandbox service is required. Owner
promotion remains separate from automated diagnostics and evaluation. The
latest Owner instruction removes mandatory sandboxes and queue guards; this
implementation does not add either. Resource accounting, source permissions,
authenticated ownership and emergency cancellation serve the explicit pocket
contract. No OS firewall or production configuration changes are necessary.

Acceptance will use deterministic controlled HTTPS sources, actual SQLite
restart/recovery, actual registered handlers and the existing workflow executor.
Synthetic qualification fixtures will be labelled and never represented as
production agent certification. Production deployment, actual independent
review and operational qualification must be reported separately.
