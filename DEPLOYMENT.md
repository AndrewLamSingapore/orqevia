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

## Closed-loop runtime configuration

The complete observation-only evidence loop requires four owner-controlled values in the untracked `.env` file:

- `PRIME_INTEGRATION_TOKEN`: authenticates VELYQUA evidence events and administrative result flushes.
- `PORTAL_RESULT_URL`: exact HTTPS Portal endpoint, currently `https://the-portal-ten.vercel.app/api/experiment-result`.
- `PORTAL_RESULT_TOKEN`: shared only with The Portal production environment.
- `CLOUDFLARE_TUNNEL_TOKEN`: starts the remotely managed tunnel from Docker.
- `PRIME_PUBLIC_URL`: the persistent HTTPS hostname assigned to the restricted integration gateway.

Generate the two application tokens independently with a cryptographically secure random generator. Never commit the populated `.env`, put either token in an `EXPO_PUBLIC_*` variable, or send a token in a URL.

On Windows, after creating a remotely managed Cloudflare Tunnel and public hostname, run:

```powershell
.\scripts\bootstrap_connected_loop.ps1 `
  -PrimePublicUrl "https://prime.example.com" `
  -CloudflareTunnelToken "<owner tunnel token>"
```

Configure the Cloudflare public hostname's origin service as:

`http://integration-gateway:8080`

Then start the connected stack:

```powershell
docker compose --profile tunnel up -d --build
```

The tunnel never targets `prime:8000` directly. It targets the Caddy integration gateway, which exposes only:

- unauthenticated `GET /health`;
- authenticated `/api/integrations/*`.

All other paths, including the PRIME dashboard, return `404` through the tunnel. Local dashboard access remains `http://127.0.0.1:8000`.

## Secret handoff

The same values must be installed at the two remote boundaries:

1. Set The Portal production `PORTAL_RESULT_TOKEN` to the exact value in PRIME's local `.env`.
2. Configure the VELYQUA owner runtime with:
   - `PRIME_BASE_URL=<PRIME_PUBLIC_URL>`
   - `PRIME_INTEGRATION_TOKEN=<same PRIME token>`
3. Do not place the PRIME token in a browser bundle or public Vercel/Expo variable. A server-side or owner-secure runtime must call PRIME.

The physical scope remains observation-only. This deployment does not authorize dosing, medication, mains switching, device control or autonomous livestock care.

## Production gate

Do not deploy a revision unless `Portal Integration Verify` succeeds for that revision.

After deployment, verify in order:

1. Local `GET http://127.0.0.1:8000/health` returns `ok: true`.
2. Public `GET <PRIME_PUBLIC_URL>/health` returns `ok: true`.
3. Public `GET <PRIME_PUBLIC_URL>/api/status` returns `404`.
4. An integration request without the bearer token returns `401`.
5. POST a known `ExperimentCandidate` through the authenticated public integration gateway.
6. Confirm the returned `ExperimentSpec` is not automatically `approved`.
7. Send only synthetic, non-physical VELYQUA state and observation events.
8. Confirm PRIME persists the deterministic evaluation.
9. Flush PRIME's result outbox and confirm The Portal accepts the matching result.
10. Confirm the Portal graph receives the evidence edge without a scientific-support or actuation claim.

If any authentication, persistence, ordering or acknowledgement check fails, stop the loop, leave the outbox pending and restore the previous known-good commit-addressable image.

## Recommended target

For the current local-first design, the owner's always-on Docker laptop is the production host. A managed container VM remains an alternative only if private PRIME data and Ollama resource requirements are acceptable there.

Do not expose port 8000 directly to the public Internet. The Compose mapping binds it to `127.0.0.1`, while the optional Cloudflare profile exposes only the restricted integration gateway.
