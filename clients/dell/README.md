# JARVIS PRIME — Dell Interface Node client

This is a **Dell thin client**, not a PRIME runtime. ABEX remains the only authoritative scheduler, Registry, TAP, task-state owner, workflow executor, and completion authority.

## Current state

The client is implemented and locally testable, but intentionally **locked**. It will not contact ABEX until an approved HTTPS Interface Node endpoint, ABEX identity pin, and bounded client credential are supplied. It does not alter PRIME, ABEX, J Console, or any existing repository.

## Security and authority behavior

- listens only on Dell loopback (`127.0.0.1`, `::1`, or `localhost`);
- permits only HTTPS upstreams and rejects URL-embedded credentials;
- checks the ABEX hostname, authority role, protocol version, and pinned identity before task traffic;
- keeps the bearer token server-side and out of browser code;
- uses idempotency keys for objective submission;
- accepts only the adopted task states;
- automatically reconnects the status stream;
- validates every downloaded artifact against its ABEX-supplied SHA-256;
- exposes no public endpoint and contains no J Console/private-state bridge.

## Start locally in locked mode

```powershell
& 'C:\Program Files\nodejs\node.exe' .\server.mjs
```

Open `http://127.0.0.1:4317`. The UI reports exactly which connection settings are absent; this is expected.

## Activate only after ABEX contract adoption

Set the values shown in `.env.example` in the process environment. Do not put the real token in `.env.example`, source control, browser storage, or the URL.

The identity pin is SHA-256 of this exact UTF-8 JSON field order returned by `GET /interface/v1/identity`:

```json
{"hostname":"DESKTOP-BGD97NB","role":"AUTHORITATIVE_PRIME","protocolVersion":"1","publicKey":"<adopted-public-key>"}
```

The Dell client expects these ABEX routes:

- `GET /interface/v1/identity`
- `GET /interface/v1/health`
- `POST /interface/v1/objectives`
- `GET /interface/v1/tasks/{taskId}`
- `GET /interface/v1/tasks/{taskId}/events` (SSE)
- `POST /interface/v1/tasks/{taskId}/cancel`
- `GET /interface/v1/tasks/{taskId}/artifacts`
- `GET /interface/v1/artifacts/{artifactId}`

No ABEX route was assumed to exist or changed during this implementation. Contract activation requires matching the adopted ABEX implementation and provisioning its identity pin and bounded credential through the approved secret path.

## Validate

```powershell
& 'C:\Program Files\nodejs\node.exe' --test
```
