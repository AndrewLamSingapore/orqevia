# ORQEVIA directive and deployment sweep — 20 October 2026

## Baseline

- Main and deployed source: `d4e2479bd16f77e669af10df1409cce989ae661c`
- Live image: `orqevia:release-d4e2479-20261020`
- Image digest:
  `sha256:632d3db51fbd810c49fd09f105c0ede0653bc8f8ba6c44f1ccd7dae76bfa110d`
- Backend and interface health: PASS
- Post-merge GitHub checks: 7/7 PASS
- Full local regression: 6,088 passed, 20 skipped, 3 deselected,
  102 subtests passed
- PWA unit tests: 81/81 PASS
- Scheduled full-stack canary: 16/16 PASS

## Directive reconciliation

| Directive | State | Evidence |
|---|---|---|
| Discover the actual 21-agent registry | Implemented and tested | `config/agent_registry.json`; registry-v1 checks |
| Preserve functional agent identities | Implemented | Registry identity and responsibility contracts |
| Optional MiT-style behavioral conditioning | Implemented, disabled by default | `app/agent_conditioning.py`; live `a01` profile is disabled |
| Never let style override correctness or security | Implemented | Subordination clause and adversarial tests |
| Durable notebook for every agent | Implemented and live | `/data/orqevia-memory.db`; 21 agents |
| Notebook sections | Implemented | Nine sections defined; identity, evidence and lessons are populated in the current run |
| Persistent memory and restart continuity | Implemented and tested | 63 records, 84 versions, 240 audit events; restart retrieval 21/21 |
| Private, project and organization scopes | Implemented | Scope checks and project-membership tables |
| Live project/organization memory usage | Not yet demonstrated | Current live records are private scope |
| Keyword and semantic retrieval | Implemented and live | FTS5 plus local embeddings; 63/63 indexed |
| Durable workflow orchestration | Implemented | `project-workflows.db`; 21 tasks, 21 handoffs, 6 artifacts |
| Temporary context versus durable knowledge | Implemented | Queue prompts are operational records; notebooks contain concise evidence and lessons |
| Explicit disagreement and judge resolution | Partial | Peer-review findings and deterministic judge exist; no general debate engine |
| Evaluation harness | Implemented | ORQ-001/PWA benchmark and fresh ORQ-002 cohort |
| Optional personality experiments | Implemented | Off by default; MBTI is a non-authoritative research tag |
| Data and artifact storage | Implemented for local deployment | SQLite stores, filesystem artifacts, verified backups |
| Processing pipeline | Implemented for bounded workflows | Validation, transformations, task dependencies, retries and recovery |
| Model registry and lifecycle | Missing as a first-class subsystem | Model roles are configured, but no MLflow-equivalent registry, promotion, or model rollback API exists |
| Compute infrastructure | Implemented and live | Docker services, CPU Ollama queue, healthchecks and resource admission |
| Monitoring and alerting | Implemented | Scheduled canary covers containers, tunnel, Access gate, telemetry, queue, workflow, notebooks and rollback readiness |
| Backup and restore | Tested | Full 95,899,793-byte volume copy; 17 live SQLite databases passed integrity checks |
| Release publication | Complete | PRs #414, #416 and #417 merged; main checks green |
| Deployment | Complete | Final source and image running on backend and interface |
| Rollback drill | Complete | `cb01d50` restored and healthy; persistence checked; final image restored |
| Public authenticated Owner journey | Open | Cloudflare Access is active; Edge automation navigation and post-login verification remain unproven |

## Findings closed during the sweep

1. Deployment drift was removed by rebuilding and deploying the merged main
   source.
2. A 21/21 lightweight agent-liveness cohort completed on the final image.
3. A full release rollback and restoration drill passed without data loss.
4. The coaching controller was configured for retired `gemma3:4b`, which could
   never be routed by the current queue. It now requests the configured
   `qwen2.5:14b-instruct-q4_K_M`; the previous container is retained for
   rollback.
5. Two stale unroutable certification jobs were cancelled with audit records
   preserved.
6. 114 clean local branches already merged into main were deleted after their
   names and commits were recorded.
7. Four redundant clean worktrees were removed; one nonempty worktree directory
   was moved to `archive/` for reversible cleanup.
8. An external PR that would have deleted 276 evidence and deployment files
   failed CI and was closed rather than merged.

## Current open items

- The public Owner browser journey remains unverified. The public URL returns a
  Cloudflare Access redirect, the login page returns 200, and the origin serves
  the PWA with the public Host header, but the Edge browser-automation layer
  still blocks the navigation and a transient 503 was reported during cutover.
- The fresh procurement cohort remains **98.33/100 PARTIAL** with 42/42 valid
  verdicts and 37 PASS / 5 FAIL.
- Model registry lifecycle is not implemented as a first-class subsystem.
- General-purpose structured debate and judge arbitration are not implemented
  beyond fixed workflow review phases.
- Live project and organization memory scopes have not yet been exercised with
  real cross-agent project data.
- Archived remote branches and historical evidence were retained because they
  are not proven disposable.
