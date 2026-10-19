# ORQEVIA regression report - 2026-10-19

## Scope and source boundary

This report separates source verification from live-runtime verification.

- Branch: `codex/tooling-assurance-20261019`
- Verified implementation commit: `18c6d2e`
- Merge commit and deployed revision:
  `86e26da41168f899ad04174135bc5a23765a46d9`
- Initial tooling deployment superseded by the security patch:
  `0177241053c2dbfcdae8b287572c6e2fb3cdc923`
- Previous live runtime source: `d5cd59f537a93292aadb9c5d4f1350c8ea7836b9`
- The backend and interface were replaced with an exact-byte image built from
  merged `main`; the loopback RAG release was promoted separately.

## Baseline

The pre-closure working baseline recorded by the preceding implementation run
was:

| Check | Baseline |
|---|---:|
| Focused Python tests after OTel/media changes | 72 passed |
| Earlier full Python suite | 6041 passed, 20 skipped, 3 deselected, 1 failed |
| Earlier full-stack canary | 12/12 passed |
| Earlier registered-agent liveness | 21/21 passed |

The one earlier full-suite failure was a protected-review cleanliness check; the
worktree contained the implementation under test. This was not counted as a
passing baseline.

## Failures found by the final pass and remediation

The first full run from a committed checkpoint produced six failures:

- five protected dependency-closure failures because `app/observability.py`
  imported OpenTelemetry as a mandatory module dependency;
- one protected verifier-closure failure because `app/provider_runtime.py` had
  been modified and the Windows worktree contained CRLF bytes for four pinned
  files.

Remediation:

1. OpenTelemetry imports now degrade to a no-op adapter when the packages are
   absent. Enabled installation reports `UNAVAILABLE`; disabled installation
   remains a no-op.
2. `app/provider_runtime.py` was restored byte-for-byte to its reviewed
   revision. Trace propagation remains at the non-protected local-knowledge,
   Ollama, and Higgsfield boundaries.
3. Four protected files were mechanically normalized from CRLF to LF in the
   working tree. Their content remains byte-identical to the pinned verifier
   revision.
4. A regression test now covers the missing-OpenTelemetry no-op path.

Evidence:

```text
protected dependency closure + initialization + observability: 14 passed
47 pinned verifier files: 0 mismatches
```

## Final source regression

Final full-suite command:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q `
  --basetemp <external-temporary-directory>
```

Final result:

```text
6049 passed, 20 skipped, 3 deselected, 6 warnings, 102 subtests passed
```

Duration: 326.73 seconds.

The five warnings are existing Starlette/FastAPI deprecations; none failed a
test.

## Workstream results

| Workstream | Final source/local result |
|---|---|
| Node.js 22+ and Playwright | 15/15 browser tests PASS; 81/81 JavaScript tests PASS |
| uv | Frozen lock and sync PASS; 55-package main environment and 91-package local-AI environment compatible |
| Ruff | Baseline, changed-file strict lint, new-file lint and format, and compile PASS |
| OpenTelemetry | Focused tests 17/17 PASS; trace, metric, production-entrypoint and privacy probes PASS |
| RAG source integration | 35 passed, 1 skipped in the focused RAG/knowledge suite |

## Live runtime regression

### Full-stack canary

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-FULL-STACK-CANARY.json`

Observed: `2026-10-19T03:27:49Z`

```text
overall: PASS
checks: 12
failed: 0
SHA-256: 639C80DDD15B545B93F7838E3DE9DC823C4F42DA2C7895D6C6176BC86C9556DA
```

The checks covered Docker engine, nine persistent ORQEVIA containers, backend
health, qualified cloud inference configuration, local TLS interface, Cloudflare
tunnel and access gate, same-boot host telemetry, Ollama models, AI Scaffold and
Fabric imports, 21-agent registry count, liveness receipt, and supervision tasks.

### Registered-agent liveness

Receipt:

`C:\Users\Admin\Documents\ABEX\operations\permanent-readiness-20261017\LATEST-QUEUE-LIVENESS.json`

Observed: `2026-10-19T03:27:19Z`

```text
agents: 21
passed: 21
failed: 0
concurrency: 1
provider: local Ollama
publication: PUBLISHED
SHA-256: C8C71F0E610E0C0E7BB21B7CD712D78E64A13300E6EB90C9BE1F5BCB9288C933
```

This proves bounded queue execution for all 21 registered agents. It is not role
competence, certification, L7, or 21/21 production readiness.

### Live RAG

A privacy-preserving probe queried the existing loopback-only local knowledge
service using existing owner authority. It reported status/counts only:

```text
generation: MODEL_INSTALLED
indexed documents: 7
retrieval: RETRIEVED, 2 hits
answer: CITED_MODEL_INTERPRETATION, model invoked, 2 citations
```

No document, question, answer, token, or owner identifier was printed.
Live ingestion was not performed during this read-only probe. Ingestion,
retrieval, answer generation, corruption handling, and citation behavior are
covered by the 35-test source suite above.

## Final comparison

| Area | Baseline | Final |
|---|---|---|
| Full Python suite | 1 known failure plus earlier passing coverage | 0 failures; 6049 passed |
| Protected verifier closure | Not yet revalidated | 47/47 files byte-identical |
| Playwright | New suite not yet final | 15/15 passed |
| JavaScript | New suite not yet final | 81/81 passed |
| Full-stack canary | 12/12 | 12/12 |
| Agent liveness | 21/21 | 21/21 |
| Live RAG | Not recorded in this tooling baseline | 7 documents; retrieval and cited answer PASS |

## Regression verdict

**No verified source or live-runtime regression remains from this pass.**

The implementation is complete at source, CI, exact-image, live deployment, and
post-deployment verification layers.
