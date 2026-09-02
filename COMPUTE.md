# PRIME compute profiles

`app/settings.py` is the sole runtime settings source. Start with `balanced`, measure `/api/cognitive/compute`, then promote only if the Dell preflight and a representative benchmark remain green.

| Profile | Typical roles | Context | Parallel specialists | Use |
|---|---|---:|---:|---|
| `compat` | one small model for fast/deep/evaluator | 8K | 2 | CPU or low VRAM rollback |
| `balanced` | 4B fast, 14B deep, independent 4B evaluator | 16K | 3 | default quality/latency balance |
| `max` | hardware-fitting fast/deep/evaluator models | 32K+ | 4 | only after GPU benchmark |

GPU preflight:

```powershell
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu22.04 nvidia-smi
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Do not raise context, parallelism and model size simultaneously. Parallel Ollama requests multiply context memory. Use `average_output_tokens_per_second`, latency and success rate from the protected compute endpoint to decide each promotion.


## Governed shared agent queue

All agents submit to the persistent SQLite queue exposed under the protected
`/api/compute-queue` namespace. Requests require `Authorization: Bearer
$PRIME_SPINE_TOKEN`.

The scheduler orders ready work by priority and FIFO age, while enforcing global,
per-agent and provider concurrency. Every running job reserves its requested RAM
and VRAM until completion, failure or lease recovery. Timeouts are enforced by
worker leases and retries are bounded per job.

A job that sets `allow_cloud:true` starts in `awaiting_approval`. Approval is
necessary but not sufficient for cloud routing: the router still uses local
capacity first. Cloud becomes eligible only when the requested model/VRAM cannot
fit locally or `PRIME_CLOUD_WAIT_SECONDS` expires. An incomplete cloud provider
configuration disables cloud workers entirely.

Estimated cost must fit both the job ceiling and rolling daily ceiling before
dispatch. Actual token usage and spend are recorded in the queue ledger.
`GET /api/compute-queue/metrics` reports queue depth, reservations, providers,
policy and rolling spend.

Example submission:

```json
{
  "agent": "analyst",
  "prompt": "Produce a bounded evidence review",
  "priority": "high",
  "model_role": "deep",
  "ram_mb": 4096,
  "vram_mb": 12000,
  "timeout_seconds": 600,
  "max_retries": 2,
  "max_cost_usd": 0.50,
  "allow_cloud": true,
  "external_execution": false
}
```

Approve or reject it with `POST /api/compute-queue/jobs/{id}/approval` and a
body of `{"decision":"approved","reason":"owner-authorized burst"}`.
