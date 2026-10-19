# Tooling implementation report - 2026-10-19

## Status summary

| Workstream | Status | Scope |
|---|---|---|
| Node.js 22+ / Playwright | **COMPLETE** | Host installation, lockfile, PWA E2E suite, three browsers, CI |
| uv | **COMPLETE** | Pin, lock, isolated Python 3.12 environment, clean sync, CI |
| Ruff | **COMPLETE** | Tool installation, baseline, changed-file strict gate, CI |
| OpenTelemetry | **COMPLETE** | Source instrumentation, loopback OTLP verification, privacy and overhead tests, CI |

“Complete” here means implemented, integrated in source and CI, and verified in
the local environment. The live runtime image was intentionally not replaced in
this pass.

## Node.js and Playwright

Implemented:

- Added `clients/pwa/.nvmrc` with Node 22.
- Added `engines.node >=22` and `packageManager: pnpm@12.14.0`.
- Added Playwright 1.63.0 as a locked PWA dev dependency.
- Added a loopback static test server and three-browser Playwright config.
- Added shell, responsive, accessibility, manifest, service-worker, offline and
  objective-submission tests.
- Added JSON/HTML reports and failure traces/screenshots/videos.
- Added a GitHub Actions `browser-assurance` job using Node 22.
- Bumped the PWA shell from `orqevia-shell-v27` to `orqevia-shell-v28`.
- Fixed the previously hidden New Objective routing defect in `dashboard.mjs`.

Executed:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm exec playwright install chromium firefox webkit
corepack pnpm test:unit
corepack pnpm test:browser
```

Results:

- unit/browser-independent tests: 81/81 PASS;
- Playwright: 15/15 PASS;
- Chromium, Firefox and WebKit all launch and run the suite.

## uv

Implemented:

- Installed `astral-sh.uv` 0.13.1 from WinGet.
- Added `pyproject.toml` with Python `>=3.12,<3.13`.
- Added locked runtime and development dependencies plus `uv.lock`.
- Added OpenTelemetry to runtime requirements without changing the Docker Python
  base or replacing the existing lock ownership model.
- Added `requirements-local-intelligence.lock` for the separate Python 3.13
  local AI environment.
- Added a CI `tooling-governance` job using `uv sync --frozen`.

Executed:

```powershell
uv lock --python 3.12
uv sync --frozen --python 3.12 --all-groups
uv lock --check
uv sync --frozen --python 3.12 --all-groups
uv pip compile requirements-local-intelligence.txt --python-version 3.13 --python-platform windows --output-file requirements-local-intelligence.lock
uv pip install --python C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe opentelemetry-api==1.45.1 opentelemetry-sdk==1.45.1 opentelemetry-exporter-otlp-proto-http==1.45.1
uv pip check --python C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe
```

Results:

- clean environment created at Python 3.12.15;
- 57 packages resolved, 55 installed;
- frozen lock check PASS;
- local AI environment package check PASS for 91 packages.

## Ruff

Implemented:

- Installed Ruff 0.17.1 with `uv tool`.
- Added Ruff policy to `pyproject.toml`.
- Selected `E9` and `F`, with explicit legacy ignores for existing dynamic
  imports, unused compatibility imports and compressed legacy code.
- Added `scripts/check_ruff_changed.py`:
  - baseline-safe lint for all changed Python files;
  - strict `E9/F` lint for newly added Python files;
  - format check for newly added Python files.
- Added Ruff checks to CI.
- Fixed `feedback` initialization in the orchestration loop and one placeholder-
  free f-string.

Executed:

```powershell
ruff check .
python scripts/check_ruff_changed.py
ruff format --check <new Python files>
```

Results:

- full configured baseline: PASS;
- changed-file gate: PASS;
- new-file strict lint and format: PASS;
- no wholesale formatting of legacy compressed modules.

## OpenTelemetry

Implemented:

- Added disabled-by-default, loopback-only OpenTelemetry configuration.
- Added ASGI HTTP duration/status metrics and server spans.
- Added trace-context propagation to model, Higgsfield and local-knowledge HTTP
  calls.
- Added RAG ingest, reindex, retrieve and answer spans.
- Added queue claim/finish and agent job execution spans.
- Added media job/database/provider spans and job counters.
- Added strict attribute allowlists; request bodies, prompts, questions and
  arbitrary headers are not captured.
- Added batch/periodic export with bounded timeouts so exporter failure cannot
  block application requests.
- Added tests and executable loopback verification scripts.
- Added OTLP verification to CI.

Executed:

```powershell
uv run python scripts/verify_observability.py
uv run python scripts/verify_otel_production.py
uv run pytest -q tests/test_observability.py
```

Results:

- real loopback trace export: PASS;
- real loopback metric export: PASS;
- production entrypoint trace and metric export: PASS;
- private request/query sentinel absent from exported bytes: PASS;
- latest measured median overhead: 0.239 ms per request over 120 requests
  (the measurement varies with host load; it is not a production benchmark).

## Files introduced or changed

- `pyproject.toml`
- `uv.lock`
- `requirements.txt`
- `requirements-local-intelligence.txt`
- `requirements-local-intelligence.lock`
- `.env.example`
- `.gitignore`
- `docker-compose.yml`
- `clients/pwa/package.json`
- `clients/pwa/pnpm-lock.yaml`
- `clients/pwa/.nvmrc`
- `clients/pwa/sw.js`
- `clients/pwa/release.mjs`
- `clients/pwa/dashboard.mjs`
- `clients/pwa/README.md`
- `clients/pwa/playwright.config.mjs`
- `clients/pwa/browser-test-server.mjs`
- `clients/pwa/browser-tests/*`
- `app/observability.py`
- `app/job_queue.py`
- `app/provider_runtime.py`
- `app/local_knowledge.py`
- `app/local_knowledge_service.py`
- `app/local_knowledge_bridge.py`
- `app/media_generation.py`
- `app/higgsfield_media.py`
- `app/media_api.py`
- `app/production_entry.py`
- `scripts/check_ruff_changed.py`
- `scripts/verify_observability.py`
- `scripts/verify_otel_production.py`
- `.github/workflows/ci.yml`

## Security boundaries

- No credentials were added to source or reports.
- No paid service was activated for this tooling work.
- No external collector is configured.
- OTLP endpoints are rejected unless loopback.
- The PWA test server is bound to loopback only.
- Browser tests use mocked sessions/tasks and no real bearer token.
- Runtime OTLP and optional media provider are disabled in the active local
  environment by default.
