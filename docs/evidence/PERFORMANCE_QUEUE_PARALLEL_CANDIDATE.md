# Bounded global queue concurrency candidate — not deployed

The live queue was hard-fixed at one global and one per-agent inference slot.
This isolated candidate leaves those defaults unchanged. A second or third global slot
is selected only when all three conditions hold:

1. `PRIME_QUEUE_CONCURRENCY=2` or `3` is set explicitly (other values fail closed to 1);
2. `OLLAMA_NUM_PARALLEL` is explicitly configured to at least the requested count; and
3. the integrity-checked measured compute profile permits
   `normal_concurrency` at least the requested count.

Per-agent concurrency remains 1. The queue's existing atomic SQLite leases,
provider concurrency and RAM/VRAM admission checks remain in place. No
production environment variable, profile, service, or running queue changed.
The isolated Compose candidate now mirrors `OLLAMA_NUM_PARALLEL` into PRIME as
well as Ollama. This is only a configuration signal, not proof that the backend
actually activated N slots. A future qualification must inspect the running
Ollama environment and startup behavior, and still provide the measured profile
before the queue admits more than one slot.
The test uses a temporary SQLite queue and fake executor: two different agents
enter concurrently; a third job for one of those agents waits until a slot is
released. This tests isolation and admission behavior, not inference speed.

An isolated CPU-only Ollama comparison at the production 8,192-token context
showed a five-request workload at N=1/2/3/4 in 29.595/17.902/12.675/13.024
seconds respectively. N=3 used about 4.402 GiB within a 6 GiB cap, produced
five correct outputs, and kept model-load times in milliseconds after warming.
N=6 and N=8 reached the 6 GiB cap when warming at the real context and are
rejected for lack of memory margin. This is evidence for an N=3 *candidate*,
not a completed owner-fast-lane, sustained, restart, or production proof.
`HOST_STABILITY=UNQUALIFIED` is unchanged.

The isolated interface candidate assigns queue priority `critical` only when
the server-issued client policy has role `OWNER`, for both new objectives and
continuations. MEMBER and legacy clients remain `normal`; callers cannot set
priority in the thin-client payload. Contract tests passed, but a running
inference is not preempted and owner latency under background load is unproven.
