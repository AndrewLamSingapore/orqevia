# ORQEVIA monolith release qualification — 23 October 2026

ORQEVIA remains a monolith on one Windows/Docker node. The model adapters,
queue, objectives, execution records and result delivery are internal modules.
Ollama, the existing database, telemetry and ingress containers support that node.
No distributed control plane, firewall or new sandbox is introduced.

## Release scope and review

The release preserves the seven deployed commits from `651b303` through
`dd8fc6b`, then adds explicit pairing as the missing-configuration default.
An explicitly configured open-admission mode remains available; trusted devices
continue silent restoration. Review covered origin validation, owner scoping,
partial output, cache recovery, queue persistence and retained local-only defaults.

Live acceptance exposed stale connection state after successful logout. The
server had revoked access, but the browser still displayed its old access state.
The fix restores enrollment state immediately and advances the shell cache to
v32. A deferred-response regression exercises the actual client module.

The LAN TLS repair tool stages public certificates with SKI/AKI and leaf key
usage, preserving keys, subjects, SANs, validity windows and SPKI pins. It never
installs trust, exports keys or restarts production. Strict Python/OpenSSL and
browser verification must succeed before a rollout is accepted. Existing trust
anchors remain compatible with non-strict clients; strict clients need the
reissued public CA certificate in their trust store. Never disable verification.

The optional telemetry overlay records the existing collector configuration in
the owning repository. `depends_on.backend.restart: true` asks Compose to restart
the collector when a Compose operation replaces its shared backend namespace.
For an out-of-band backend replacement, explicitly recreate the collector too.

## Observed evidence

These are agent observations, not owner-only STATUS Verified claims.

| Boundary | Evidence |
| --- | --- |
| Live local gateway | Local-only job `ae3da511-d998-42eb-9449-14f9f2188eef`, `ollama-fast` / `gemma3:1b`, completed; cloud disabled. |
| Live approved cloud gateway | Job `a005f792-81c7-402c-be75-3e61992d30fe`, `hf-gemma-nano`, completed once, response POSITIVE; 27 input / 2 output tokens, computed cost $0.00000155 against $0.01 cap. Billing reconciliation was not independently checked. |
| Strict LAN TLS | Python 3.13 / OpenSSL 3.0.21, full chain and IP hostname verified; Chromium also accepted the updated trust anchor without a TLS bypass. |
| Live PWA chain | Task `72da5ba0-c24d-4d2e-9a1c-4c70848d2d0f` completed via authenticated browser submission and local inference; result persisted; Markdown downloaded and SHA-256 verified. Logout UI fix still requires acceptance on the release image. |
| Release boundary tests | 81 passed, including strict TLS handshake, wrong-hostname rejection, pairing defaults, trusted refresh and private knowledge boundary. |
| Inference fabrics | 392 passed across Hyper-Inference, MLP, registry, provider adapters, retries/circuits, budgets, cloud queue recovery and objective evidence. These are isolated deterministic tests, separate from live requests. |
| PWA logout/cache regression | 14 passed; actual module with deferred transport plus worker cache tests. |
| Host recovery | Docker API and LAN endpoint timed out while Desktop reported running. Graceful restart timed out; only Docker-owned processes and its distro were restarted. Existing containers, images and durable volumes recovered. No data was deleted. Cause of engine unresponsiveness remains unproven. |

## Inference fabric classification

- The active production path is PWA → interface → objective → queue →
  `direct_stream` (Ollama) or `cloud_execution` → result artifact and ledger.
- `ModelGateway` is a real inference adapter used by retained internal callers.
  Its frontier path requires explicit configuration and consent.
- `hyper_inference/proxies.py` explicitly uses local mocked providers. Passing
  its tests proves advisory logic and boundaries, not external model execution.
- `mlp_fabric.py` implements bounded numerical inference from JSON model data;
  training candidates and model promotion are separate operations.
- OpenAI-compatible and DeepSeek adapter tests do not establish live credentials
  or cloud qualification. Only the configured HF route received a live call.
- Media generation is a separate capability and received no billable request.

## Single-node limits and remaining qualification

The host has 32,085 MiB physical RAM and integrated Radeon graphics; observed
Ollama generation is CPU-only (`size_vram=0`). Existing queue/Ollama concurrency
remains one. Do not infer dedicated GPU capacity from Windows shared graphics
memory. A measured profile must name actual model digests, runtime version,
context/output options, memory reserve and benchmark scope.

The initial inventory had 5,580 MiB host RAM available. Container-side psutil
observes the Linux VM rather than all Windows pressure. No new memory admission
profile is activated by this release; short-prompt results cannot qualify the
maximum configured context, general reasoning quality or higher concurrency.

The measured eight-prompt run scored 6/8 for each installed generation model.
Both failed exact bare-tool-name and bare-Python formatting contracts; these are
retained failures, not evidence of general coding or tool-use qualification.
Native schema-constrained JSON passed for both; the embedding route returned
768 dimensions. Median wall latency was 5.659 seconds for 1B and 6.146 seconds
for 4B, with at least 5,565 MiB host RAM available across the two benchmark
segments. Short classification, extraction and structured-output work may use
1B; broader work retains 4B and its explicit quality limitations. N>1 remains
unqualified. No model download or silent role/configuration change was made.

A later runtime observation found an independently changed deep selection of
`gemma3:12b`. It was preserved and measured separately: 8/8 bounded contracts,
median wall time 9.198 seconds, minimum host RAM available 5,412 MiB, CPU-only.
These short tasks do not establish general coding quality or maximum context.
Native chat then reproduced a live configuration fault: at context 8192 it
returned READY in 0.222 seconds; at the configured 16384 it timed out. The
measured-context overlay restores 8192 without changing model roles, output
limits or queue concurrency. Original failed jobs and receipts remain retained.

Live navigation also exposed HTTP 429 on ordinary concurrent Intelligence reads.
Its existing two-slot bound is retained; GET requests may queue for two seconds
instead of being rejected after 50 ms. Mutation timing, authentication, body
bounds and audit requirements remain unchanged. A real six-request ASGI burst
regression verifies all reads succeed while peak execution stays at two.

Full receipts, original failures, screenshots and hashes are retained locally in
`operations/release-qualification-20261023` and the dated architecture assessment.
Application publication, CI, deployment identity and live acceptance are recorded
separately. A PR or a source-test pass alone is not deployment evidence.
