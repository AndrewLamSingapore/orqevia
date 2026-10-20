# Durable project workflows and agent notebooks

## Purpose

ORQEVIA now runs the SME profitability analysis as a registered workflow rather
than a task-specific coordinator script. The Owner starts one workflow from the
PWA. ORQEVIA then persists 21 registered-agent tasks, registry-valid handoffs,
queue references, retries, execution outputs and artifacts.

The template is `config/project_workflow_templates/sme-profitability.v1.json`.
Callers cannot supply arbitrary prompts or select additional agents.

## Execution path

1. The PWA posts financial inputs to `/pwa/api/project-workflows`.
2. The interface validates the Owner session and forwards the request to the
   loopback backend.
3. The backend validates the template and all 21 agent identities.
4. A durable run is committed to `/data/project-workflows.db`.
5. Phase-one tasks are submitted to the existing local compute queue.
6. Every queue job is linked to its task, agent, prompt hash, provider and
   result hash.
7. Phase two (`a26`) runs only after all phase-one work is terminal.
8. Phase three (`a29`) runs after the independent quality review.
9. ORQEVIA writes the report, financial results, agent matrix, execution log,
   memory test and provisional verification.
10. After a backend restart, `/verify-restart` compares the saved decision with
    the durable record and promotes the run to `COMPLETED` only when every
    applicable check passes.

## Durability and recovery

- Database: `/data/project-workflows.db`, SQLite WAL with `synchronous=FULL`.
- Artifacts: `/data/project-workflows/<project>/<run-id>/`.
- Queue: existing `/data/compute-queue.db`.
- Handoffs: existing `/data/agent-authority.db`.
- Queue submissions use deterministic idempotency keys.
- Failed tasks use a bounded retry schedule with exponential backoff.
- On backend startup, unfinished workflows are reloaded. Local queue jobs that
  belonged to a dead worker process are requeued; cloud jobs are never replayed.
- Cancellation records the request, cancels queued/running jobs where present,
  and marks unfinished tasks rather than reporting completion.

## Agent notebooks

Database: `/data/orqevia-memory.db`.

Each of the 21 registered agents receives a private, independently addressable
notebook with these sections:

- identity
- working memory
- long-term memory
- decisions
- lessons learned
- procedures
- project knowledge
- evidence
- handoffs

Record fields include memory ID, agent ID, scope, section, type, content hash,
source, source reference, evidence references, timestamps, version, verification
status, confidence, retention class, expiry, idempotency key, deletion status
and task/project identifiers.

Access rules:

- Private: owner agent, plus explicitly authenticated Owner administration.
- Project: only listed project members; writes require a write grant.
- Organization: approved knowledge only; promotion requires Owner authority.
- Every read, write, correction, deletion, search and denied access is audited.
- Verified records are versioned and superseded rather than overwritten.

Retrieval is hybrid:

- SQLite FTS5 provides exact keyword matching.
- `embeddinggemma:300m-qat-q4_0` supplies local semantic vectors.
- Missing vectors are built on demand.
- Returned notebook text is labelled untrusted reference data, never an
  instruction or authority source.

## Behavioral conditioning

Conditioning is optional and disabled by default for every agent. It can alter
decision style, challenge style, exploration, collaboration, directness and
verbosity. It cannot alter agent identity, responsibilities, permissions, tool
access, evidence requirements or task instructions. MBTI is retained only as an
optional research tag; ORQEVIA makes no claim that a type predicts superior
performance.

## PWA

`/pwa/projects.html` provides:

- one authenticated workflow start action;
- live task state;
- cancel action;
- artifact download;
- all-21 notebook directory;
- section-level records, sources and versions;
- keyword/semantic notebook search;
- memory export;
- per-agent conditioning controls.

## API

Backend-owner routes:

- `GET /api/project-workflows/templates`
- `POST /api/project-workflows`
- `GET /api/project-workflows`
- `GET /api/project-workflows/{run_id}`
- `POST /api/project-workflows/{run_id}/cancel`
- `POST /api/project-workflows/{run_id}/verify-restart`
- `GET /api/project-workflows/{run_id}/artifacts/{name}`
- `GET /api/agent-notebooks`
- `POST /api/agent-notebooks/search`
- `GET /api/agent-notebooks/{agent_id}`
- `POST /api/agent-notebooks/{agent_id}/records`
- `PATCH /api/agent-notebooks/{agent_id}/records/{memory_id}`
- `POST /api/agent-notebooks/{agent_id}/records/{memory_id}/correct`
- `DELETE /api/agent-notebooks/{agent_id}/records/{memory_id}`
- `GET /api/agent-notebooks/{agent_id}/records/{memory_id}/history`
- `GET|PUT /api/agent-notebooks/conditioning/{agent_id}`

The public PWA uses equivalent `/pwa/api/project-workflows` and
`/pwa/api/notebooks` routes. They require a valid Owner session and an
unambiguous same-origin mutation request.

## Security boundaries

- Protected certification files remain byte-identical to the reviewed revision.
- Registry dispatch is enabled through explicit environment configuration.
- Notebook search output is data, not authority.
- Workflow artifacts are served only after the authenticated owner bridge.
- Artifact downloads verify the stored SHA-256 before release.
- No credentials or hidden chain-of-thought are written to notebooks.
- Cloud execution and external side effects remain disabled in the template.

## Operational checks

```powershell
pytest tests/test_project_workflows.py tests/test_agent_notebooks.py `
       tests/test_fresh_initialization_20261016_batch.py `
       tests/test_fresh_initialization_20261019_batch.py -q
node --test clients/pwa/dashboard-tests.mjs clients/pwa/tests.mjs
curl -ksS https://192.168.1.23:8443/pwa/api/session
```

## Rollback

Before a deployment, preserve the running image IDs, Compose file, environment
file and container inspection output. To roll back:

1. Restore the previous Compose and environment snapshots.
2. Set `ORQEVIA_IMAGE` and `ORQEVIA_INTERFACE_IMAGE` to the prior image.
3. Recreate only backend and interface.
4. Re-run health, PWA, dispatch and queue checks.
5. Preserve the new workflow and notebook databases for forensic recovery;
   rollback does not require deleting them.

