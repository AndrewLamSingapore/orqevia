# PRIME advisory skill parity candidate — 2026-10-03 SGT

## Boundary

This is an isolated branch candidate, not production deployment or proof that all 21 agents can execute. Accepted Golden Gen 2 remains unchanged. Host stability is still UNQUALIFIED. The Codex task's available collaboration limit is four simultaneous agents including the primary; that setting is not a PRIME inference limit and cannot be raised from this repository. PRIME production inference remains N=1. Isolated performance evidence favors N=3 with an Owner-reserved slot, but this is not a production qualification.

## Implemented here

- `config/prime_skill_registry.json` declares three bounded shared advisory methods. Each has no required tool and grants no action authority.
- `app/skill_router.py` checks the canonical agent registry and resolves a small just-in-time pack by task class and tier. NANO receives no pack to preserve its minimal measured prompt path.
- `app/agent_dispatch_api.py` includes guidance in the actual enqueue prompt only when `PRIME_SKILL_PACKS_ENABLED=1`. The default is disabled. It returns source hash and candidate skill IDs in routing metadata. An unavailable/invalid registry fails closed before enqueue.
- Generated capability manifest, per-agent matrix and profiles in this directory separate declarations and tested branch routing from live agent competence. The capability graph includes candidate skill edges, declared tool eligibility and declared authority as distinct relationships.

## Proof and limits

Focused routing/dispatch/context/graph tests: 40 passed on 2026-10-03. The generated evidence tests: 19 passed. The broad Python suite passed 1,123 tests plus 26 subtests; after adding the malformed-registry check, its focused router rerun passed 14/14. PWA Node tests passed 59/59. Both evidence exporters passed `--check`. These tests cover registry selection and a mocked enqueue path, not 21 completed specialist executions, live tool availability, model assignment, production skill parity, Owner latency with packs enabled, or production persistence. Every matrix row is therefore `UNVERIFIED` for runtime skill competence and `NOT_DEPLOYED` for production skill availability.

The remaining safe next proof is a bounded isolated agent-by-agent task with result validation and source-appropriate tool checks, followed by a guarded production trial only after host and deployment gates permit it. Do not enable permission bypass, copy credentials into prompts, or infer rights from skill presence.
