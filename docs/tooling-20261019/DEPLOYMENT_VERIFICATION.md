# ORQEVIA tooling deployment verification - 2026-10-19

## Status

**DEPLOYED AND VERIFIED ON ABEX.**

PR #398 passed all nine required checks and merged as:

```text
0177241053c2dbfcdae8b287572c6e2fb3cdc923
```

## Deployment identity

| Component | Deployed identity |
|---|---|
| Backend | `orqevia:tooling-20261019-0177241-exact` |
| Interface | `orqevia:tooling-20261019-0177241-exact` |
| Image ID | `sha256:61c8625714cf0677ea1535e368150366b93ee0f2910d4221e4d5683df13259a9` |
| OCI revision label | `0177241053c2dbfcdae8b287572c6e2fb3cdc923` |
| Loopback RAG release | `0177241053c2dbfcdae8b287572c6e2fb3cdc923-exact` |
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
observed: 2026-10-19T02:51:12Z
overall: PASS
checks: 12
failed: 0
SHA-256: 478C57D71820B35E1D6139DCCCD0CBC5B096765576D42B538E99F01DCCD37545
```

The canary covers all nine persistent ORQEVIA containers, backend health,
qualified cloud routing, local HTTPS PWA, Cloudflare tunnel/access, same-boot
telemetry, model inventory, AI Scaffold/Fabric imports, the 21-agent registry,
fresh liveness and supervision tasks.

### Agent liveness

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-QUEUE-LIVENESS.json`

```text
observed: 2026-10-19T02:50:43Z
source_revision: 0177241053c2dbfcdae8b287572c6e2fb3cdc923
agents: 21
passed: 21
failed: 0
publication: PUBLISHED
SHA-256: 5BCA4616C1B6604763E022B2988DB9C5E2EE248EFFF9CF1F0DF0F2A621ADF2E4
```

This establishes bounded queue liveness only; it is not role competence,
certification, L7, or production-readiness certification.

### RAG

```text
source revision: 017724...-exact
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
No external collector or paid telemetry account was added.

## Rollback

The pre-deployment `.env` and exact container snapshots are retained:

- `.env.pre-tooling-20261019T024135Z`
- `orqevia:rollback-tooling-backend-20261019t024135z`
- `orqevia:rollback-tooling-interface-20261019t024135z`
- `CURRENT.pre-tooling-20261019T0244Z.json`

The previous source revision was
`d5cd59f537a93292aadb9c5d4f1350c8ea7836b9`. Rollback does not require deleting
volumes, databases, RAG indexes, or evidence.
