# PRIME / JARVIS

PRIME `7.3.1.1-evidence-grounded` is the only cognitive control plane for JARVIS. The Control Surface is local-only, read-only and no-actuation.

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

The six canonical views are:

- Conversation: read-only cognition with `remember:false`.
- Evidence: verified artifacts and reviews.
- Memory: explicit session, episodic, durable and evidence boundaries; protected reads only.
- System: live PRIME model and persistence counters.
- Actions: proposals and approvals displayed as observation-only cards.
- Audit: filterable Stable Spine events and meta-review.

The browser tab may hold the owner-controlled `PRIME_SPINE_TOKEN` in session storage for protected reads. The surface contains no approval, rejection, execution, automation, orchestration, consolidation, memory-write or physical-action controls.

## Architecture

- PRIME: FastAPI/Uvicorn application on port 8000
- Ollama: local model runtime
- Model init: ensures configured fast/deep/embedding models exist
- Persistent PRIME and Ollama named volumes
- Optional restricted Caddy + Cloudflare integration path
- Portal integration: versioned `ExperimentCandidate` ingestion and bounded `ExperimentSpec` emission

PRIME is stateful and is not deployed to Vercel. GitHub Actions publishes the verified application image to GHCR. See `DEPLOYMENT.md` for production, rollback and physical-safety gates.

