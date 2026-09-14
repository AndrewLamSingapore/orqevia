# PRIME / JARVIS

PRIME `7.3.1.1-evidence-grounded` is the only cognitive control plane for JARVIS. The Control Surface is local-only, approval-gated and no-actuation.

## One-click Dell operation

Double-click `JARVIS.cmd`, then choose:

1. Start and open Control Surface
2. Status and safety checks
3. Diagnose runtime
4. Repair and consolidate
5. Open Control Surface
6. Stop JARVIS (data retained)

The canonical Control Surface is `http://127.0.0.1:8000/control`.

The operator automatically:

- uses one stable Compose project named `prime`;
- adopts existing PRIME and Ollama volumes before superseding running legacy containers;
- writes a recovery inventory before any container replacement;
- never deletes Docker volumes or the stopped rollback container;
- detects unrelated port-8000 conflicts and leaves them untouched;
- checks `/health`, `/control`, `/api/control-surface/manifest` and `/api/status`;
- requires public `/control`, `/api/status` and the Control Surface manifest to remain HTTP 404;
- opens the browser only after every local safety gate passes.

Command-line equivalents:

```bat
JARVIS.cmd start
JARVIS.cmd status
JARVIS.cmd doctor
JARVIS.cmd repair
JARVIS.cmd open
JARVIS.cmd stop
```

To install an exact green GHCR revision and retain the current volumes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\jarvis.ps1 -Action update -Image ghcr.io/andrewlamsingapore/prime:sha-<verified-commit>
```

## Control Surface

The seven canonical views are:

- Overview: owner state, priorities, evidence and guidance.
- Conversation: read-only cognition with `remember:false`.
- Evidence: verified artifacts and reviews.
- Memory: working, episodic, semantic, procedural and protected classes with explicit retention and authority.
- System: live PRIME model and persistence counters.
- Actions: approve/modify/reject cards show risk, source, evidence, reversibility and expected effect; decisions never execute actions.
- Audit: request → evidence → reasoning route → policy → approval → result traces plus meta-review.

Direct protected APIs require the owner-controlled `PRIME_SPINE_TOKEN`; the local browser workspace does not expose or store it. The surface can record approval decisions through its trusted-local adapter, but contains no execution, automation, orchestration, consolidation, memory-write or physical-action controls.

## Frozen reasoning route

PRIME applies one testable sequence: **deterministic → local AI → confidence gate → frontier AI**. A verified deterministic result stops model use. A strong local result passes. Partial or limited local confidence may escalate only when a frontier resource is both explicitly allowed and actually available; otherwise PRIME labels the local output as a held draft and reports its gaps. Consequential work remains a proposal requiring explicit approval regardless of the reasoning route.

The current runtime has no frontier inference resource enabled. The policy is exposed read-only in `/api/control-surface/manifest`; it does not execute models or actions.

## Architecture

- PRIME: FastAPI/Uvicorn application on port 8000
- Ollama: local model runtime
- Model init: ensures configured fast/deep/embedding models exist
- Persistent PRIME and Ollama named volumes
- Optional restricted Caddy + Cloudflare integration path
- Portal integration: versioned `ExperimentCandidate` ingestion and bounded `ExperimentSpec` emission

`app/settings.py` is the only model-settings source. Compose, health checks, chat, `/api/cognitive/reason`, `/multi-reason`, and semantic memory use `OLLAMA_BASE_URL`, `PRIME_FAST_MODEL`, `PRIME_DEEP_MODEL`, and `PRIME_EMBED_MODEL`. Readiness is fail-closed until every exact configured model appears in Ollama `/api/tags`. Multi-specialist inference defaults to two concurrent workers and records specialist, critic, synthesis, and evaluation stages under one task trace.

Generated answers pass a post-inference evaluator for source coverage, unsupported claims, contradiction, uncertainty, evidence requirements, policy conformance, and task success. A failed result is withheld; the confidence gate never returns the draft as an answer.

PRIME is stateful and is not deployed to Vercel. GitHub Actions publishes the verified application image to GHCR. See `DEPLOYMENT.md` for production, rollback and physical-safety gates.

## Scalable compute

PRIME now separates fast, deep, evaluator and embedding roles, records Ollama throughput and latency, and supports explicit `compat`, `balanced` and `max` profiles. The evaluator may run on an independent model to reduce correlated errors. The protected `/api/cognitive/compute` response includes per-provider/model success rate, latency and output-token throughput.

The default Compose file remains hardware-safe. After the Dell GPU preflight passes, apply `docker-compose.gpu.yml` and tune one variable at a time. See `COMPUTE.md` for the promotion ladder. Vercel applications publish governed events to the Portal relay; PRIME pulls and acknowledges them from the private Dell runtime, so no inbound Dell exposure is required.


## Governed 29-agent queue

PRIME provides one persistent, protected compute queue for every agent. It
enforces priority/FIFO scheduling, global and per-agent concurrency, explicit
model roles, live RAM/VRAM reservations, worker timeouts, bounded retries and
per-job/daily cost ceilings. Cloud-capable or externally executing jobs are held
for an auditable owner approval. Approved cloud work remains local-first and can
burst only for an unavailable local model, insufficient local VRAM, or an
expired local wait threshold. See `COMPUTE.md`.
