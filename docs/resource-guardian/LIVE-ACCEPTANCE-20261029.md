# ABEX Resource Guardian live acceptance - 29 October 2026

This dated engineering receipt supersedes the earlier candidate-only statements
in this directory for the specific ABEX runtime below. It does not promote any
Owner-only Verified portfolio section or certify every agent's semantic quality.

## Decision and source

**ACCEPT_BOUNDED_LOCAL_RESOURCE_ENVELOPE.** Guardian is implemented, tested,
deployed, enforced and runtime verified in persistent HOME_ECO. Production was
explicitly Owner-resumed in the DeepSeek session at 13:05 SGT, generation 1.
Later continuation preserved that OPEN state. Backup and Intelligence logging
are expressly parked; no offline backup, log recreation or compaction occurred.

Deployed application source: `5247611ed3a8f8dbb411a7e9ac556c116e7dce3d`.
Image `orqevia:guardian-5247611ed3a8`, immutable ID
`sha256:5eb620f737daf43729f39603f124394800b5abe54904ee07255c4cc1d56709f8`.
All Python application files matched the source archive; all nine CI checks
passed on that revision. Documentation-only successor commits are not the
running image's source revision. [PR472](https://github.com/AndrewLamSingapore/orqevia/pull/472)
is separate from main; merge is not claimed by this receipt.

The existing backend is the sole logical coordinator. DeepSeek's immutable
interface image `sha256:96e88213d04a277ffaf2f30765f936cc253cb6de52f6c81d7c50df73d9d1d8ea`
is preserved, with submission-only output mode `queued`. No new worker service,
deployment queue guard, Docker socket, inference-for-readiness loop or recurring
monitor was installed. Source-level deterministic scheduling and monitoring fixes
from DeepSeek are included without claiming that every natural-language request
automatically chooses the deterministic operation.

## Device and calibrated envelope

AMD Ryzen 7 PRO 8840HS, 8 cores/16 logical processors, 32 GiB installed RAM,
31.33 GiB usable. A naturally idle Docker/WSL restart applied an 18 GiB ceiling
and retained 4 GiB swap; actual guest memory rose from 15.29 to 17.56 GiB.
Original containers returned without cancelling a job or restarting Windows.
Later backend/interface releases are separately recorded replacements.

The active profile reserves 3 GiB host memory and 10% guest memory. Its memory
recovery multiplier is 1.05; default code remains 1.2 for other profiles. CPU
busy/recovery thresholds remain 85/65. One physical inference is permitted for
21 logical roles. HOME_ECO admits one registered tool and one build; qualified
upper bounds are two small tools and one build. ULTRA_ECO admits no new build.
Modes do not change Owner admission, model/provider authorization or spending.

Profiles pin Ollama 0.34.2, installed model digests, context 8192 and output 4096.
Twelve-billion-parameter reserved memory is 14,922,088,448 B, with verified
resident credit when the exact single loaded model and runtime agree. The
separate host and VM calculations avoid double charging WSL's resident pages.
Unknown/stale observations keep conservative admission. Full guest headroom is
still required. Native tools cannot borrow model residency credit.

Native ProcessorTime and WMI readings disagreed during observed idle comparisons.
The existing protected 60-second sampler now records native ProcessorTime with
source, timestamp and boot identity; admission prefers only validated fresh
native readings. Legacy readings remain available. No provider-level WMI root
cause, temperature, energy savings or universal safe threshold is asserted.

## Actual execution evidence

| Trial | Samples | Minimum host free | Load / request seconds | Result |
|---|---:|---:|---:|---|
| 1B cold | 98 | 7.332 GiB | 2.299 / 3.179 | PASS |
| 12B cold | 260 | 3.522 GiB | 15.199 / 21.860 | PASS |
| 12B warm | 1 | 3.487 GiB | 0.0023 / 3.450 | PASS; CPU peak unmeasured |
| Final native-counter 12B | 83 | 3.255 GiB | 0.0036 / 7.235 | PASS |

These were real existing-queue LOCAL_ONLY requests, cloud disabled and zero
permitted external cost. Queue waits were 230/827/849/311 seconds, separate
from active execution budgets. Samples include other authorized work while
waiting, not isolated attribution. No observed active inference count exceeded
one. The prior 4 GiB candidate failed its resource floor despite a valid answer;
that failure remains retained. A separate 20-sample responsiveness observation
had zero shell timeouts and verified HTTPS READY with maximum latency 2.31 s.

All nine roles run; all five declared Docker health checks pass. Four volumes
and three installed Docker Ollama model digests are preserved. An isolated
consistent SQLite qualification preserved a SHA256 projection of 6,994 job
records and all 21 roles; no production data was mounted or worker started.
Actual backend/OTel restart preserved HOME_ECO, the native counter source and
Owner OPEN generation 1. Subsequent production admissions recorded HOME_ECO.

Verified-certificate browser acceptance opened 17 screens without page errors.
An authenticated HTTPS deterministic objective persisted to the database and
downloaded its dispatch artifact with matching SHA256, without a model call.
Disposable test sessions were revoked. These checks do not certify every
consequential action, model answer or hardware fault.

## Custody, recovery and operational limits

The operator evidence directory is
`C:/Users/Admin/Documents/ABEX/operations/recovery-readiness-20261029`.
Its `guardian-acceptance-final.json`, `guardian-persistence-verified.json`,
`guardian-local-*.json`, `guardian-migration-qualified.json`,
`guardian-deployment-5247611.json`, `browser-smoke.json`,
`guardian-https-flow.json` and `EXECUTION-REPORT.md` retain exact commands,
timestamps, image identity, measurements and limits. The public acceptance
projection is [release-evidence/guardian-live-acceptance.json](release-evidence/guardian-live-acceptance.json).
Private configurations and SQLite snapshots remain DPAPI-protected outside Git.

Historical missing rollback tags were not recreated or relabelled. A qualified
replacement package covers 11 image roots and 92 protected package files;
archives, OCI blobs and protected files were hash verified and accepted by the
Docker loader using existing content. It is on the same physical C: drive,
not a clean-host restore or data-volume/VHDX/off-device disaster backup.

The first release hit a sidecar namespace configuration error and actually
restored the original backend/OTel services. Original containers, exact images
and private configuration snapshots remain available. Rollback at natural idle
uses the exact dated pair/configuration; never rewind the live database, clear
jobs/permits, undo the Owner resume or remove models. The optional profile can
be disabled. Existing sampler backups and ACLs are retained.

For future Compose recreation include `docker-compose.yml`,
`docker-compose.otel-collector-20261022.yml` and
`docker-compose.guardian-20261029.json`, with `--no-build --pull never`.
The overlay passed static Compose validation; no Compose up is claimed for that
validation. Ollama replacement changes its cgroup identity and requires rebinding
and qualification. No Docker socket is exposed to the backend.

Unregistered OS applications and Windows Ollama are not automatically controlled.
Thermal/power telemetry, arbitrary sustained load, full reboot acceptance and
all-role competence remain unverified. Legacy composite interface task metadata
does not establish its source revision; its image is immutably pinned. Complete
recent activity across all 21 roles and disaster-backup acceptance remain UNKNOWN
in the canary, without failed service checks. Offline backup/logging changes stay
parked. C++/NumPy PR469 remains independent, disabled and undeployed; no custom
C++ benefit or whole-application speedup is claimed here.
