# ORQEVIA tooling deployment verification - 2026-10-19

## Status

**DEPLOYED AND VERIFIED ON ABEX.**

PR #400 passed all nine required checks and merged the security remediation as:

```text
86e26da41168f899ad04174135bc5a23765a46d9
```

PR #398 (`0177241`) established the initial tooling deployment. PR #400
supersedes its runtime image with patched web dependencies and the final
privacy boundary.

## Deployment identity

| Component | Deployed identity |
|---|---|
| Backend | `orqevia:tooling-20261019-86e26da-exact` |
| Interface | `orqevia:tooling-20261019-86e26da-exact` |
| Image ID | `sha256:376a96f6bd061e3e6375cb4d21ef7ffcf9714584f44ffeca8987c18bb6eeb95c` |
| OCI revision label | `86e26da41168f899ad04174135bc5a23765a46d9` |
| Loopback RAG release | `86e26da41168f899ad04174135bc5a23765a46d9-exact` |
| Compose project | `orqevia-epoch-20261016` |

The exact image was built from a detached Git worktree with
`core.autocrlf=false`. Seven critical source/image pairs matched byte-for-byte:

- `app/production_entry.py`
- `app/observability.py`
- `app/job_queue.py`
- `app/local_knowledge.py`
- `clients/pwa/dashboard.mjs`
- `clients/pwa/release.mjs`
- `clients/pwa/sw.js`

The separate RAG release also matched the Git blobs for
`local_knowledge.py`, `local_knowledge_service.py`,
`local_knowledge_bridge.py`, and `observability.py`.

## Security remediation

- FastAPI: `0.143.1`
- Starlette: `1.9.0`
- uvicorn: `0.54.0`
- Full Python regression: **6049 passed, 20 skipped, 3 deselected,
  102 subtests passed**
- Open Dependabot alerts after merge: **0**

FastAPI 0.143 native tracing captured request query strings by default. Native
tracing, metrics, logs, and operation spans are disabled on every ORQEVIA
FastAPI application. The ORQEVIA allowlisted middleware is the sole telemetry
source.

## GitHub checks

All required checks passed:

1. browser-assurance
2. tooling-governance
3. quality
4. isolated-verifier
5. status-authority
6. Analyze (python)
7. Analyze (javascript-typescript)
8. Analyze (actions)
9. CodeQL

## Live acceptance

### Full-stack canary

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-FULL-STACK-CANARY.json`

```text
observed: 2026-10-19T03:27:49Z
overall: PASS
checks: 12
failed: 0
SHA-256: 639C80DDD15B545B93F7838E3DE9DC823C4F42DA2C7895D6C6176BC86C9556DA
```

The canary covers all nine persistent ORQEVIA containers, backend health,
qualified cloud routing, local HTTPS PWA, Cloudflare tunnel/access, same-boot
telemetry, model inventory, AI Scaffold/Fabric imports, the 21-agent registry,
fresh liveness and supervision tasks.

### Agent liveness

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-QUEUE-LIVENESS.json`

```text
observed: 2026-10-19T03:27:19Z
source_revision: 86e26da41168f899ad04174135bc5a23765a46d9
agents: 21
passed: 21
failed: 0
publication: PUBLISHED
SHA-256: C8C71F0E610E0C0E7BB21B7CD712D78E64A13300E6EB90C9BE1F5BCB9288C933
```

This establishes bounded queue liveness only; it is not role competence,
certification, L7, or production-readiness certification.

### RAG

```text
source revision: 86e26da...-exact
generation: MODEL_INSTALLED
indexed documents: 7
retrieval: RETRIEVED, 2 hits
answer: CITED_MODEL_INTERPRETATION, model invoked, 2 citations
```

No document, question, answer, credential or owner identifier was printed.

### Deployed browser

```text
Chromium: HTTP 200, ORQEVIA, manifest present, no overflow, mobile OK, Objective route OK
Firefox:  HTTP 200, ORQEVIA, manifest present, no overflow
WebKit:   HTTP 200, ORQEVIA, manifest present, no overflow
```

The deployed PWA serves shell cache `orqevia-shell-v28` and includes the
New Objective routing repair.

### OpenTelemetry

The image imports OpenTelemetry 1.45.1 and reports status `DISABLED` under the
active policy. An in-image production-entrypoint probe observed trace and
metric export to a loopback receiver with the private query sentinel absent.
FastAPI native query capture is disabled. No external collector or paid
telemetry account was added.

## Rollback

The pre-deployment `.env` and exact container snapshots are retained:

- `.env.pre-security-20261019T032427Z`
- `orqevia:rollback-security-backend-20261019t032427z`
- `orqevia:rollback-security-interface-20261019t032427z`
- `orqevia:tooling-20261019-0177241-exact` as the previous exact release image
- `CURRENT.pre-tooling-20261019T0244Z.json` as the pre-tooling RAG pointer

The previous deployed product revision was `0177241`; the pre-tooling rollback
revision remains `d5cd59f537a93292aadb9c5d4f1350c8ea7836b9`. Rollback does not
require deleting volumes, databases, RAG indexes, or evidence.
