# Prime

Recovered and containerized Prime 7.3.1.1 Evidence Grounded.

## Architecture

- Prime: FastAPI/Uvicorn application on port 8000
- Ollama: local model runtime
- Model init: pulls the configured fast/deep/embedding models on first startup
- Persistent application state: Docker volume mounted at `/data`

## Run locally

1. Install Docker Desktop.
2. Optionally copy `.env.example` to `.env` and change model names.
3. Run `docker compose up --build -d`.
4. Open `http://localhost:8000`.
5. Health check: `http://localhost:8000/health`.

## Container registry

Pushes to `main` build and publish the Prime application image to GitHub Container Registry using GitHub Actions. The workflow uses the repository-scoped `GITHUB_TOKEN`; no personal access token is committed.

## Data and secrets

Runtime databases, model data, `.env` files, private keys, caches, and virtual environments are excluded from source control and Docker build context.
