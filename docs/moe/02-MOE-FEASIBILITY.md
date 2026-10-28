# MoE feasibility assessment

## Recommendation

Prioritize application-level selective activation and coordination. Preserve the
existing dense 12B model for tasks that require it, validate narrow 1B uses, and
reserve cloud reasoning for explicitly eligible tasks with measured quality need.
Native MoE remains an optional benchmark, not a required migration.

Native MoE activates only some experts per token. It still needs storage and
accessible memory for the full expert weights, plus attention/KV state, working
buffers and runtime overhead. Active-parameter count is not a RAM estimate or a
guarantee of CPU speed. Independent specialist agents are not neural experts.

| Approach/candidate | Source facts | ABEX assessment |
|---|---|---|
| Qwen3-30B-A3B | 30.5B total, 3.3B active; Ollama Q4_K_M package about19GB; Apache2.0 | Weight package exceeds current Docker memory before runtime/context overhead; poor first experiment |
| gpt-oss-20b | About21B total/3.6B active; MXFP4; Apache2.0; current Ollama package about14GB | Borderline with15.29GiB engine and other services; must replace residency rather than coexist, and needs a measured memory/quality test |
| Smaller sparse MoE | Some lower-total-parameter models may fit | Feasible in principle; exact runtime, license and task quality must be checked before naming one a replacement |
| Existing21 specialist roles | One default role already selected; shared inference | Lowest-complexity first path; improve selection evaluation and eliminate repeated background work |
| Local/cloud hybrid | Existing catalog, privacy classification and accounting | Optional escalation; flagship provider readiness/price/quality not yet established |

Qwen3.5-35B-A3B is also a current Apache2.0 MoE candidate. Its active count does
not remove the full35B weight requirement. No exact ABEX-compatible quantization,
RAM measurement, CPU speed or quality result was obtained; do not recommend it
from its name or published benchmark alone.

No native-MoE model was installed or benchmarked. No task-quality non-inferiority,
tokens/sec, TTFT, context-RAM curve or licensing deployment review is claimed.
Published model benchmarks are not ABEX measurements.

GPU: the current Linux container has no compute GPU device and Ollama reports
CPU-only. Docker documents its Windows WSL2 GPU passthrough path for NVIDIA;
this machine has AMD integrated graphics. Native Windows Vulkan is a separate
possible investigation, not a verified supported Docker AMD path. No driver,
BIOS, WSL or model configuration was changed.

Primary sources checked28Oct2026:

- [Qwen3 model card](https://huggingface.co/Qwen/Qwen3-30B-A3B)
- [Ollama Qwen3 30B package](https://ollama.com/library/qwen3:30b)
- [OpenAI gpt-oss-20b model](https://developers.openai.com/api/docs/models/gpt-oss-20b)
- [OpenAI Ollama guide](https://developers.openai.com/cookbook/articles/gpt-oss/run-locally-ollama)
- [Ollama gpt-oss 20B package](https://ollama.com/library/gpt-oss:20b)
- [Qwen3.5 model card](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)
- [Docker GPU support](https://docs.docker.com/desktop/features/gpu/)
- [Ollama hardware support](https://docs.ollama.com/gpu)
