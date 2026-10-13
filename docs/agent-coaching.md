# Bounded agent coaching

`python -m app.agent_coaching` runs a controller, not a second inference pool.
The existing PRIME service remains the only executor on its existing queue.
All 21 canonical roles receive an original baseline, a disjoint synthetic
practice task with a fixed assessor, and the same original acceptance request.
Acceptance adds an answer-free reusable method to the execution environment;
its effective prompt differs and both prompt/request hashes are recorded.
Original acceptance oracles, failed receipts and Registry bytes are unchanged.
Internal semantic grades do not grant certification or production readiness.

Sessions and transitions persist in `/data/agent-coaching.db`. Submission uses
the existing queue's durable idempotency keys, including recovery after a queue
commit/controller crash. There is at most one outstanding coaching job, no
cloud disclosure/spend, no inference retry and at most two practice attempts.
Owner queued/running work precedes new coaching. One cohort has 21 logical
sessions; no new agents or 21 simultaneous workers are created. Scheduling is
at least daily with at most 84 jobs in a rolling day. New submission stops at
20,000 history events or a 64 MiB controller storage footprint (database plus
SQLite WAL/SHM files); history is preserved. The storage threshold also prevents
new cohorts. It stops new transitions rather than deleting or checkpointing
evidence to shrink the store. A missing submitted queue job blocks its session
with `QUEUE_JOB_MISSING`, retaining the job binding without replay or a grade.

`deploy/agent-coaching.compose.yml` attaches only to the existing data volume.
The controller has no network, credentials, exposed ports or container-control
socket. The existing worker's model bindings/admission/auth controls remain
unchanged. Set a pinned image/source and copy the existing local model *names*
to its environment. Never copy runtime secret values. A source/contract change
blocks unfinished sessions rather than relabelling their evidence.

Create `/data/coaching.pause` to stop new transitions without clearing state.
Stopping the sidecar stops the controller; any submitted bounded queue job is
owned by the existing executor. Restart resumes the same job. Rollback removes
the sidecar only; do not roll back the live queue or erase coaching failures.
The restart policy also resumes across normal host/Docker restarts, while a
deliberate container stop stays stopped. Health checks require a controller
tick within 60 seconds, rather than treating an old database as live operation.

`interface_telemetry.snapshot` offers bounded read-only per-role internal grades
and original event times; a fresh dashboard read never refreshes old evidence.
Coaching records expose no task prompts, answers, secrets or certification.
The telemetry source change needs its own Interface rollout and acceptance.
No DigitalOcean deployment, internet access, physical iPhone acceptance,
autonomous coding/deployment adapter or 21/21 competence is implied.
