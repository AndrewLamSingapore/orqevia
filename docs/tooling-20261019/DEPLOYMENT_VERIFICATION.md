# ORQEVIA tooling deployment verification - 2026-10-19

## Status

**DEPLOYED AND VERIFIED ON ABEX.**

PRs #400, #402 and #403 remediated dependency, telemetry, SSRF, cookie, regex,
error-disclosure and temporary-file findings. The final runtime revision is:

```text
97a9f936e6d166a334ea4eb949f563d8f3c3a230
```

PR #398 (`0177241`) established the initial tooling deployment. PR #400 and
the follow-up CodeQL fixes supersede its runtime image.

## Deployment identity

| Component | Deployed identity |
|---|---|
| Backend | `orqevia:tooling-20261019-97a9f93-exact` |
| Interface | `orqevia:tooling-20261019-97a9f93-exact` |
| Image ID | `sha256:bc3d591841ddd8b6cc1835051fa8fbd8ad304807ef56d8d2b952a1fbcc3eaac1` |
| OCI revision label | `97a9f936e6d166a334ea4eb949f563d8f3c3a230` |
| Loopback RAG release | `97a9f936e6d166a334ea4eb949f563d8f3c3a230-exact` |
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
- Full Python regression: **6052 passed, 20 skipped, 3 deselected,
  102 subtests passed**
- Open Dependabot alerts after merge: **0**
- Open secret-scanning alerts: **0**
- Open code-scanning alerts: **0**

FastAPI 0.143 native tracing captured request query strings by default. Native
tracing, metrics, logs, and operation spans are disabled on every ORQEVIA
FastAPI application. The ORQEVIA allowlisted middleware is the sole telemetry
source.

Five CodeQL findings were corrected in source. Eleven remaining results were
reviewed and dismissed as false positives with audit comments because artifact
identifiers are exact 32-character lowercase hex values, protected paths reject
symlinks/reparse points, and the cookie value is a revalidated 43-character
server-generated token.

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
observed: 2026-10-19T04:02:14Z
overall: PASS
checks: 12
failed: 0
SHA-256: BE539271B14BFE161489FAA2A5FC977EDF77E286DC9D19E416661A7D2FD0FE8A
```

The canary covers all nine persistent ORQEVIA containers, backend health,
qualified cloud routing, local HTTPS PWA, Cloudflare tunnel/access, same-boot
telemetry, model inventory, AI Scaffold/Fabric imports, the 21-agent registry,
fresh liveness and supervision tasks.

### Agent liveness

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-QUEUE-LIVENESS.json`

```text
observed: 2026-10-19T04:01:33Z
source_revision: 97a9f936e6d166a334ea4eb949f563d8f3c3a230
agents: 21
passed: 21
failed: 0
publication: PUBLISHED
SHA-256: 074A8A1A96E0C86B99F315BBB327E644D522285D47EF67AD39720619EF0A3F46
```

This establishes bounded queue liveness only; it is not role competence,
certification, L7, or production-readiness certification.

### RAG

```text
source revision: 97a9f93...-exact
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

- `.env.pre-codeql-20261019T035917Z`
- `orqevia:rollback-codeql-backend-20261019t035917z`
- `orqevia:rollback-codeql-interface-20261019t035917z`
- `orqevia:tooling-20261019-86e26da-exact` as the previous release image
- `orqevia:tooling-20261019-0177241-exact` as the previous exact release image
- `CURRENT.pre-tooling-20261019T0244Z.json` as the pre-tooling RAG pointer

The prior deployed product revision was `86e26da`; the pre-tooling rollback
revision remains `d5cd59f537a93292aadb9c5d4f1350c8ea7836b9`. Rollback does not
require deleting volumes, databases, RAG indexes, or evidence.
