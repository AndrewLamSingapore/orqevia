# Evidence Lens production access gap — bounded diagnosis

Observed 27 September 2026, approximately 18:32 +08:00. This is an executed
read-only diagnosis and resume checkpoint, not Evidence Lens end-to-end PASS.

## Exact execution scope

Accepted production source remained
`b171253566e7c879283d2aacf699ae6c1ec8988e`, image ID
`sha256:1cfbefa03a0a68d162242ccf5139f498eee3594e01bb0e568ff4f71ca187b2b5`.
PRIME, Interface and Ollama remained healthy with restart counts zero.

Root executed a read-only `python -B` function probe inside the existing PRIME
container. It created no objective, changed no file/database, and replayed no
credential. The live `app/system_architecture.py` module SHA-256 was
`78d3b14e4d99f9da7d814816d5395b6c9f473a5a4e97564fdc783e57e88a59f2`.

| Question | Actual running-container result |
| --- | --- |
| Source/runtime identity | Exact accepted source and image ID, canonical runtime answer |
| Is Phase 2 Golden and accepted? | UNVERIFIED: canonical governance evidence unavailable |
| ABEX/Dell/PRIME architecture; is Dell production authority? | UNAVAILABLE: canonical manifest cannot be read |
| Agent count; caller claims 300 | Canonical count 21; no model agent selected |
| What does agent a99 do? | UNAVAILABLE; no invented role or tools |

## Established cause and boundary

These four paths were absent from the running image:

- `/app/governance/phase2-state.json`
- `/app/governance/golden-gen1-manifest.json`
- `/app/governance/golden-gen2-manifest.json`
- `/app/docs/evidence/PHASE2_RUNTIME_RECEIPT_B171253_20260927.json`

Dockerfile packages application, configuration and PWA assets, not governance
documents. The actual production result is fail-closed abstention. The stale
Gen1 answer obtained by evaluating the same module in a repository checkout is
not a production result and must not be attributed to this physical runtime.

The source nevertheless hard-wires old Gen1/Phase2-candidate records. Existing
tests assert historical `NOT_DEPLOYED`/Gen1 output. Blindly copying those files
into production would introduce stale answers and is not an accepted repair.

## Unfinished integration qualification

- Evidence Lens's example is static; its test explicitly asserts no PRIME API
  query. Demo/UI qualification does not establish live evidence retrieval.
- No production call sites beyond schemas/tests were located for portable
  evidence adapters. This is a scoped search observation, not proof of absence.
- Architecture lookup uses objective text rather than attached context. General
  portfolio/commercial questions can fall through to model dispatch.
- Objective responses wrap deterministic text as SYSTEM_FACT with generic
  provenance, without retaining nested unavailable status and exact source
  digest/freshness. This requires separately qualified provenance work.

The A–F live objective matrix remains unfinished. These direct function probes
are not objective-path or physical acceptance. Continue with exact task receipts
and bounded tests before claiming end-to-end qualification. Any resolver or
provenance repair belongs in an isolated successor and must preserve immutable
source/runtime binding, explicit unavailability, historical supersession and
server-owned authority. No production or acceptance mutation occurred here.
