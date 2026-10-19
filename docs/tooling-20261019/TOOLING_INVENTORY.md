# ORQEVIA tooling inventory - 2026-10-19

Scope: ABEX host, ORQEVIA source, PWA, runtime environment, CI workflows and
existing observability. This is a factual inventory, not a production deployment
claim.

## Final CLI and runtime inventory

| Tool | Version | Location / source | Status |
|---|---:|---|---|
| Node.js | 24.20.0 | `C:\Program Files\nodejs\node.exe` | Installed, local LTS at or above Node 22 |
| npm | 11.19.0 | Node.js distribution | Installed |
| Corepack | 0.35.0 | Node.js distribution | Installed |
| pnpm | 12.14.0 | Corepack and PWA `packageManager` pin | Installed and lockfile verified |
| Playwright | 1.63.0 | PWA dev dependency | Installed |
| Chromium | 153.0.8010.12 | Playwright browser cache | Installed |
| Firefox | 155.0 | Playwright browser cache | Installed |
| WebKit | 26.6 | Playwright browser cache | Installed |
| Python host | 3.13.15 | `C:\Users\Admin\AppData\Local\Programs\Python\Python313` | Existing host utility runtime |
| Python locked environment | 3.12.15 | `C:\Users\Admin\Documents\ABEX\repos\prime\.venv` | uv-managed, production-matching version |
| Docker runtime Python | 3.12.14 | `orqevia-epoch-20261016-backend-1` | Live runtime |
| uv | 0.13.1 | `astral-sh.uv` WinGet package | Installed, hash-verified by WinGet |
| Ruff | 0.17.1 | `C:\Users\Admin\.local\bin\ruff.exe` via `uv tool` | Installed and configured |
| OpenTelemetry API/SDK | 1.45.1 | Main uv environment and local AI venv | Installed |
| OTLP HTTP exporter | 1.45.1 | Main uv environment and local AI venv | Installed |
| FastAPI | 0.143.1 | Backend lock and deployed image | Installed |
| Starlette | 1.9.0 | Patched transitive web dependency | Installed |
| uvicorn | 0.54.0 | Backend lock and deployed image | Installed |
| Git | 2.55.0.windows.5 | `C:\Program Files\Git\cmd\git.exe` | Existing |
| GitHub CLI | 2.102.0 | `C:\Program Files\GitHub CLI\gh.exe` | Existing, not authenticated |
| Docker Engine/CLI | 29.8.2 | Docker Desktop | Existing |
| Docker Compose | 5.6.0 | Docker CLI plugin | Existing |
| Ollama | 0.40.6 | Host installation | Existing |
| Hugging Face CLI | 2.2.0 | Global Python scripts | Existing |
| Higgsfield CLI | 1.2.2 | Global npm package | Existing |

## Repository-level tool ownership

| Area | Manifest / lock | Purpose |
|---|---|---|
| ORQEVIA Python | `pyproject.toml`, `uv.lock` | Reproducible Python 3.12 development and CI environment |
| Runtime container | `requirements.txt`, `Dockerfile` | Preserved pinned production dependencies; now includes OpenTelemetry |
| Existing local AI | `requirements-local-intelligence.txt`, `requirements-local-intelligence.lock` | Isolated Python 3.13 FAISS/Ollama environment |
| PWA Node | `clients/pwa/package.json`, `clients/pwa/pnpm-lock.yaml` | Node 22 minimum, pnpm and Playwright ownership |
| CI | `.github/workflows/ci.yml` | Locked Python, Ruff, Playwright and OTLP verification gates |

## Node and Playwright

- Host Node 24.20.0 satisfies the `>=22` policy and is a current LTS release.
- Product repositories that pin `.nvmrc` use Node 22.
- The PWA now pins Node 22 in `.nvmrc`, pnpm 12.14.0 in `package.json`, and
  Playwright 1.63.0 in the pnpm lockfile.
- CI uses Node 22 for the browser and existing JavaScript paths. The host uses
  Node 24 as an additional compatibility check.
- All three Playwright browser engines are installed and launch successfully.

## Python environments

- The locked ORQEVIA development environment is Python 3.12.15 with 56 installed
  packages from a 58-package `uv.lock` resolution.
- The separate local AI environment remains Python 3.13.15 and is not merged into
  the backend environment. `uv pip check` reports all 91 installed packages
  compatible.
- Production Docker remains on Python 3.12. Version ownership is now explicit in
  `pyproject.toml`.
- Python dependency installation in the existing Dockerfile remains `pip`-based
  to avoid changing the production build boundary during this tooling pass.

## Existing quality and observability systems

- `pytest.ini` owns the historical-custody marker exclusion.
- No Black, Flake8, isort, Pylint, Tox or pre-existing Ruff configuration was
  found.
- Action records provide hash-chained JSONL audit delivery.
- Queue and compute ledgers provide business outcome accounting.
- Host metrics and Interface telemetry provide read-only gauges.
- No pre-existing OpenTelemetry SDK, collector or exporter was found in the
  runtime source.

## Live runtime inventory

The live ORQEVIA-related containers were healthy before and after local tooling
verification:

- backend;
- Interface;
- Ollama;
- coaching;
- intelligence companion;
- Caddy integration gateway;
- Cloudflare tunnel;
- trust bootstrap;
- geospatial development database.

Source changes in this pass were not deployed to those containers.
