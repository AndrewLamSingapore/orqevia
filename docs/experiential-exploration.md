# Local experiential exploration candidate

This opt-in source library addresses durable, bounded simulator experiments and
retrieval adaptation. It does **not** establish autonomous model reasoning,
role-specific skill acquisition, model-weight training, production admission or
Azure L7 certification. It changes no production routes, worker configuration,
permissions, signing policies, registry identities or sovereign product.

## Existing mechanisms reused

- `agent_registry`: exact registered specialist IDs and existing names/roles.
- `AgentAuthorityRuntime`: existing specialist-to-lead and lead-to-lead
  consultation boundaries and sanitized handoff ledger.
- `Phase2Kernel`: scoped objectives, hypotheses, attempts and counterexamples.
- `MemoryStore`: persistent episodes with searchable experiment history.
- `evaluate_lesson`: repeated evidence and counterexample admission check.

The simulator explores three whitelisted integer transformations. It observes
permutation preservation and ordering without a scalar reward. It selects the
supported strategy, retains failed strategies, then challenges the proposal on
three disjoint held-out examples under another registered identity. These are
algorithmic fixtures, not 21 independent model actors or role-specific cases.

## Isolation and persistence

The caller supplies an empty, dedicated directory. Existing unmarked data and
symbolic-link/junction paths are refused. The directory contains a scope marker
and separate memory, continuity and authority SQLite databases. No runtime
environment variable silently selects a production database.

Each run reserves at most 9–100 trials persistently (default 12). Independently,
the sandbox persists trusted-caller ceilings: default two runs/24 trials per
agent and 42 runs/504 trials for the sandbox. Restart or a new run cannot reset
these ceilings; atomic reservations prevent concurrent oversubscription. A
failed objective/episode write consumes its reserved slot. History retrieval
filters the agent/query and applies its read limit in SQL. Failed episode
writes consume their reserved trial. Input length, magnitude and strategy are
bounded; no shell, arbitrary code, subprocess, network or model operation is
available in the library. The evaluation CLI starts two bounded subprocesses
with a 120-second limit, demonstrating retention after actual process exit.
Partial runs resume stored observations; completed discovery is idempotent.

Candidate hashes bind observations and episode provenance. Local reviews bind
the candidate, held-out cases, reviewer and simulation scope. Admission is denied
by default. A host can inject its existing authorization verifier; its accepted
receipt must bind the exact admission or rollback operation. Receipts are
single-use and bind the exact candidate, agent and skill version. Transfer and
rollback recheck the persisted version-bound admission witness; a reviewed but
unadmitted candidate cannot propagate through a forged version row. This is not
a tamperproof database against actors who control its raw files. The evaluation
harness injects **synthetic fixture authorization**,
which must never be used as a production trust boundary.

Sandbox procedural versions retain the complete candidate and authorization
digest. Rollback requires separate authorization and does not erase prior
versions or failures. They are stored in the sandbox candidate namespace rather
than bypassing `MemoryStore.put_governed`'s existing Owner requirement. Validated
sharing follows the existing consultation graph through domain leads; consumers
receive no new tool rights or execution authority. All shared content remains
labelled `simulation_fixture`; it cannot become production procedural memory.

## Reproduce source acceptance

```powershell
python -m pytest -q tests/test_experiential_exploration.py tests/test_agent_registry.py tests/test_memory_meta.py tests/test_phase2_intelligence.py tests/test_general_intelligence.py
python scripts/evaluate_experiential_exploration.py --output <fresh-evidence-directory>
```

The second command writes `learn.json`, `21-agent-matrix.json` and the isolated
SQLite evidence. Every row copies the actual registry identity and capability
requirements and explicitly leaves live model self-direction, role-specific
transfer, production promotion and Azure L7 unverified. Simulator baseline and
post-adaptation results are counted separately; they are not intelligence scores.

## Remaining live integration and release boundaries

`agent_execution_live.observe_live_baseline` remains the existing authenticated
dispatcher adapter; this library does not invoke it, invent credentials, attach
tools to agents, or silently substitute simulation for model output. Real
self-generated experiment design needs separately authorized model dispatch,
role-specific unfamiliar tasks, contamination-resistant unseen evaluation and
an independent reviewer. General source tests cannot satisfy those criteria.

DigitalOcean is the intended operational cloud target; Azure is the independent
L7 assessment environment. Neither is deployed or assessed by this candidate.
Production activation and any spend require existing authorization and signed
release/admission evidence. Rollback of this unactivated source candidate is to
retain the existing production release; removing the opt-in library reverts its
source integration. Sandbox skill rollback is tested independently and grants
no deployment rights.
