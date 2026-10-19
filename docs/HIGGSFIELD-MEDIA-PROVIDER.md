# Higgsfield optional media provider

Status: implemented as an optional, disabled-by-default provider boundary.
It is not a replacement for ORQEVIA orchestration and is not exposed to the 21
agents as a tool.

## Decision

The audited architecture did not require Higgsfield. The Owner subsequently
authorized this provider as an explicit extension. The extension remains isolated:

- ORQEVIA's model gateway, RAG, Fabric and agent registry are unchanged.
- Missing credentials make the provider unavailable, not the ORQEVIA runtime.
- No automatic provider substitution or fallback is performed.
- Production generation uses the documented asynchronous REST API.
- The CLI is used for authenticated, read-only discovery only because interactive
  OAuth commands are not suitable for unattended production jobs.

Official references:

- <https://open.higgsfield.ai/quick-start>
- <https://docs.higgsfield.ai/docs/authentication.md>
- <https://docs.higgsfield.ai/docs/concepts/requests.md>
- <https://docs.higgsfield.ai/docs/concepts/polling.md>
- <https://docs.higgsfield.ai/docs/concepts/errors.md>
- <https://docs.higgsfield.ai/docs/concepts/idempotency.md>
- <https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md>

## CLI setup verified on ABEX

```powershell
$env:PATH = 'C:\Program Files\nodejs;C:\Users\Admin\AppData\Roaming\npm;' + $env:PATH
node --version
npm --version
npm list -g --depth=0
higgsfield.cmd --version
higgsfield.cmd workspace list --json
higgsfield.cmd workspace status --json
higgsfield.cmd account status --json
higgsfield.cmd model list --json
higgsfield.cmd workflow list --json
```

The current process may inherit an older PATH than Windows Explorer. The machine
and user PATH are already correct; either start a new process or prepend the two
directories above for the current process.

The CLI stores its OAuth credentials under:

```text
C:\Users\Admin\.config\higgsfield\credentials.json
```

The inspected ACL grants access only to the Admin account, Administrators and
SYSTEM. Do not print the access or refresh token and do not copy these credentials
into ORQEVIA configuration.

## Provider configuration

The REST adapter uses a complete Higgsfield API key in the documented
`key-id:key-secret` form:

```powershell
$env:ORQEVIA_HIGGSFIELD_ENABLED='1'
$env:ORQEVIA_HIGGSFIELD_API_KEY_REF='env:ORQEVIA_HIGGSFIELD_API_KEY'
$env:ORQEVIA_HIGGSFIELD_API_KEY='<set in an approved secret store>'
$env:ORQEVIA_HIGGSFIELD_CLI='C:\Users\Admin\AppData\Roaming\npm\node_modules\@higgsfield\cli\vendor\hf.exe'
```

Alternatively, use two secret references:

```text
ORQEVIA_HIGGSFIELD_API_KEY_ID_REF=env:ORQEVIA_HIGGSFIELD_API_KEY_ID
ORQEVIA_HIGGSFIELD_API_KEY_SECRET_REF=env:ORQEVIA_HIGGSFIELD_API_KEY_SECRET
```

Never commit the key. Never place it in command-line arguments, prompts, logs,
receipts, browser code or test output. The adapter resolves credentials only at
the HTTP transport boundary.

The API base URL is fixed to `https://api.higgsfield.ai`; configuration cannot
redirect it to an arbitrary origin.

## Endpoints

All media endpoints require the existing owner bearer token.

| Method | Route | Purpose |
|---|---|---|
| GET | `/media/v1/health` | Local configuration and credential readiness |
| GET | `/media/v1/catalog` | Read-only CLI model/workflow discovery |
| POST | `/media/v1/estimate` | Free provider cost estimate |
| POST | `/media/v1/jobs` | Submit an explicitly authorized, bounded job |
| GET | `/media/v1/jobs/{request_id}` | Poll provider state |
| POST | `/media/v1/jobs/{request_id}/cancel` | Cancel a queued request |

The routes exist in source but fail closed when
`ORQEVIA_HIGGSFIELD_ENABLED` is not `1`.

## Request shape

```json
{
  "task_id": "local-operation-id",
  "operation": "image",
  "model_path": "official/model/path/from-docs",
  "payload": {
    "prompt": "A neutral product photograph"
  },
  "data_classification": "CLOUD_PERMITTED",
  "max_cost_usd": "0.10",
  "charge_authorized": true,
  "idempotency_key": "one-uuid-per-generation-intent"
}
```

The model path must come from the selected model's official API documentation.
Do not infer it from a CLI job type. The official documentation explicitly treats
the shared OpenAPI file as supplementary rather than the authoritative model
catalog.

Supported generic operation labels are `image`, `video`, `audio`, `workflow` and
`3d`. Marketing Studio, Cinematic Studio, dubbing and voice-change are discovered
as workflows and submitted through their documented media endpoint/path. The
adapter does not silently substitute a different model or environment.

## Safety controls

- Local-only, sensitive or restricted data is rejected before any provider call.
- `charge_authorized` must be explicitly `true` for submission.
- The free estimate endpoint is called before submission.
- Estimated USD must not exceed both the caller's and deployment's caps.
- Daily submission and concurrent-job limits are enforced from the local SQLite
  job store.
- One idempotency key is persisted per intended generation. An ambiguous retry
  reuses that key.
- API errors are mapped to bounded codes; raw provider error bodies and credentials
  are not returned or logged.
- Status/cancel URLs from the provider must be HTTPS on `api.higgsfield.ai`.
- Output URLs must be HTTPS and without embedded credentials.
- Signed upload URLs and upload headers are never logged.
- Completed output is retained by Higgsfield for at least seven days; ORQEVIA
  must copy durable media to its own artifact storage if longer retention is
  required.
- The CLI discovery subprocess receives a reduced environment, a fixed command
  allowlist, bounded timeouts and no shell execution.

## Provider independence

`app/media_generation.py` owns the provider-neutral request, estimate, job and
durable-store contracts. `app/higgsfield_media.py` is the optional adapter.
Future media providers can implement the same protocol without changing
orchestration, RAG or Fabrics.

The model gateway remains for reasoning/chat providers and is not reused as a
generic media queue.

## Validation

Focused tests:

```powershell
python -B -m pytest -q tests/test_media_generation.py tests/test_higgsfield_media.py
```

Regression tests must also cover:

- agent registry count remains 21;
- FastAPI route import and owner-auth denial;
- existing provider, RAG, Fabric and action-ledger tests;
- full-stack canary remains 12/12 after source integration;
- no runtime image or container was replaced during source-only validation.

## Rollback

This source integration is disabled by default. To roll back before deployment:

```powershell
git restore app/direct_entry.py
Remove-Item app/media_api.py, app/higgsfield_media.py, app/media_generation.py
Remove-Item tests/test_media_generation.py, tests/test_higgsfield_media.py
```

Do not use destructive Git reset. After a future deployment, disable the provider
first with `ORQEVIA_HIGGSFIELD_ENABLED=0`, then recreate the affected service from
the prior reviewed image. Preserve `/data/media-jobs.db` and generated media
metadata until the rollback has been verified.

