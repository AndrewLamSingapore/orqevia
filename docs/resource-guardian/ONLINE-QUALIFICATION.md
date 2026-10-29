# Online Guardian qualification - 29 October 2026

Candidate branch codex/guardian-release-20261029 includes the saved PR467/468
source, then fixes activation defects discovered before rollout. Production is
already Owner-resumed (generation1 at13:05SGT) in a separate authorized DeepSeek
session. Subsequent Owner instructions explicitly allow normal work and park
OFFLINE BACKUP AND LOGGING. Do not restore the obsolete paused-generation0 state,
stop active jobs, apply the parked logging recreation, or start the cold backup.

## Verified recovery and online state

A protected same-C-drive baseline package contains9images,9image configurations,
142unique native Linux/amd64 layers and186SHA256-verified OCI blobs. Docker's
loader accepted the archive while reusing existing content; it was not a clean
host/disaster restoration.42external files/configuration are DPAPI protected and
round-trip verified. No historical rollback image was relabelled/reinvented.
The two old image archives were not found among622651files searched;27access
errors/26skippedlinks limit completeness. Older17October backup receipts predate
the20/21October targets and had off-device sync PENDING. VHDX cold backup is not
executed and is now explicitly parked. Current data is preserved.

HTTPS health remains200/READY. The Caddy gateway was observed restarting during
another session's changes and recovered in a new container at13:18. This branch
made no gateway changes. Image/configuration custody must distinguish the older
baseline recovery package from that subsequent live configuration. No model
inference was submitted by this qualification work.

## Defects corrected

- Resolve memory budgets against provider.model. Normal role/automatic submissions
  deliberately leave requested job.model blank and must not be rejected as an
  unqualified model after routing resolves the configured provider.
- Account for an already resident model's verified live working set instead of
  reserving its entire total footprint a second time for every request. Credit
  requires the exact model digest, qualified context, single resident model,
  unchanged before/after runtime observations, valid expiry and readonly cgroup
  counters. Inactive file cache and explicit server reserve are excluded. Any
  uncertainty keeps the full original budget. Other models/tools and explicit
  RAM reservations cannot borrow that credit.
- Reuse existing host-metrics field validation and retain individual timestamps.
  Wrong schemas/collector/host identities and stale CPU data are unavailable.
- Wake the existing direct dispatcher when completion releases capacity, instead
  of adding up to15seconds of fallback polling delay. No second dispatcher or
  deployment queue guard is installed.
- Test mode changes/restart against both a paused state and the Owner-resumed
  generation1 state. Modes never grant or reverse Owner admission authority.
- Revalidate pinned model digests, runtime version and the configured token
  envelope at local admission, including drift after server startup. Unknown or
  mismatched identities retain the job without starting an unmeasured model.
  Existing remote-provider authorization is independent of this local check.
- Account for WSL physical pages already charged to Windows. The existing host
  sampler now records a single vmmemWSL working set with source, timestamp and
  boot identity. Remaining host growth is bounded by the verified VM ceiling
  plus an explicit overhead reserve. Linux still reserves the full unallocated
  model budget; native tools receive no VM credit. Missing/stale evidence keeps
  conservative full host/commit accounting.
  Verified already-resident guest free/cache pages also reduce incremental host
  growth: resident Windows pages minus nonavailable Linux memory and the explicit
  overhead reserve. This supports a cold model with cached VM pages, while the
  separate Linux budget and Windows reserve remain mandatory.

## Evidence and production decision

125original focused checks passed under active production, without new inference.
Targeted new checks cover routed budgets, warm residency, stale/wrong evidence,
Owner resume preservation and immediate capacity reuse. Full candidate tests/CI
are recorded in a separate custody receipt after completion; these are source
checks, not deployed enforcement.

Current measured VM MemTotal16,414,040,064B (~15.29GiB), available3,275,636,736B in
one live sample. Host available6,124,834,816B. In that sample five verified HTTPS
health requests returnedREADY in0.70-0.87s. A later Ollama sample recorded
13,684,744,192B cgroup charge,13,278,519,296B working set and14,280,974,336B charged
high-water. Current loaded12B context is8192; configured output4096; runtime0.34.2.
Exact installed model digests are retained. Historical charged peak14,487,719,936B
is retained as a conservative total-footprint observation; it is not model quality.

The original example reserves20%host/10%VM and has no model budgets. Enabling it
would stall ordinary jobs. Even with memory budgets, the current VM needs a
measured cold-load/reserve calculation; do not relax margins or claim a warm
model proves all cold starts. A larger WSL limit is one possible reversible
software option, not new hardware and not an executed configuration change.
A later Owner-authorized naturally idle Docker/WSL restart applied an18GiB
ceiling with unchanged4GiB swap. Actual MemTotal became18,857,222,144B
(17.56GiB); all nine original container identities returned healthy, verified
HTTPS wasREADY and Owner generation1 remainedOPEN. No active job was cancelled,
Windows restart, offline backup or logging change occurred. The first attempt
retained the old VM and is preserved as a failed check; the second fully stopped
the WSL VM before restart. Host headroom and cold/warm qualification remain
separate live acceptance requirements.

Production activation remains conditional on a verified complete profile,
matching model/runtime/context identities, verified readonly host/cgroup mounts,
cold and warm admission tests, responsiveness, existing producer coverage and
an idle release interval that preserves accepted work. Do not call a passing
unit suite, normal production resumption or a prepared branch enforced Guardian.

## Deployment and rollback scope

Use the existing backend/coordinator. An optional readonly bind to only Ollama's
current cgroup directory supplies memory counters, not Docker control access:
/sys/fs/cgroup/docker/<verified-ollama-container-id> -> fixed operator-owned path.
No Docker socket, new service/container authority or recurring monitor. A paired
existing measured-compute profile must pin model digests/runtime/context before
release; changing weights/context invalidates its resource qualification.
Host receipt/provenance comes from the existing protected sampler, unchanged.

No production deployment or Owner admission mutation has occurred. A future
backend replacement must coordinate its existing OTel network-namespace sidecar
and preserve the exact prior images/configuration for rollback. Model policies,
credentials, learned records, HTTPS and all21logical roles remain unchanged.
Optional flag removal and retained prior backend/sidecar images are the source
rollback; never replace a current database with stale data or replay uncertain
external work. Parked backup/logging actions stay parked until the Owner resumes
them. Source candidate custody and CI receipt will carry exact head hashes.
