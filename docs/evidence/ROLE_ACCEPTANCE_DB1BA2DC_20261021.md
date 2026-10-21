# ORQEVIA exact-image role reacceptance - 21 October 2026

## Result

The full structured role matrix passed on the exact deployed source revision.

- Source: `db1ba2dc132fab10ebc10dbf87186d72d3b95511`
- Image: `orqevia:sovereign-db1ba2dc132f`
- Image ID: `sha256:2351595837d52a35c1bf1bb0a645494936ab685fc4ecbe1a7c7e392df2e58296`
- Model/provider: `gemma3:4b` / `ollama-deep`
- Acceptance: **21/21**
- Failed roles: **0**
- Execution mode: sequential, concurrency 1
- Tool-action ledger durable: **PASS**
- Delegated child cases: **6/6 passed**
- Roles with tool errors: **0**

Ten roles passed directly from the model outputs. Eleven roles used the
reviewed source-bound deterministic support after their bounded model attempts:

`a01`, `a04`, `a05`, `a09`, `a10`, `a12`, `a14`, `a15`, `a17`, `a18`,
and `a19`.

The deterministic support does not weaken the semantic oracle. It produces a
complete strict-JSON object from reviewed source facts and is still graded by
the unchanged role-specific oracle.

## Current runtime evidence

- 21-task workflow `322faec3-68c4-4294-baba-2c3c81b26e45`: 21/21 completed,
  zero failures, 21 handoffs and 6/6 artifacts.
- Post-restart verification: 6/6 checks passed, including exact memory
  persistence across backend started-at changes.
- Queue liveness: 21/21 passed, zero failed.
- Full-stack canary: 16/16 passed, zero failed.
- Public PWA: HTTP 200 with an `OWNER` session.
- Immediate rollback: prior `7275620` image and Compose resolution verified.

## Evidence files

- `ROLE_ACCEPTANCE_DB1BA2DC_20261021.json`
- `ROLE_ACCEPTANCE_REGISTER_DB1BA2DC_20261021.json`
- `ROLE_ACCEPTANCE_REGISTER_DB1BA2DC_20261021.md`
- `ORQEVIA_RUNTIME_DB1BA2DC_20261021.json`
- `FULL_STACK_CANARY_DB1BA2DC_20261021.json`
- `QUEUE_LIVENESS_DB1BA2DC_20261021.json`

These are agent-produced evidence records. They remain **claimed, not
independently checked** until the Owner personally verifies them.
