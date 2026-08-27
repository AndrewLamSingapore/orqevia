# PRIME Deployment

PRIME is a stateful Docker application, not a serverless web application.

## Runtime contract

A production host must provide:

- Docker Compose or equivalent long-running container orchestration;
- persistent storage for PRIME `/data`;
- persistent storage for Ollama `/root/.ollama`;
- enough CPU/RAM for the configured Ollama models;
- an internal network path from PRIME to Ollama;
- TLS/reverse proxy if PRIME is exposed beyond the local machine.

Vercel is not the deployment target for the current architecture because PRIME expects a persistent process, Docker volumes, and an Ollama service.

## Canonical image

After a verified merge to `main`, GitHub Actions publishes:

`ghcr.io/andrewlamsingapore/prime:latest`

and a commit-addressable `sha-*` image.

Production should deploy the commit-addressable image, not an unpinned floating image, when rollback precision matters.

## Production gate

Do not deploy a revision unless `Portal Integration Verify` succeeds for that revision.

After deployment, verify in order:

1. `GET /health` returns `ok: true`.
2. `GET /api/status` responds; model readiness may take time on first model pull.
3. POST a known `ExperimentCandidate` to `/api/integrations/portal/experiments`.
4. Confirm the returned `ExperimentSpec` is not automatically `approved`.
5. GET the candidate by canonical ID and confirm the same experiment ID is persisted.
6. If any application or persistence check fails, redeploy the previous known-good commit-addressable image.

## Recommended target

For the current local-first design, the simplest production target is the owner's always-on Docker host (desktop, mini PC, NAS, or Linux server) running `docker compose`. A managed container VM is also suitable if private PRIME data and Ollama resource requirements are acceptable there.

Do not expose port 8000 directly to the public Internet without authentication and a TLS reverse proxy.
