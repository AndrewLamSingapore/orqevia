# Optional ONNX MiniLM embedding path

Status: active on the live ORQEVIA local knowledge service since
2026-10-19 14:14 SGT.

## Scope

ORQEVIA's local RAG path uses:

1. `sentence-transformers/all-MiniLM-L6-v2` on CPU;
2. normalized 384-dimensional vectors;
3. a FAISS index of those vectors;
4. Ollama Qwen for cited answer generation.

The optional ONNX path replaces only item 1. Ollama, FAISS, SQLite, agent
generation, routing and authority remain unchanged.

## Activated state

The active release is:

`runtime/orqevia-local-knowledge/releases/97a9f936e6d166a334ea4eb949f563d8f3c3a230-exact-onnx-20261019`

`CURRENT.json` binds the model directory, graph SHA-256 and two-thread CPU
configuration. The service reports `embedding_backend=ONNX_CPU`,
`CPUExecutionProvider`, a `READY` 29-chunk/7-document index and no
initialization error.

## Verified benchmark

The export used local model revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, ONNX opset 18 and a two-thread CPU
execution limit. The workload used the current 29-chunk RAG corpus.

| Workload | PyTorch CPU | ONNX CPU | ONNX result |
| --- | ---: | ---: | --- |
| 24 query embeddings, batch 1 | 199.4 ms p50 | 74.4 ms p50 | 2.7x faster |
| 96 document chunks, batch 8 | 2,654 ms p50 | 2,622 ms p50 | no meaningful gain |
| 96 document chunks, batch 16 | 3,008 ms p50 | 2,769 ms p50 | approximately 11% faster |

Numerical parity across 32 samples:

- minimum cosine similarity: `0.99999976`;
- maximum absolute element error: `1.6e-7`;
- identical top-1 and top-5 retrieval for all 24 test queries.

**DIRECTML STATUS: DELETED, NOT INSTALLED, AND DISABLED.** DirectML was tested
historically against the same AMD Radeon 780M environment:

- 24 query embeddings: approximately 581 ms, slower than PyTorch and CPU ONNX;
- 96 document chunks at batch 16: approximately 2,273 ms, faster than CPU for
  ingestion but unsuitable as the default interactive path.

CUDA is not available on this host. OpenVINO is not an appropriate provider for
the installed AMD CPU/GPU platform. ONNX Runtime's available providers in the
CPU package were `AzureExecutionProvider` and `CPUExecutionProvider`.

## Export

Export tooling must use a separate environment because `optimum-onnx==0.1.0`
constrains `transformers` below the version used by the current local
intelligence environment.

```powershell
uv venv C:\Users\Admin\orqevia-ai\.onnx-export
uv pip install --python C:\Users\Admin\orqevia-ai\.onnx-export\Scripts\python.exe -r requirements-local-intelligence-onnx-export.txt
C:\Users\Admin\orqevia-ai\.onnx-export\Scripts\python.exe scripts\export_minilm_onnx.py C:\Users\Admin\orqevia-ai\models\all-MiniLM-L6-v2-onnx-1110a243
```

The export is local-only and writes `onnx-manifest.json` with the source
revision, graph digest, size, opset and dimensions. Do not download model
content during service startup.

## Runtime configuration

Install only the runtime package in the local intelligence environment:

```powershell
uv pip install --python C:\Users\Admin\orqevia-ai\.venv\Scripts\python.exe -r requirements-local-intelligence-onnx-runtime.txt
```

The activation launcher reads these values from the `minilm_onnx` object in
`runtime/orqevia-local-knowledge/CURRENT.json`:

```text
ORQEVIA_MINILM_BACKEND=onnx-cpu
ORQEVIA_MINILM_ONNX_DIR=C:\Users\Admin\orqevia-ai\models\all-MiniLM-L6-v2-onnx-1110a243
ORQEVIA_MINILM_ONNX_SHA256=<model_sha256 from onnx-manifest.json>
ORQEVIA_MINILM_ONNX_THREADS=2
```

`auto` uses ONNX only when both the model directory and digest are configured.
If either value is present without the other, startup fails rather than
silently changing embedding semantics. `torch` preserves the existing backend.

## Acceptance

Acceptance completed on 2026-10-19:

1. `pytest -q tests/test_onnx_embedding.py tests/test_local_knowledge.py`
   passed **9/9**.
2. `GET /health` reports `embedding_backend=ONNX_CPU` and the pinned graph
   digest.
3. Forty-eight authenticated retrieval calls completed with zero errors.
4. The result witness SHA-256 remained
   `53d743b9a233bb57e04fd15f58c5db989461d0bed08154cd245e714707b3c24b`.
5. The current FAISS generation pointer and index files were unchanged.
6. A cited-answer request still completed through Ollama Qwen with valid
   citations.

Rollback requires restoring
`CURRENT.pre-onnx-20261019.json` and `launch.pre-onnx-20261019.py`, then
restarting the local knowledge process. The prior exact release remains
available.
