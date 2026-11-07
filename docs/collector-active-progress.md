# Active execution progress observation

The Windows collector previously checked only the most recent job start or
completion. A genuine job streaming for more than 120 seconds therefore became
`UNKNOWN / WORKER_HEARTBEAT_NOT_EXPOSED`, even when its durable progress was current.

The additional observation reads the existing queue through SQLite `mode=ro`
and `query_only=ON`, inside the inspected immutable backend container ID. It
accepts candidates only from occupied local `running / INFERENCING` records with
bounded, nonempty, NUL-free text, an update strictly after admission, and an
unexpired finite lease matching the recorded admission and execution budget.
The job must have started after the current backend start; the running backend
revision must match its inspected image revision.

An empty stream frame can republish unchanged text and advance `updated_at`.
Consequently, a candidate alone does not establish genuine content progress.
The protected previous operational receipt holds at most 32 witnesses containing
SHA256 hashes, character counts and observation times. Each witness binds the
backend container ID, source revision, backend start, job admission, hashed job
identity and hashed lease identity. Actual progress requires a different content
hash, a strictly larger character count and an increasing update time across
two valid observations in that same context. The first observation remains
`UNKNOWN` when admission/completion evidence is old.

The previous observation time is the conservative lower bound on genuine
progress. The collector never substitutes the current timestamp for that bound.
Unchanged text retains the original genuine-progress time and cannot extend its
freshness. Malformed, future, old-context or duplicate witnesses are rejected.
The existing 120 second freshness window and five second clock tolerance remain
unchanged; a sampling gap greater than 120 seconds cannot establish freshness
from two otherwise changed samples.

The source writer audit found that `JobQueue.update_progress` is the only normal
writer that advances `updated_at` on an already running job while keeping it
running. The actual streaming callback supplies that writer with accepted model
progress. Claiming a job sets `updated_at` equal to admission; retries retain old
output but reset admission. Phase transitions write `timings_json`; lease-only
maintenance does not advance `updated_at`. Approval, cancellation, completion,
timeout and recovery update other states. The background admission verification
clone is uncommitted and always rolled back.

The collector exports only the bounded hashes/counts, validated progress times
and fixed validation codes, plus existing content-free persistence/source
metadata. It exports no prompt, result, raw job identifier, raw timing record or
lease value. Witnesses stay in the protected receipt; the existing API consumer
projects the check reason/timestamp and omits the witness data. A positive check
reports `PERSISTENCE_AND_RECENT_EXECUTION_PROGRESS_OBSERVED` at the conservative
progress time with validation
`TWO_SAME_CONTEXT_OBSERVATIONS_WITH_INCREASED_NONEMPTY_TEXT`. The existing
120 second recent job-start/completion fallback remains unchanged.

This is execution-progress evidence, not a continuous idle worker heartbeat or
proof that the model answer is correct. Idle periods, stale or absent progress,
invalid leases, old backend admissions and incomplete identity remain `UNKNOWN`
when no other recent valid execution evidence exists. There is no continuous
worker heartbeat in the current application; adding one requires a separate
source change rather than a freshness extension or a health override.

The host collector is independently installed; the backend, interface and
coaching application image may remain on source `0274ddcf`. Source validation
and actual installed scheduled-collection evidence must be reported separately.
