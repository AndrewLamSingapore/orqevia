# Optional model prewarm candidate — isolated, not deployed

The measured cold `gemma3:4b` PRIME request spent 9.155 s loading the model,
about 75% of its 12.195 s client wall time. A subsequent warm request spent
0.001 s on model load and 1.596 s total. This supports testing prewarm as a
candidate for the observed cold-load bottleneck. It does **not** prove a net
owner-facing improvement, especially when the owner requests a different model
or Ollama evicts this model.

The later production workload review found `gemma3:4b` in 40 of 54 historical
jobs and all observed 2 October jobs. Therefore the candidate defaults to the
configured `deep_model`, which targets that observed production model when
configured as `gemma3:4b`; it does not assume the configured fast model is the
dominant workload. `PRIME_PREWARM_MODEL` may explicitly select `fast`, `deep`,
or `evaluator`, but may not name an arbitrary or unconfigured model.

`app/model_prewarm.py` is a library-only candidate. No production config,
startup hook, deployment, or restart has been changed. The default is disabled:
only exact `PRIME_PREWARM_ENABLED=1` schedules work. A future isolated startup
trial would call `start_optional_prewarm(settings)` *after* essential startup,
without awaiting it. It uses a daemon supervisor and daemon HTTP worker so
PRIME boot/shutdown do not depend on Ollama. The supervisor stops waiting at
20 seconds; socket operations have a 10-second timeout. An unresponsive remote
peer may leave a daemon HTTP worker running briefly after supervisor timeout,
but it cannot block boot/shutdown. No retries are performed.

The candidate checks `/api/tags` first and only sends a load request when the
selected configured model is already installed; it never pulls an absent
model. It loads exactly that one model via Ollama's documented empty-prompt
`/api/generate` form and uses the configured `settings.keep_alive` (30 minutes
in the observed production settings), capped at two hours and rejected if zero
or invalid, with no generated
content. The handler retains only a coarse status and exception class; it
never records endpoint bodies, URLs, credentials, or prompt data. Failure or
timeout cannot raise into startup. No auth, identity, Golden image, or
production path changes are made.

Official Ollama API documentation confirms that an empty-prompt generate call
loads a model into memory and `keep_alive` controls residence time:
[Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md),
[Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx).

Before any deployment: wire the hook in a disposable candidate, measure boot
readiness, cold/warm TTFT and total request time, verify Ollama memory pressure
and model residency, exercise absent/unresponsive Ollama, and retain only if
net benefit and safety gates pass. `HOST_STABILITY=UNQUALIFIED` remains in force.
