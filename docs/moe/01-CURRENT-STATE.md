# Current-state architecture

Observed 28 October 2026: 17 containers, 9 running, 8 stopped; 69 unique images,
15 volumes, 7 networks, 3 Compose projects. All five declared Docker health checks
were healthy; Caddy, two tunnels and OTel have no Docker health check. These are
scoped observations, not proof every application function is healthy.

| Exact running container | Verified purpose | Dependencies/storage |
|---|---|---|
| orqevia-epoch-20261016-backend-1 | FastAPI production entry, missions, agent dispatch, job journal | Ollama; epoch data volume; provider catalog |
| orqevia-epoch-20261016-interface-1 | HTTPS workbench and thin-client bridge | Backend; same data volume; read-only native metrics |
| orqevia-epoch-20261016-ollama-1 | Shared Ollama 0.34.2 | Epoch Ollama model volume |
| orqevia-coaching-coaching-1 | Durable coaching controller | Shared epoch data/job DB; existing HTTPS notification |
| orqevia-intelligence-1 | Intelligence API | Intelligence data volume |
| orqevia-epoch-20261016-integration-gateway-1 | Caddy integration gateway | Backend; existing Caddyfile |
| orqevia-epoch-20261016-cloudflared-1 | Cloudflare connector | Existing remote tunnel configuration |
| orqevia-epoch-20261016-cloudflared-dual-1 | Named HTTPS-origin tunnel | Interface HTTPS; trusted origin CA |
| orqevia-epoch-20261016-otel-collector-1 | Trace/metric collection and local file export | Backend network namespace; OTel data volume |

Stopped: observability stage; three local-closure stages; two older live-stage
backend/interface containers; pre-capacity intelligence; completed model-init.
They are not assumed disposable. Model-init is a successful one-shot Compose
dependency. PostgreSQL 17 and pgvector images exist without database containers.
The deployed memory/job/workflow implementations use SQLite; hybrid memory stores
embedding vectors with cosine retrieval, and notebooks support FTS5. Do not install
a duplicate database, vector store, queue, or broker on this evidence.

Host: Ryzen 7 PRO 8840HS, 8 cores/16 logical processors, 32 GB RAM, Radeon 780M.
Docker sees 15.29 GiB. Windows reports a 512 MiB graphics allocation, which is not
a verified total usable shared-GPU memory budget. WSL exposes `/dev/dxg`; the
Ollama container exposes no `/dev/dxg`, `/dev/dri` or `/dev/kfd`. Ollama reports
100% CPU execution. Thermal, fan and power telemetry were not established.
Windows Ollama supports a host knowledge-service dependency and is preserved.

| Model installed in Docker | Quantization | Manifest layer bytes |
|---|---|---:|
| gemma3:1b | Q4_K_M | 806,067,267 |
| gemma3:12b | Q4_K_M | 8,164,039,587 |
| embeddinggemma:300m-qat-q4_0 | Q4_0 | 238,539,085 |

One resident model, one parallel inference, 8192 context, two-minute retention,
q8_0 KV cache and flash-attention request settings were observed. A setting does
not prove the backend actually uses every optimization. Samples grew from 9.07
to 12.44 GiB and later 13.72 GiB during ongoing work, around 795-818% CPU.
Memory growth alone does not establish a leak. No measured OOM or material swap
pressure explained the earlier observations.

Deployed backend: f37673b4; interface: 60c5c11a; coaching: b360da9. The live output
mode remained direct and compute profile balanced. The new home_eco source is
not deployed. Direct dispatch starts a thread per job and `claim_direct()` bypasses
shared local admission. The inner HTTP stream deadline therefore includes waiting
inside Ollama. Coaching's deployed request budget is 300 seconds.

During 06:56-07:26 UTC, six completed 12B jobs took 304-333 seconds and five
background jobs failed at about 300 seconds with LOCAL_EXECUTION_TIMEOUT.
These are completion-window observations, not a controlled capacity benchmark.
Two application jobs were marked running with one configured model slot.

## All 21 registered specialists

| ID | Registered role |
|---|---|
| a01 | Strategy Lead |
| a02 | Planning and Roadmap |
| a04 | Decision and Comparison |
| a05 | Portfolio and Capacity |
| a06 | Research Lead |
| a07 | Evidence |
| a09 | Knowledge |
| a10 | Data Lead |
| a12 | Metrics and Analysis |
| a13 | Forecast |
| a14 | Data Quality |
| a15 | Engineering Lead |
| a16 | Architecture |
| a17 | Implementation |
| a18 | Test and Verification |
| a19 | Reliability |
| a20 | Commercial and Economic Lead |
| a21 | Cost and Value |
| a26 | Independent Quality Lead |
| a28 | Risk |
| a29 | Release |

The orchestrator is additional to these specialists. Registration and historical
successful model results exist for all 21; present role competence and fresh
end-to-end execution remain NOT VERIFIED. The saved 6/21 liveness result means
recent nonempty 12B success within 24 hours, not fifteen dead worker processes.

`objective_api.select_capabilities()` already returns one default specialist using
deterministic keyword scoring. Explicit capability lists can request more.
Submission fan-out is bounded to three, but this does not coordinate physical
inference across missions. Existing authority edges, workflow handoffs, notebooks,
collective records, action records and idempotency bindings are reused.

An active Hugging Face catalog route names DeepInfra Gemma 3 4B classification.
Historical journal rows mention other cloud models. Neither establishes current
provider billing, current usable credentials, or a current high-end reasoning route.
