# PWA / Interface streaming-path review (isolated candidate)

Date: 2026-10-02. Scope: source inspection only in `feat/prime-performance-20261002`; no production request, write, or latency benchmark was performed in this lane.

## Observed contract

- `app/interface_contract.py:162-178` implements `/interface/v1/tasks/{id}/events` as one bounded SSE snapshot. It hashes the current status into a cursor, emits at most one frame, and returns an empty body if `Last-Event-ID` matches. It sets `X-Event-Mode: bounded-snapshot`. This is reconnectable status polling, not a persistent token stream.
- `clients/pwa/core.mjs:103-125` reads the entire response body before parsing even `mode='sse'`; `events()` at line 141 returns a completed array. No event is rendered incrementally from this response.
- `clients/pwa/app.mjs:45-46` awaits `events()`, then awaits `status()` serially, then renders the task, and waits 2000 ms before repeating. Thus an intermediate contribution produced just after a completed cycle can wait nearly 2 seconds **plus** the next two request latencies before display. This is an architectural bound, not a measured latency.
- `clients/pwa/app.mjs:22-41` displays intermediate contributions as explicitly incomplete and records task state before updating history. This distinction must be retained.
- `clients/pwa/app.mjs:64` separately revalidates the session each 60 seconds while visible and not busy. It is not the task-update clock.
- The legacy desktop UI in `app/main.py:1778` awaits a non-streaming `/api/chat` JSON response and renders only after completion. `app/main.py:525` also invokes Ollama with `stream:false`. This is a separate path from the governed PWA task path; do not conflate either with the Codex desktop UI complaint.

## What is not established

No timings of PRIME receipt, model first token, generation, Interface processing, browser fetch, DOM paint, or owner-visible output were collected here. Therefore these code paths are plausible contributors but **not yet a measured dominant bottleneck**. The server's synchronous task-status work, model runtime, and agent handoffs may dominate instead.

## Smallest safe next candidate and proof

First instrument a genuine authorized PWA objective end to end with monotonic timestamps at submit, first authoritative task receipt, each events/status request start and end, first nonempty contribution, render completion, and terminal result. Correlate with server task/step timestamps and model timings without logging objective text, tokens, credentials, or identities. Run cold and warm trials. Store raw timings with the baseline.

If the serial fetch and fixed polling interval are then material on the measured critical path, a scoped candidate could move full-status retrieval ahead of the redundant snapshot or replace the two-request polling cycle with a governed long-poll/stream contract. Preserve authorization, reconnect cursor, revocation, bounded retries, offline/visibility handling, intermediate-vs-final status, and artifact integrity. Do **not** simply render SSE payload as final output or drop status polling: `clients/pwa/revision-tests.mjs:10` explicitly requires status checks even when no new event arrives. Prove via existing PWA revision tests, interface contract tests, disconnection/cancel/revocation tests, and measured before/after first-useful-output latency. Keep only a statistically meaningful improvement without correctness or resource regression.

Status: SOURCE-INSPECTED / LATENCY-UNMEASURED / NO OPTIMIZATION APPLIED in this lane.

## Isolated timing component

`clients/pwa/timing.mjs` now contains an opt-in, local-memory-only monotonic stage recorder. It is disabled by default, bounded to 128 samples, and accepts only the fixed stage vocabulary; it never accepts objective text, task IDs, credentials, response bodies, or headers. It is **not wired to `app.mjs` yet**, so no owner or production timing is claimed. Focused recorder and PWA regression tests ran on 2026-10-02 with `node --test clients/pwa/timing-tests.mjs clients/pwa/revision-tests.mjs`: 19 passed, 0 failed.
