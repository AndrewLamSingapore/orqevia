# Verified architecture baseline, 25 October 2026

This is an observed baseline before PIF/MEL implementation, not a production
completion claim. Source: `4d415d8528c48e9f795e5758d33f244d782cb53f`, with the
reviewed HTTPS request change `9d29c6e` and independently deployed board change
`5028b1b` reconciled on branch `codex/runtime-unrestricted-20261025`.
Unrelated worktrees and their histories remain intact.

| Component | Classification | Actual implementation and implication |
|---|---|---|
| Runtime | EXISTING AND VERIFIED | Python 3.12 FastAPI backend, separate TLS interface, Docker Compose, native local knowledge process; nine persistent services. `production_entry` extends `direct_entry`; reuse routers rather than add mandatory services. |
| Agent orchestration | EXISTING AND VERIFIED | Existing agent registry, dispatch, objectives and one shared compute worker pool. Twenty-one registered specialists do not establish twenty-one full role certifications. Keep dispatch/authorization independent from predictions. |
| Task state/history | EXISTING AND VERIFIED | `job_queue.py` persists `compute_jobs` and timestamped `compute_events`, including submitted, claimed, terminal, retry and lease events. Read through a sanitized adapter. Repeated acceptance/coaching jobs require representativeness checks. |
| Objective history | EXISTING BUT INCOMPLETE | `objective_api.py` persists objective/turn snapshots and revisions; snapshots alone do not establish complete timestamped transitions. Do not infer objective completion times from queue samples. |
| Prediction | EXISTING BUT INCOMPLETE | `predictive_intelligence.py` chronological last-value baseline and deterministic hyper-inference scores are not a Markov service. Extend interfaces; do not duplicate orchestration. |
| PIF | MISSING | No verified shared transition estimation, provenance registry, calibrated hidden-state inference or validated decision policy evaluation found. Implement optional pure-Python package; unsupported results explicitly unavailable. |
| Model registry | EXISTING AND VERIFIED | `model_registry.py`, append-only model events and local `model-registry.db`. Existing neural schema requires token fields. Capability-specific tables in the same database avoid fake token counts or a new registry service. |
| Local inference | EXISTING AND VERIFIED | Docker Ollama has Gemma3 12B/4B/1B and embeddinggemma. Native host inventory differs (1B/4B). Deep/evaluator standing policy is 12B. Existing queue/model/provider contracts remain authoritative. |
| Retrieval | EXISTING AND VERIFIED | Local MiniLM ONNX CPU, DeBERTa NLI, existing graph/FAISS/document services. MiniLM source revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, graph SHA256 `e81857e1b034a003c6dba3ae71271faa3c0ca29f8e0b06505ef2e0e6c35ab0f8`, 384 normalized dimensions. Reuse `OnnxMiniLMEncoder`; no remote-code loading. |
| Remote providers | EXISTING AND VERIFIED | Governed HF specialized route and existing external provider interfaces. Last explicit public HF test cost $0.00000155. External weights cannot be pruned locally. No automatic paid benchmarking. |
| Hardware | EXISTING AND VERIFIED | AMD Ryzen7 PRO8840HS, 8 cores/16 logical CPUs, 33,644,036,096 bytes RAM, Radeon780M iGPU. No NVIDIA device/toolchain observed. GPU compute/kernel compatibility must not be inferred from an iGPU name. |
| NVIDIA 2:4 sparse acceleration | NOT APPLICABLE | No compatible NVIDIA Tensor Core hardware observed. Ordinary transition matrices stay on CPU. Unsupported sparsity has no speedup claim. |
| MEL | EXISTING BUT INCOMPLETE | Pinned ONNX CPU inference and already quantized Ollama artifacts exist. No unified independent experiment/selection/rollback layer or representative comparative evidence found. Add optional inventory and experiment APIs; preserve baseline until task quality is validated. |
| Security/audit | EXISTING AND VERIFIED | Bound-owner HTTPS gateway, backend authority checks, trusted HttpOnly Secure sessions, scoped audit stores. PIF/MEL reuse them and grant no action authority. Defender ABEX custom scan completed with no detections; wider machine assessment remains separate. |
| Networking | EXISTING BUT INCOMPLETE | Public/local user entrypoint HTTPS8443 with trusted certificates/HSTS;8081 retired. Existing private Docker/loopback transports require coordinated TLS migration. No claim that every private hop is already TLS. New integrations and acceptance requests use verified HTTPS. |
| Tests/build/release | EXISTING AND VERIFIED | pytest, Ruff, browser checks, CodeQL, protected history checks and existing Compose release workflow. Nine CI checks passed for9d29. Existing four noncanonical regression fixture/assertion defects are documented separately; not silently omitted. |
| Live fabrics | EXISTING AND VERIFIED |630af1b passed36 scoped operations,43 contracts and260 desktop/mobile checks. Subsequent5028b1b deployment needs source-bound revalidation. This is scoped operation evidence, not every fabric roadmap feature. |

Evidence is retained under the ABEX workspace's
`operations/orqevia36-production-20261025`, `operations/system-security-20261025`
and `operations/deploy-4fcb5b9-20261025`. Significant immutable receipts include
`production-630af1b-https36.json`, `production-630af1b-https43.json`,
`browser-production-630af1b-all36-paced.json`, `publication-630af1b.json`,
`stage-9d29c6e-120-https.json` and `workspace-malware-scan.json`.

PIF and MEL will be separate packages, independent flags, health signals,
storage tables and rollback procedures. Neither is imported by core model
execution or authorized to promote models/dispatch actions on prediction alone.
CPU benchmark tooling is optional and imports heavy frameworks lazily.
Hidden-state production use, causal claims, model optimization promotion and
forecast accuracy remain NOT VERIFIED until their specific evidence exists.
