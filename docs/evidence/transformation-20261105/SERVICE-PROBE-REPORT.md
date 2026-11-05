# Shell-less service readiness probes - 5 November 2026

Implemented `scripts/probe_service_health.py` and `tests/test_service_health_probes.py` in the consolidated worktree. No service restart, configuration change, installation, deployment, account probe or credential resolution was performed by this task.

The on-demand CLI replaces invented container health checks with bounded, explicit evidence for the collector and the two cloudflared containers. It never exports Docker `Config.Env`, `Cmd`, raw logs, credential values or raw exception messages. Output metadata is limited to fixed container names, state, declared Docker health, normalized start time, restart count and immutable image ID.

## Actual pre-deployment observation

Receipt: `PREDEPLOY-PROBES-20261105.json`, observed `2026-11-05T00:59:29.938761+00:00`.

| Service | Result | Verified evidence | Limit |
|---|---|---|---|
| OTel collector | **UNKNOWN** | Process running; its existing loopback TCP socket accepts a connection | Existing endpoint is legacy private loopback transport. No plaintext HTTP request was sent. TLS and OTLP request acceptance remain unqualified before the parent TLS deployment. |
| cloudflared | **PASS**, scoped | Four current-process registered tunnel connections; no subsequent observed connection interruption | Current-start log evidence, not a public ingress/origin end-to-end check |
| cloudflared-dual | **PASS**, scoped | Four current-process registered tunnel connections; no subsequent observed connection interruption | Same scope; Cloudflare authentication and origin reachability were not bypassed or assumed |

Overall **UNKNOWN** is intentional because the collector has not yet demonstrated the planned HTTPS transport. It must not be rewritten as full readiness. Docker declares no container health check for these shell-less images; that absence remains explicit.

## Collector probe after TLS deployment

The script runs a short, standard-library Python helper through Docker stdin in the existing backend. It compares the configured endpoint with the expected private HTTPS origin, default `https://desktop-27lkj2v.local:4318`, and uses `/run/orqevia-tls/ca.crt` through `ssl.create_default_context`. Certificate and hostname verification remain enabled, proxies are disabled, and all redirects are rejected.

When that exact HTTPS endpoint is configured, the helper sends one `POST /v1/traces` with JSON `{}`. A 200 OTLP-compatible response, verified certificate and accepted empty payload are all required for PASS. The result states **receiver acceptance only**: an empty request cannot prove span persistence, successful export, Phoenix delivery or end-to-end tracing. Invalid JSON, unrelated JSON bodies, partial rejection, TLS failure and non-200 status cannot qualify the receiver.

Before TLS cutover, an existing loopback `http://127.0.0.1:4318` (or equivalent localhost address) is inspected with TCP connect only. No plaintext HTTP acceptance request or plaintext fallback is introduced.

## Tunnel interpretation

Docker logs are limited to the current container start and the last 300 lines. Registration, retry and disconnection events are parsed per numeric connection index. Timestamps restore order across Docker stdout/stderr buffers. Older process events and undated/unsequenced messages cannot establish current readiness; a later interruption without an observed matching reconnection prevents PASS. Missing logs, missing Docker or incomplete evidence produce UNKNOWN, not invented success. Process state other than running produces FAIL.

No public hostname, token or full tunnel configuration is needed for this scope. The script does not treat a Cloudflare authentication redirect as a successful portal journey, because it makes no such ingress request.

## Verification and use

- `uv run pytest -q tests/test_service_health_probes.py`: **21 passed**, 0 failed, 0.39s.
- Strict E9/F lint and Ruff formatting passed for both files.
- Tests cover per-connection reconnects, later failures, old/undated logs, log-stream ordering, metadata privacy, endpoint restrictions, false TLS claims, failure redaction, stopped services and Docker failure.
- The actual helper is exercised in controlled tests: legacy mode opens only a socket; TLS sends only `{}` with a CA-verifying context and rejects redirects, unrelated response bodies, partial rejection and certificate failure. No production request is made by tests.

```powershell
uv run python scripts/probe_service_health.py --output C:/Users/Admin/Documents/ABEX/operations/reboot-sweep-20261105/service-probes/POSTDEPLOY-PROBES-20261105.json
```

An explicit `--otel-https-endpoint` may select another credential-free private HTTPS origin on port 4318. The endpoint must also match the backend's actual configured endpoint before any HTTPS request is sent. Receipt files use exclusive creation; prior evidence is never overwritten. Exit status is 0 for PASS, 1 for FAIL, 2 for UNKNOWN.

The parent owns the TLS change, consolidated full suite, CI, deployment and post-deployment receipt. This task ran only small focused tests and read-only live observations. No commit or push was performed.
