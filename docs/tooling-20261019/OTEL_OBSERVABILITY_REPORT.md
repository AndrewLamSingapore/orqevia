# OpenTelemetry observability report - 2026-10-19

## Status

**COMPLETE for source integration and local end-to-end verification.**

Live runtime activation is disabled by default. No permanent collector or
external vendor account was added.

## Existing observability retained

- Action ledger: hash-chained JSONL under the data volume.
- Compute and queue metrics: SQLite ledgers and queue status.
- Interface telemetry: freshness-labelled system and host fields.
- Host metric collector: operator-owned JSON receipt.
- Health/canary evidence: existing tasks and receipts.

OpenTelemetry augments these controls. It does not replace the audit ledger,
queue accounting or full-stack canary.

## Implemented boundary

`app/observability.py` provides:

- optional tracer and meter providers;
- OTLP/HTTP trace and metric exporters;
- loopback-only endpoint validation;
- parent-based sampling;
- HTTP server spans and request-count/duration metrics;
- safe internal span helper;
- W3C trace-context extraction and injection;
- graceful no-op behavior when disabled;
- graceful no-op behavior and an explicit `UNAVAILABLE` result when the
  OpenTelemetry packages are absent;
- exporter isolation from request success/failure.

## Instrumented boundaries

| Boundary | Telemetry |
|---|---|
| FastAPI production entrypoint | HTTP method/route class/status, duration, error |
| Local knowledge HTTP bridge | outgoing trace context |
| Local RAG ingest/reindex/retrieve/answer | nested internal spans |
| Ollama generation request | outgoing trace context |
| Queue claim/finish | internal database spans |
| Agent job worker | job execution span, count, duration, status |
| Media provider calls | estimate/submit/status/cancel spans |
| Media SQLite lifecycle | durable-operation spans |

The protected verifier closure requires `app/provider_runtime.py` to remain
byte-identical to its reviewed revision. Outbound trace propagation was therefore
not added there; the protected file and its trust chain are unchanged.

## Privacy controls

- No request or response bodies.
- No prompts, questions, answer text or model output.
- No credentials, cookies, authorization headers or arbitrary headers.
- No raw URL path or query string.
- Only an allowlist of bounded attributes is accepted.
- Route is reduced to `health`, `pwa`, `interface`, `media`, `control`, `api` or
  `other`.
- Collector endpoint must be loopback.
- Sampling default is 10%.
- Export runs through batch/periodic processors with bounded queue and timeout.
- Telemetry exporter errors are isolated from application responses.

## Configuration

Disabled defaults:

```text
ORQEVIA_OTEL_ENABLED=0
ORQEVIA_OTEL_ENDPOINT=http://127.0.0.1:4318
ORQEVIA_OTEL_SERVICE_NAME=orqevia
ORQEVIA_OTEL_ENVIRONMENT=abex-local
ORQEVIA_OTEL_SAMPLE_RATIO=0.1
```

The backend Compose service receives these variables explicitly. The local AI
service also calls `install_observability` and receives the same environment
through its launcher.

## Verification

### Unit and integration tests

```powershell
uv run pytest -q tests/test_observability.py
```

Coverage includes:

- route-class-only HTTP attributes;
- status/error metrics;
- internal attribute allowlist;
- W3C trace propagation;
- real OTLP trace export to a loopback HTTP receiver;
- rejection of remote/non-loopback collector URLs;
- disabled mode with no network probe.

### Production entrypoint

```powershell
uv run python scripts/verify_otel_production.py
```

Observed:

```json
{
  "status": "PASS",
  "production_entrypoint": "app.production_entry:app",
  "trace_export_observed": true,
  "metric_export_observed": true,
  "private_query_absent": true,
  "prompt_capture": "DISABLED",
  "endpoint": "loopback"
}
```

### Overhead

```powershell
uv run python scripts/verify_observability.py
```

Observed over 120 requests:

```text
baseline median:      3.3227 ms
instrumented median:  3.5617 ms
median overhead:      0.2390 ms
```

This measurement is local, not a production load benchmark.

## Deployment boundary

- The source and CI are ready to build a new backend image.
- The running production backend image was not replaced in this pass.
- No collector is permanently running.
- When activated, the initial collector must remain loopback or an approved
  internal collector; arbitrary remote endpoints are rejected by code.
- Output retention and exporter destination remain an operational policy choice.

## Rollback

1. Set `ORQEVIA_OTEL_ENABLED=0`.
2. No application dependency on telemetry remains.
3. Recreate the service from the previous image if necessary.
4. Preserve action ledgers and existing queue evidence.
