# Hugging Face provider candidate (not deployed)

This source candidate adds text-only streaming chat to PRIME's existing governed cloud path. It does not activate a model or change Golden Gen2. The example catalog is disabled and unpriced. Browser login is not an API credential.

## Boundary

- PRIME resolves `env:HF_TOKEN` only at the transport boundary; agents and the PWA receive neither the token nor a token reference. The adapter fixes HTTPS to `https://router.huggingface.co/v1/chat/completions` and requires an explicit `model:provider` route, avoiding provider auto-selection.
- The request uses Hugging Face's documented `max_tokens`, streaming and usage fields. Existing bounded retries, cost reservation, data-classification policy, action records and outcome metrics remain in the PRIME cloud path. Tools, constrained structured output, embeddings and vision are **not** advertised by this adapter.
- A Hugging Face catalog entry cannot be enabled without `qualification_status=QUALIFIED`. Qualification still requires a fresh model/provider availability and price check, cost ceiling, privacy decision, a scoped token with Inference Providers permission, an isolated real request, validation, and provenance review. An enabled entry with unknown prices is not admitted by the queue.
- Provider `health()` reports local credential readiness only; network health stays `UNMEASURED` until an actual request. Failures must not be reported as success or silently retried after ambiguous execution.

## Remaining acceptance

The Owner's browser sign-in does not provide `HF_TOKEN` to ABEX. No token, paid service, model inference, 21-agent HF objective, Owner PWA path, Golden rollback or production promotion has been performed. Keep the example disabled until the Owner supplies a scoped token through an approved secret channel and approves any payment/privacy terms that apply. After that, verify a non-sensitive pinned model through PRIME and compare with the existing local path before considering promotion.

Official references: [chat API](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion), [Inference Providers](https://huggingface.co/docs/inference-providers/en/index), [tokens](https://huggingface.co/docs/hub/en/security-tokens), [security](https://huggingface.co/docs/inference-providers/en/security), [pricing](https://huggingface.co/docs/inference-providers/en/pricing).
