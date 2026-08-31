# PRIME Deployment

PRIME is a stateful Docker application for the owner-controlled Dell host. Vercel is not its runtime target.

## Canonical local runtime

The repository Compose file has one stable project identity: `prime`. Do not create project-name copies such as `prime-main`, `prime_v731`, or `prime-github-ready1` for normal operation.

Run `JARVIS.cmd repair` once after installing a green release. The operator performs this order:

1. validate Docker and Compose;
2. save container, volume, network and inspect inventory under `%LOCALAPPDATA%\JARVIS\checkpoints`;
3. adopt the currently mounted PRIME `/data` and Ollama `/root/.ollama` named volumes into the untracked `.env`;
4. stop and remove only running legacy PRIME/Ollama container objects;
5. leave all volumes and stopped rollback containers intact;
6. start the `prime` project using the exact pinned image;
7. verify runtime version, integrity, Control Surface routes and no-actuation manifest;
8. when tunnel secrets are present, start the canonical restricted gateway/tunnel and supersede their running legacy container objects;
9. open the Control Surface only after the complete contract passes.

An unrelated process or container on port 8000 is a hard stop. The operator will not terminate it.

## Exact image gate

Production `.env` must pin:

```dotenv
PRIME_IMAGE=ghcr.io/andrewlamsingapore/prime:sha-<green-main-commit>
```

The update action rejects floating tags and images outside `AndrewLamSingapore/prime`.

## Required health contract

Local:

| Route | Required |
| --- | --- |
| `/health` | HTTP 200, `ok: true`, version `7.3.1.1-evidence-grounded`, integrity `ok` |
| `/control` | HTTP 200 |
| `/api/control-surface/manifest` | HTTP 200, read-only, all mutation/actuation boundaries false |
| `/api/status` | HTTP 200 |

Public restricted integration hostname, when configured:

| Route | Required |
| --- | --- |
| `/health` | HTTP 200 |
| `/control` | HTTP 404 |
| `/api/status` | HTTP 404 |
| `/api/control-surface/manifest` | HTTP 404 |

## Persistence and rollback

`JARVIS.cmd stop` uses Compose down without `--volumes`. Repair removes only replaceable running container objects after inventory; it never invokes Docker volume removal.

The existing rollback checkpoint and stopped rollback container remain outside the cleanup target. To restore, pin the checkpoint's immutable image and named volumes in `.env`, then run the status contract before accepting the rollback.

## Secrets

Keep populated `.env` values off Git, screenshots, prompts, logs and command history. Use independent high-entropy values for `PRIME_SPINE_TOKEN`, `PRIME_INTEGRATION_TOKEN`, `PORTAL_RESULT_TOKEN`, `PORTAL_PRIME_TOKEN` and the Cloudflare tunnel token.

## Physical safety boundary

This release authorizes software observation, synthetic verification and human-readable proposals only. It does not authorize dosing, mains switching, heater/filter/pump control, medication, diagnosis, autonomous livestock-care action or any other physical actuation.

