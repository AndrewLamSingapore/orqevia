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
