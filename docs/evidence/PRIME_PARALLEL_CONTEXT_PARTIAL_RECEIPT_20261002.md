# PRIME parallel/context mission — partial checkpoint, 2026-10-02

Status: **PARTIAL, NOT PRODUCTION VERIFIED**. This is an isolated review branch
and draft PR #143, not a replacement for accepted Golden Gen 2 production.

## Proven on the branch

- The objective submission and continuation paths call the bounded ready-work
  scheduler for independent capability *submissions*. This is not model
  execution parallelism or a dependency-aware completed-work DAG.
- The registry declares 21 canonical agent identities and 29 responsibility
  owners. `PRIME_AGENT_MATRIX.json`, `PRIME_CAPABILITY_GRAPH.json`, and
  `PRIME_CONTEXT_PROFILES.json` are deterministic projections of that registry,
  with the source SHA-256 and explicit activation=false fields. They do not
  prove running agents.
- A bounded context pack selects source-labelled, fresh, agent/task-relevant
  data, rejects invalidation and duplicate source IDs, preserves mandatory
  dispatcher constraints, and does not silently truncate. The *opt-in* advisory
  dispatch path uses it for request context before enqueueing a model job;
  oversize context fails without enqueue. `PRIME_CONTEXT_PACKS_ENABLED` defaults
  off. No shared objective-state retrieval or actual tokenizer qualification
  has been implemented.
- Controlled isolated N=1/2/3/4 backend comparison favored N=3 on the tested
  five-request workload (29.595/17.902/12.675/13.024 s). N=6/8 exceeded the
  6 GiB test-container margin. N=3 remains a leading candidate, not a
  production setting. See `PRIME_INFERENCE_CONCURRENCY_20261002.md`.
- The isolated reserved N=3 Owner test measured 0.913 s first token, versus
  6.989 s fully occupied without reservation. A non-preemptible full pool
  cannot guarantee immediate arbitrary-arrival Owner service; the current
  reserve is intentionally not background-work-conserving. See
  `PRIME_OWNER_LOAD_PROOF_20261002.md`.

## Not proven / blocked

- Production remains accepted Golden Gen 2, N=1. No branch code, N=3 setting,
  context pack, DAG, or 21-agent activation was deployed from this checkpoint.
- Host stability is **UNQUALIFIED** after seven unexpected restarts. The latest
  28 September 0x133 dump implicates the AMD display ISR/DPC path, but no
  common cause has been established. A clean administrative reboot is not a
  stability pass. Preserve the forensic originals and do not treat uptime alone
  as qualification.
- No live 21/21 execution proof, actual multi-agent tool overlap, selected
  context-pack utilization by each agent, or production Owner-under-background
  proof exists. No production PWA visible-render timing or reboot persistence
  proof exists.
- Strict all-slot background utilization while preserving the measured fast
  Owner response needs bounded/preemptible inference or an explicitly accepted
  latency tradeoff, both unproved. Mixed-provider global-slot isolation also
  remains unproved.
- The production promotion, service restart, and reboot sequence must wait for
  the host-stability/safety boundary and an evidence-supported guarded trial.

## Safe continuation order

1. Preserve this branch and draft PR; keep accepted production/rollback intact.
2. Design and test the real completed-work DAG, verified-state/context source
   boundary, tokenizer/secret limits, and 21-agent role-specific dispatch.
3. Prove controlled backend and Owner policy under sustained representative
   load with rollback, then reassess host stability before any promotion.
4. Only after a safe promotion decision, measure live PRIME/PWA/agent proof,
   restart and reboot persistence, and regression guards. Report actual values.

The branch tests and generated-export check are recorded in
`PERFORMANCE_TEST_RESULTS.md`; none can substitute for live production proof.
