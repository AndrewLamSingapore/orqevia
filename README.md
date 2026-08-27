# Prime

Recovered and containerized Prime 7.3.1.1 Evidence Grounded.

## Architecture

- Prime: FastAPI/Uvicorn application on port 8000
- Ollama: local model runtime
- Model init: pulls the configured fast/deep/embedding models on first startup
- Persistent application state: Docker volume mounted at `/data`
- Portal integration: versioned `ExperimentCandidate` ingestion and bounded `ExperimentSpec` emission

## Portal → PRIME integration

PRIME exposes `POST /api/integrations/portal/experiments` and `GET /api/integrations/portal/experiments/{candidate_id}` through `app.entry:app`.

The integration validates The Portal's candidate contract, routes the candidate through PRIME's bounded specialist selector, emits and validates a deterministic experiment specification, persists the handoff, and remains idempotent by canonical Portal candidate ID.

A PRIME specification may become `verified`, but it is never automatically `approved`. Consequential execution remains explicitly approval-gated.

## Run locally

1. Install Docker Desktop.
2. Optionally copy `.env.example` to `.env` and change model names.
3. Run `docker compose up --build -d`.
4. Open `http://localhost:8000`.
5. Health check: `http://localhost:8000/health`.

## Verification

GitHub Actions runs `Portal Integration Verify`, which compiles the runtime, runs unit/API/contract tests, validates a real Portal aquarium candidate, imports the composed runtime, builds the Docker image, starts the container, checks `/health`, performs a real candidate POST, and verifies persisted retrieval.

## Container registry

Pushes to `main` build and publish the Prime application image to GitHub Container Registry using GitHub Actions. The workflow uses the repository-scoped `GITHUB_TOKEN`; no personal access token is committed.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the production runtime contract, deployment gate and rollback procedure. PRIME's current persistent Docker + Ollama architecture is not targeted at Vercel/serverless hosting.

## Data and secrets

Runtime databases, model data, `.env` files, private keys, caches, and virtual environments are excluded from source control and Docker build context.
