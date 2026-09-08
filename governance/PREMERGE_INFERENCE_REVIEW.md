# PR #59 pre-merge inference review

Recommendation: **HOLD**. This is branch evidence, not deployed behavior or a
claim of estate-wide admission. Operational STALE is retained.

## Source ingress inventory

| Ingress/call family | Model transport | PR behavior |
|---|---|---|
| Authenticated Harness dispatch | queue worker → execute_job → HarnessedExecutor → _infer | Signed PDP/PEP admission, one-use in-thread worker scope, local HTTP chat only |
| Raw _infer invocation | same network adapter | Denied without the consumed worker call scope; cloud rejected |
| /api/chat, cognitive reason, evaluator and multi-specialist internals | ModelGateway._post | Always denied before network, independent of pilot environment flag |
| Dataset/code generation, research synthesis, org/autonomous/phase3/orchestration cycles and smoke endpoints | main.ollama_post | Always denied before network |
| Persistent scheduled automation | orchestrate → gateway or main model helper | Same denied transports; no separate model admission |
| Memory ingestion/search/indexing and embeddings | main embedding helpers / HybridMemory._embed | Model calls denied; existing deterministic lexical fallback explicitly reports degraded retrieval |
| Code run helper and /api/code/run | subprocess Python | Denied before process launch; AST filtering was not a trusted execution boundary |
| Configured frontier/cloud GPU | gateway transport / provider selection / raw adapter | Frontier unavailable, no cloud providers advertised, legacy network helper denied, adapter rejects cloud |
| Model readiness /tags, Portal graph, relay/telemetry/result adapters, public URL reads | HTTP metadata/data operations | Not counted as a governed model executor; cloud/provider-side inference effects and external-state semantics require estate review |

The raw network adapter is now scoped to the exact job object, once, after PEP
consumption. This is a trusted-code call boundary, not an OS sandbox against
arbitrary trusted code or an administrator importing internal helpers. There is
no client-supplied permit or new signing authority.

## Crash/concurrency evidence and limitations

- Durable lease consumption and the shared ledger's started/uncertain states
  serialize inference across independent worker processes, including distinct
  queue objects sharing that ledger. Separate interpreters race one lease;
  exactly one reaches the mocked provider.
- An interpreter exits abruptly inside inference after fsync of a call marker.
  Restart cannot reuse the lease. Queue expiry marks the job failed without
  retry; a new job cannot take the still-started durable slot.
- Timeout/uncertain outcomes retain the slot. No automatic uncertain-slot reset
  or authorization reissue is introduced. Operator reconciliation remains
  necessary; availability is deliberately sacrificed for no duplicate inference.
- The worker rereads its durable claim and rejects changed/expired claims. TTL
  is checked again after acquiring the Harness transaction lock, closing the
  pre-lock time-of-check gap.
- Queue submission and Harness binding commit to different databases. A crash
  after binding but before queue commit can leave an orphan queued binding.
  It does not create runnable queue work, but operator reconciliation is not
  implemented. A crash after completion but before queue finish can leave a
  completed Harness outcome and failed queue bookkeeping, without permission
  to retry the consumed lease.
- Current Spine policy, queue state and Harness consumption still span separate
  transactions. A policy/claim update can race their successive checks. There
  is no atomic cross-store fence; do not claim the whole boundary is proved.
- Replacing/restoring a ledger or using another database path loses shared
  replay/concurrency history. No external fencing generation prevents an old
  worker or independent authority/database from acting. Ordinary restart with
  the same intact ledgers is covered; rollback-to-old-data is not.

## Live estate evidence and remaining blockers

The read-only connector observed healthy PRIME version 7.3.1.1 at
2026-09-08T02:47:30Z, with zero running agent jobs and physical_actuation false.
It does not report the deployed commit or aggregate provider activity. The last
owner-recorded container/image/revision remains c449dd1 and is not PR #59.

Windows process observation found tunnel-client PID 12168 and native Ollama PID
13544. A process listing is not evidence of inference or a common admission
lock. The owner previously recorded a separate Docker Ollama container.

The current four cloud Git revisions match observed READY deployment metadata
and health revisions. Portal reports generation configured; VELYQUA reports
cloud configured and Stable Spine server_configured false. These are not
evidence of inference through PRIME's one-slot authority. Sky's current
deployment lacks revision metadata; its recorded runtime SHA/hash remains
explicitly historical, not inferred from current source HEAD.

Remaining blockers:

1. No verified effective Docker/native/provider-network inventory or isolation
   proves all callers use one admission point; native Ollama and direct clients
   may exist outside this code boundary.
2. Cloud inference-capable paths and external adapters are not demonstrated to
   share PRIME's authority or one-slot admission. Cross-repository source and
   effective runtime configuration need a complete authority/egress audit.
3. No atomic cross-store policy/claim/admission fence; queue/Harness orphan and
   completion bookkeeping require a specified operator recovery protocol.
4. No durable external fencing against restored/alternative ledgers or old
   authorities. Data continuity, registry digest and current effective Dell
   settings are not independently verified.
5. The proposed canonical SSOT/checkpoint are only on PR #59. Main and the Dell/
   Library mirrors are unchanged; a reviewed mirror update remains pending.
6. Sky runtime revision/content equivalence is unverified for its current
   deployment. Operator three-agent acceptance, ABEX, AgentScope and VELYQUA
   hardware commissioning remain pending. No live rollout is authorized here.

No native process, container, credentials, profile, production configuration,
rollback/checkpoint branch or live authority was changed during this review.
