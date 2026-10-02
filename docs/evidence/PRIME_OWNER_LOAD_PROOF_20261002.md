# Isolated Owner-under-load inference proof — 2026-10-02 SGT

Status: **candidate evidence; not production acceptance**. `HOST_STABILITY=UNQUALIFIED`.

`benchmarks/owner_queue_probe.py` used a temporary SQLite `JobQueue` and the
pinned Ollama image in a separate loopback-only Docker container at
`127.0.0.1:11435`. The production model volume was mounted read-only. The
container had an 8-CPU / 6-GiB limit and was removed after each configuration.
All scenarios used `gemma3:4b`, `num_ctx=8192`, temperature zero, and six total
jobs from distinct registered agents. Background work occupied its allowed
slots before an Owner-critical job arrived; the remaining background jobs
were queued. The short case generated a validated 1–20 sequence; the longer
case generated a validated 1–50 sequence (142 output tokens on its single
warm-up). All six queued outputs were correct in every reported run. Warm
model-load durations during the timed workloads were milliseconds, not seconds.

| Backend N / queue policy | Owner queue wait | Owner first token after submit | Owner completion | Six-job completion after Owner submit |
| --- | ---: | ---: | ---: | ---: |
| N=2, no reserve, short | 5.909 s | 6.219 s | 12.140 s | 18.753 s |
| N=3, no reserve, short | 6.663 s | 6.989 s | 13.360 s | 13.634 s |
| N=3, two background slots / one Owner reserve, short | 0.108 s | 0.913 s | 6.959 s | 19.219 s |
| N=3, two background slots / one Owner reserve, longer | 0.070 s | 0.976 s | 18.009 s | 51.171 s |

The unreserved N=3 configuration improved batch completion but **worsened
Owner first-token time** versus unreserved N=2. Reserving one of three local
inference slots for an arriving Owner markedly improved the measured Owner
response in these isolated trials; the tradeoff was lower background
throughput when no Owner needed the slot. This is intentional latency headroom,
not a claim of work-conserving maximum background saturation.

The candidate queue now prevents aged background work from overtaking a
critical job, includes critical jobs even after a >1,000-job background backlog,
and caps local noncritical inference at N−1 when N>1 is selected. OWNER role is
server-issued in the interface policy; client payloads cannot choose priority.
Existing running inference is not preempted.

**Limits:** this used real Ollama inference through a temporary queue, not the
production PRIME/PWA path. The harness labels N but does not introspect the
backend's active parallelism; the temporary container was launched explicitly
with `OLLAMA_NUM_PARALLEL=N`. No Owner PWA paint timing, thermal trace,
long-duration stability, 21-agent live workload, service-restart persistence,
or Windows-reboot persistence was proven. Docker memory immediately after the
two N=3 runs was 4.405 and 4.413 GiB of the 6-GiB cap; that is not a peak
memory trace. No production concurrency setting was changed.
