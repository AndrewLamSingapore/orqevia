# PRIME Deployment

PRIME is a stateful Docker application, not a serverless web application.

## Runtime contract

A production host must provide:

- Docker Compose or equivalent long-running container orchestration;
- persistent storage for PRIME `/data`;
- persistent storage for Ollama `/root/.ollama`;
- enough CPU/RAM for the configured Ollama models;
- an internal network path from PRIME to Ollama;
- encrypted secret injection for cross-project tokens;
- TLS plus authenticated access if PRIME is reachable beyond the local machine.

Vercel is not the deployment target for the current architecture because PRIME expects a persistent process, Docker volumes, and an Ollama service.

## Canonical image

After a verified merge to `main`, GitHub Actions publishes:

`ghcr.io/andrewlamsingapore/prime:latest`

and a commit-addressable `sha-<40-character-commit>` image.

Production must set `PRIME_IMAGE` to the commit-addressable image. Do not use a floating image tag when rollback precision matters. The Compose file continues to support `docker compose up --build -d` for local source development.

## Required configuration

Copy `.env.example` to an untracked `.env` on the owner-controlled host and populate these values without printing or committing them:

| Variable | Purpose | Must match |
| --- | --- | --- |
| `PRIME_IMAGE` | Exact verified PRIME image | Merged, green PRIME commit |
| `PRIME_INTEGRATION_TOKEN` | Authenticates VELYQUA events to PRIME | VELYQUA runtime token |
| `PORTAL_RESULT_URL` | Authenticated result-return endpoint | Portal production `/api/experiment-result` |
| `PORTAL_RESULT_TOKEN` | Authenticates PRIME results to Portal | Portal encrypted production token |
| `PRIME_BIND_ADDRESS` | Host listener | Keep `127.0.0.1` unless a protected private network requires otherwise |
| `PRIME_PORT` | Host port | Default `8000` |

Generate independent high-entropy secrets locally. Never place populated tokens in Git, screenshots, task prompts, logs, chat, command history, or public deployment metadata.

## Always-on and remote access

The containers use `restart: unless-stopped`, health checks, bounded log rotation, persistent volumes, and graceful shutdown. The host must also start Docker automatically after login or reboot.

The Compose default binds PRIME to `127.0.0.1`. For phone or remote access, place an identity-aware private overlay or authenticated TLS reverse proxy in front of the loopback listener. Do not change the bind address to `0.0.0.0` and do not forward router port 8000 directly to the public Internet.

Remote access is not considered verified until all of the following pass from the actual phone or remote client:

1. TLS certificate and hostname validation;
2. authenticated access by the owner;
3. rejection of an unauthenticated client;
4. no direct public reachability of port 8000;
5. successful PRIME health and read-only status requests;
6. revocation and recovery procedure tested.

## Production gate

Do not deploy a revision unless `Portal Integration Verify` succeeds for that exact revision.

Before any host mutation, run the retained read-only host inventory and preserve a verified backup of the PRIME and Ollama volumes. Then:

1. pin `PRIME_IMAGE` to the exact green commit-addressable image;
2. populate the untracked runtime secrets;
3. pull and start the Compose stack;
4. wait for both Ollama and PRIME health checks to pass;
5. confirm `GET /health` returns `ok: true`;
6. confirm `GET /api/status` responds;
7. confirm a wrong integration token is rejected;
8. post only the non-physical synthetic `ExperimentCandidate` fixture;
9. confirm its `ExperimentSpec` is persisted and is not automatically `approved`;
10. deliver only synthetic VELYQUA observation events through authenticated HTTPS;
11. flush the synthetic PRIME result to Portal and verify the matching authenticated acknowledgement and graph attachment;
12. restart the stack and verify persistence;
13. verify rollback to the immediately preceding known-good image and restore the current image.

If any authentication, health, persistence, exact-revision, or rollback check fails, stop and retain or restore the previous known-good runtime.

## Physical safety boundary

This deployment authorizes software observation and synthetic verification only. It does not authorize dosing, mains switching, heater/filter/pump control, medication, diagnosis, autonomous livestock-care action, or any other physical actuation. Those capabilities require a separately approved design, qualified electrical and domain safety review, fail-safe hardware, manual override, commissioning evidence, and explicit owner approval for the exact action.

## Recommended target

For the current local-first design, the simplest production target is the owner's always-on Docker host: desktop, mini PC, NAS, or Linux server. A managed container VM is suitable only if its privacy, persistence, cost, Ollama resource, backup, access-control, and rollback requirements are explicitly accepted.
