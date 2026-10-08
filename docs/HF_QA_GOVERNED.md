# Optional governed HF QA source path

`POST /api/compute-queue/hf/qa` uses the existing private Owner bearer boundary
and Model Fabric queue. Its body contains `agent_id` (canonical permanent ID),
`task_id` (fresh UUID), `provider_id` (explicit selected HF catalog entry),
`context`, `question`, `data_classification: CLOUD_PERMITTED`, `max_cost_usd`
(decimal string), and optional total/primary timeouts (defaults 30/15 seconds).
The same task UUID cannot reserve a second chain. Input is at most 2048 context
bytes and 256 question bytes; secret-like input is denied before disclosure.

The selected **operator-owned** enabled/qualified HF catalog entry must contain
an optional `serverless_qa` object with exactly these fields:

- `version`: `hf-serverless-qa.price.v1`
- `model`: `deepset/roberta-base-squad2`
- `maximum_charge_usd`: a positive decimal string taken from a real commercial
  maximum-charge contract for the fixed serverless model/endpoint, one bounded
  request, and no retry. Token rates or an inferred free allowance do not suffice.
- `price_contract_sha256`: the retained actual contract evidence digest.
- `valid_until_utc`: the actual contract expiry, an offset-aware future timestamp.
- `router_fallback`: an explicit boolean allowing the same selected HF chat model
  as the sole alternate after proven rejected admission.

No contract is shipped, activated or fabricated by this implementation. Absence,
expiry or malformed scope fails closed before credentials or requests. The
existing catalog task/prompt/agent scope still applies to the fixed QA-to-chat
prompt. A configured router fallback also needs its pinned provider/model,
qualified task scope, valid prices and sufficient context/output limits. This
path denies catalog fallback chains and forces zero provider/job retries.

Both jobs reserve their costs atomically before dispatch. Held jobs are excluded
from ordinary workers, but count against daily admission. Only a targeted claim
can execute one; normal global, per-agent, provider and cloud capacity checks
still apply. A proven clean direct rejection records zero direct charge before
claiming the alternate. Successful unmetered QA, transport failure and cancellation
after dispatch retain the direct maximum charge. Running uncertain work is never
replayed. Never-dispatched holds cancel/expire with zero charge. The cloud executor
checks selected catalog identity again before credentials; the returned receipt
binds actual selected identity, child job, reservation and original input digest.
The direct rejection observer records per-attempt evidence even without an
alternate; an eventual error's `pre_execution` flag is not a billing receipt.
The pinned price contract and task scope are revalidated after targeted claims,
so a claim wait cannot carry expired authority into credential resolution.

Cloud claims also persist `cloud_inflight`. Cancellation leaves it set, so
another worker/process cannot consume the apparently freed cloud slot while HTTP
cleanup continues. Only the trusted executor's `finish` call after its coroutine
and cleanup have settled clears client occupancy, including late callbacks for
canceled/failed jobs. Unknown provider billing and remote execution remain
uncertain and their cost cap stays reserved. A worker crash/expired lease marks
running work failed but **does not clear** cloud occupancy or replay it. It needs
a real trusted completion/cleanup receipt or explicit operator reconciliation;
a timer or process restart alone cannot establish cleanup. The queue's separate
`cloud_inflight` metric exposes these occupied/uncertain jobs.
Legacy running cloud-eligible jobs without dispatch-kind evidence are migrated
conservatively as occupied, including NULL/local-looking provider identities.

`PRIME_CLOUD_REQUEST_CAPACITY` provides an additional cloud upper bound, default
one, clamped to one through four. It does not create extra workers or enlarge the
existing measured global/local limit. Four is an implementation bound, not proof
that four concurrent requests are qualified. No settings, catalog, mounts,
credentials or runtime deployment are changed by this source work.

The offline tests exercise the real queue and HF transports with synthetic HTTP
responses. They prove admission/accounting behavior, not live HF availability,
pricing, deployment or answer quality. Before live use, check exact source CI,
the real operator contract and catalog scope, deployment correspondence, and one
Owner-authorized bounded task at existing capacity. Independently check its answer
against the task oracle, usage/cost evidence and failure receipt. Any increased
parallel capacity requires its own observed qualification. A matching source span
does not award model/agent qualification or L7.
