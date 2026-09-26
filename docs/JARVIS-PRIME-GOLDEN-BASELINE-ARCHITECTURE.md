# JARVIS PRIME Golden Baseline Architecture — Generation 1

Status: **FROZEN ARCHITECTURE**  
Production source: `17fad78d410dca5d9101483cb777a2b9b619bac3`  
Production image: `prime:sha-17fad78` (`sha256:745244a3a8fb6d2708e96b63504e55c10aead7538fc4ed9c0621328cd7ef3681`)  
Runtime acceptance: **VERIFIED**  
Architecture freeze and long-duration stability are separate. The Windows/production long-duration stability evaluation remains pending.

## 1. Golden identity

This document is the canonical architecture authority for JARVIS PRIME Golden Generation 1. It describes the implemented, deployed and accepted local ABEX generation only. `STATUS.md` remains the human current-status authority; `governance/golden-gen1-manifest.json` is this architecture's machine-readable identity. Evidence does not become architecture merely by existing, and this document cannot establish a later runtime generation.

## 2. System purpose

JARVIS PRIME accepts an authenticated Owner or Member objective, applies server-side identity and authority, selects canonical capabilities and agents, executes through bounded model/tool paths, preserves system-owned provenance, and returns results and artifacts to the originating authorized client.

## 3. Architectural principles

- One PRIME; ABEX is the sole production authority and runtime host.
- Source is not runtime; a receipt and independent verification bind them.
- Context, competence, prediction, model prose and agent claims do not grant authority.
- PRIME selects canonical agents by registry capability and role.
- Agents cannot self-declare, self-promote, transfer or amplify authority.
- System metadata is server-owned; model output is content.
- Tool invocation is not verified effect; test PASS is not physical PASS.
- Historical evidence is immutable; current truth is generation-bound.
- Promotion is governed and rollback remains available.

## 4. Production topology

```text
Owner/Member client
  -> HTTPS Interface on ABEX (LAN 192.168.1.23:8443)
  -> server-side session and authority check
  -> PRIME on ABEX (loopback 127.0.0.1:8000)
  -> registry/routing/queue/model/tool execution
  -> result and task-bound artifact
  -> authorized originating client
```

Docker generation `prime-epoch-20260919` runs PRIME and Interface from the same immutable image. Ollama is a separately pinned local model runtime. Databases and artifacts reside in the external PRIME data volume. No database, Docker API, Ollama API or PRIME internal API is intentionally exposed to the LAN or public Internet in this baseline.

## 5. Trust boundaries

The client is untrusted for role, authority, runtime identity, task metadata and artifact integrity. The Interface authenticates a hashed session credential and resolves the server-owned account/role. PRIME owns routing and execution state. Models and agents are advisory/restricted computational resources, not principals that can create authority. Consequential external effects require the applicable independent policy and verification boundary.

## 6. Identity and authority

- **Owner:** canonical account `owner:lam:prime-epoch-20260919`; server-enforced `OWNER` role.
- **Member:** separately enrolled server-side `MEMBER`; never inherits Owner authority.
- **Device/client:** a client identifier bound to a hashed, expiring, revocable session record.
- **Enrollment:** short-lived, one-time, role-bound pairing record; plaintext codes are not stored.
- **Session:** hashed credential with client, account, role, expiry and revocation state.
- **Application:** may request only allowed operations; it cannot assert a role.

Owner and Member identities, sessions and data are distinct. Model output, retrieved context, agent delegation and client UI state cannot alter authority. Denial is fail-closed.

## 7. PRIME orchestration

Verified Gen 1 responsibilities include objective lifecycle, revision-aware continuation, canonical agent/capability routing, compute queueing, bounded local/cloud provider selection, result evaluation, artifact materialization, offline deferral/reconciliation, system-owned runtime/provenance reporting, and bounded observation/repair support. PRIME does not have unlimited repair authority, self-preservation goals or permission to redesign or deploy itself.

## 8. Canonical agent architecture

`config/agent_registry.json` schema `2.0`, registry version `1.0.0`, defines exactly 21 logical agents and 29 historical responsibility mappings. Agent IDs are immutable. Each entry declares role, capability requirements, eligible tools, model tiers, delegation targets, non-responsibilities and failure behavior. Delegation transfers work, never authority. The historical 29-agent schema `1.1` is not current.

## 9. Models and tools

Models are replaceable resources selected by server policy for locality, task class, cost and availability. The accepted local path uses pinned Ollama image `sha256:da6e0dc5651df159e45686fd663c4dbe1624a52c44d7280eeac1551d8f865532`; the accepted Owner task used `ollama-deep`. Tool eligibility comes from registry/policy, not model request. WASM or other sandbox execution remains bounded by host guard and explicit policy. A model/tool response does not prove an external effect.

## 10. Task and execution lifecycle

```text
Owner/Member -> Interface -> session/authority -> objective
-> PRIME orchestration -> canonical capability/agent
-> queue -> model/tool -> evaluated result -> artifact -> authorized client
```

Objectives use server-created task UUIDs, idempotency keys, revisions and explicit states. Concurrent conflict and uncertain dispatch fail closed. Jobs record bounded attempts, provider, routing reason, timestamps, result/error and completion state. Terminal tasks can materialize a task-bound artifact exactly once.

## 11. Provenance

Authoritative fields are system-owned: task UUID; created, started, completed and updated timestamps; runtime/source/image identity; account/role; execution state; artifact identity, byte count and digest; verification and acceptance state. Model text is `MODEL_CONTENT`. It cannot populate or override those fields. The repaired boundary is evidenced by current task metadata and by preservation of the historical fabricated UUID/timestamp failure as historical evidence.

## 12. Data and storage

Canonical production stores in the external PRIME data volume:

| Store | Purpose | Integrity/persistence |
|---|---|---|
| `interface.db` | client/account binding and idempotent Interface requests | SQLite, `quick_check=ok` |
| `pwa-sessions.db` | hashed pairing, sessions and admission limits | SQLite, `quick_check=ok` |
| `objectives.db` | objective, revision and turn lifecycle | SQLite, `quick_check=ok` |
| `compute-queue.db` | jobs, approvals and execution events | SQLite, `quick_check=ok` |
| `compute-ledger.db` | reasoning attempt/cost/verification records | SQLite, `quick_check=ok` |
| `offline-queue.db` | durable deferred operations and reconciliation receipts | SQLite, `quick_check=ok` |
| `jarvis-memory.db` | governed episodic and durable memory | SQLite, `quick_check=ok` |
| artifact store | task-bound immutable result artifacts | digest verified |
| action records | evidence of bounded actions/effects | append-oriented evidence |

`prime.db` and `prime-spine.db` are empty compatibility stores in this generation, not authoritative current state. Rollback uses the preserved image plus private checkpoint; secrets are regenerated/rebound, not stored in public evidence.

## 13. Memory and RAG

Gen 1 has governed episodic/durable memory and bounded retrieval through `jarvis-memory.db`, `app/memory.py`, `app/hybrid_memory.py` and `app/governed_knowledge.py`. Promotion to durable memory requires typed source/provenance, confidence and lifecycle status. Identity and authority remain outside model-written memory. The proposed Phase 2 Context Fabric is not a Gen 1 capability.

## 14. Observer and repair

Gen 1 observes host/runtime health, queues, dependency availability, execution failures, registry/runtime drift and relevant Windows/storage events through bounded health, observation and operational-workflow paths. Repair must preserve evidence, stay within host guard and existing authority, and verify effect independently. Disk/partition/EFI/firmware operations, uncontrolled retries/reboots, identity recreation and broad Docker data deletion are outside this authority.

## 15. Interface and PWA

Canonical endpoint: `https://192.168.1.23:8443/pwa/` (LAN-only TLS using the local CA). Accepted shell generation is `jarvis-shell-v11`. The runtime receipt freezes hashes for `index.html`, `app.mjs`, `sw.js`, `release.mjs` and `recovery.js`. The PWA supports authenticated connection state, objective submission, recent-task opening, dedicated result display, task metadata separation, artifacts and qualified Read Aloud behavior. Platform-controlled installed-icon refresh behavior is not represented as a server authority.

## 16. Clients

- **ABEX:** sole production authority, production host and canonical execution environment.
- **Dell:** trusted PRIME client, independent verifier and engineering/recovery workstation; never production authority and cannot transition `PRIME.RUNTIME`.
- **Owner iPhone:** physically accepted for session persistence, Owner authority and a real Chinese JARVIS objective round trip.
- **Member iPhone:** identity and Member-to-Owner denial evidence are historical accepted commissioning evidence; deferred UX items do not grant or alter authority.
- **Wuhan/Mainland-China:** physical verification pending; Singapore/LAN evidence cannot satisfy it.

## 17. Network and security

The Interface is bound to ABEX LAN address on HTTPS 8443. PRIME is loopback-only on 8000. The accepted runtime exposes neither Ollama nor databases publicly. TLS, strict origin handling, CSP/no-store/nosniff, hashed credentials, least authority, bounded delegation, secret references, host guard, provenance validation and rollback are Golden invariants. Optional tunnel profiles are not active Golden connectivity merely because Compose defines them.

## 18. Artifacts

Artifacts are created by the server from terminal task results, assigned a system artifact ID, hashed, byte-counted and bound to task/revision. Authorized clients list/download through the Interface. Artifact content cannot rewrite task, runtime, identity, authority, digest or verification metadata.

## 19. Verification and acceptance

The lineage is:

```text
source 17fad78d...
-> image prime:sha-17fad78 / sha256:745244...
-> ABEX PRIME + Interface
-> ABEX runtime receipt SHA-256 49c6668f...
-> Dell corrected verification f5a6f344... / artifact SHA-256 dc80ee30...
-> governed acceptance at 2026-09-26T07:48:05Z
-> PRIME.RUNTIME VERIFIED
```

The acceptance transition is fail-closed and exactly once. Neither ABEX prose, Dell prose, Owner statement nor UI text can directly set it.

## 20. Rollback and recovery

Immediate rollback is `prime:sha-2ca9b4a`, image ID `sha256:77024fd32de246fe61ed5043f82482f44cb78c5e94a2600fb43e85318fdf7539`, with private checkpoint `/data/recovery/pwa-mobile-control-predeploy-20260926`. Recovery preserves databases, identities, artifacts, evidence and secrets boundaries. The accepted source, pinned images, Compose/runtime manifests, schemas, registry, receipt, verification and architecture manifest provide the reconstruction chain.

## 21. SSOT and governance

Truth ownership is category-specific and non-conflicting:

- current human status: `STATUS.md`;
- Gen 1 architecture: this document;
- Gen 1 machine identity: `governance/golden-gen1-manifest.json`;
- agent roles/capabilities: `config/agent_registry.json` at accepted source;
- live runtime: ABEX runtime;
- runtime/source binding: accepted receipt plus independent verification and acceptance record;
- identity/authority: server-side PWA session/account data and policy;
- task/artifact truth: their canonical stores;
- historical failures: immutable evidence records.

Derived checkpoints and summaries cannot override their authority. Candidate manifests cannot describe production until governed promotion and acceptance.

## 22. Known external and unverified gates

- Long-duration Golden stability evaluation: **PENDING**.
- Wuhan/Mainland-China physical acceptance: **PHYSICAL VERIFICATION PENDING**.
- VELYQUA physical telemetry: **PARKED / not physically qualified**.
- Broader public-portfolio evidence in `governance/operational-manifest.json`: may remain `STALE`; this does not invalidate the independently accepted local PRIME generation.

## 23. Candidate and future architecture boundary

Complex Problem Solving, Predictive Intelligence, Objective Continuity/Core Will and High-Context Vibe Engineering are Phase 2 candidate programs. They are not part of Golden Gen 1 unless already listed above as an implemented Gen 1 primitive. Candidate work must occur on isolated branches/data, preserve Gen 1 production, qualify security/provenance/authority, and undergo a new source-to-runtime receipt and independent acceptance before any Golden Generation 2 freeze.

Golden Gen 1 is immutable. Material accepted evolution creates a new Golden generation; it never rewrites this one.
