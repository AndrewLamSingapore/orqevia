# Provider gateway candidate

This extends ORQEVIA's existing provider catalog, cloud executor, queue budgets,
circuit boundary and outcome records. It creates no agent registry, dispatcher,
treasury or paid account. The shipped activation template has an empty `models`
array. Nothing selects, enables or probes an external provider automatically.

## Wire adapters and admission

`openai_responses` pins the official `/v1/responses` endpoint, isolates
`env:OPENAI_API_KEY`, sends text input with `max_output_tokens` and `store:false`,
and parses text deltas plus completed usage. `deepseek_chat` pins the official
`/chat/completions` endpoint, isolates `env:DEEPSEEK_API_KEY`, uses `max_tokens`
and streams completion usage/cache hits. Neither adapter advertises tools,
multimodal input, embeddings, structured output, provider-side idempotency or
model entitlements. The model is an explicit catalog choice, never a guessed
current alias. Hidden reasoning is not emitted as answer text.

Activation requires a qualified exact model, declared text-generation capability,
explicit finite input/output rates, context/output caps and dated official
rate/capability evidence. No price is hardcoded. Configured evidence is an
activation input, not proof that a request succeeded or an account is funded.

The existing tier/locality router and cloud executor enforce disclosure and queue
spend ceilings. Explicit fallback candidates are rebound to current catalog
configuration before each dispatch. Existing bounded retries remain at most two
at the primitive boundary, with the existing cloud executor permitting at most
one. Only proven rejected admission or local missing credentials may fall back;
ambiguous transport/5xx, partial text, usage, timeout, cancellation, authentication
failure or insufficient balance cannot replay paid work. Provider circuit state
is process-local and is not a durable provider-health certification.

## Durable submission idempotency

The existing queue accepts an optional bounded `idempotency_key`. Its digest is
scoped to canonical agent and atomically bound to the submitted request and job
in the existing queue database. An identical retry returns the original job;
a changed request rejects the key. Keys are not provider secrets, and only hashes
are stored. Concurrent duplicate submissions and restart reuse are tested.
This is local submission protection; no undocumented upstream exactly-once or
refund guarantee is claimed. The existing cloud-worker lease/replay boundary is
unchanged.

## Read-only usage and quota view

Authenticated `GET /api/compute-queue/providers/usage` projects at most the latest
500 local `reasoning_attempts` insertions. It has the existing 21 agent IDs,
provider aggregates and inherited queue job/day/concurrency caps. It does not
create a usage database or call a provider. Missing usage/cost is `UNKNOWN`, not
zero. A recorded cost is labelled a local rate estimate, never an invoice or
provider balance. No per-agent monetary allocation is invented: that value is
null until an owning quota policy exists. Provider balance remains unknown.

The treasury lane's `SIMULATED` wallet and settlement balances are a separate
domain and are never combined with model billing. Unit fixtures explicitly use
`MOCK_CONTRACT_FIXTURES`; they cannot qualify live inference, normal-role agent
work, actual usage, funding, production rollout or 21/21 runtime readiness.

## ABEX CLI and DigitalOcean preparation

The read-only host audit found an existing Codex CLI and working ChatGPT sign-in.
No CLI update, credential file change, default change or API request was required.
ChatGPT CLI authentication is not a provider API key and does not imply OpenAI
API billing access, DeepSeek entitlement or an email-linked funding source.

`deploy/digitalocean/provider-boundary.preparation.json` records architecture and
ownership boundaries only. It is deliberately not a deployable app specification:
the current runtime has local transport gates, SQLite/WAL and local durable
records. App Platform local disks are ephemeral; a cloud storage/transport design
and its independent acceptance are still required before moving ownership.
No resource, account, payment method, domain, firewall rule or storage migration
was created or changed.

## Primary references

- [OpenAI Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Codex authentication](https://developers.openai.com/codex/auth)
- [DeepSeek Chat Completions schema](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek error codes](https://api-docs.deepseek.com/quick_start/error_codes/)
- [DigitalOcean app specification](https://docs.digitalocean.com/products/app-platform/reference/app-spec/)
- [DigitalOcean runtime secrets](https://docs.digitalocean.com/products/app-platform/how-to/use-environment-variables/)
- [DigitalOcean storage constraints](https://docs.digitalocean.com/products/app-platform/how-to/store-data/)
