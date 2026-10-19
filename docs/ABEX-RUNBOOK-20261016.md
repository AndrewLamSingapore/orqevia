# ABEX runbook - 16 October 2026

Owner-authorized continuation. Run these natively on ABEX (DESKTOP-BGD97NB /
DESKTOP-27LKJ2V). Dell prepared the source; this document grants no authority.
Capture completion/exit evidence for each step and add a dated non-Verified
STATUS.md entry. Only Lam moves anything into Verified.

## 0. Prerequisites

- ABEX powered on, signed in, on the expected LAN address (`192.168.1.23`).
- Git clone of `AndrewLamSingapore/orqevia` at latest `main`.
- Docker Desktop running.

## 1. Hugging Face CLI reachability

```powershell
hf --version
Test-NetConnection huggingface.co -Port 443
hf ping
```

Expected: `hf --version` prints a version, the TCP test succeeds, and `hf ping`
reports the hub reachable. ORQEVIA inference itself runs offline; this only
proves model-pull reachability.

## 2. Host metrics collector

Pre-provision the protected directories, then run the sampler on a schedule.

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\ABEX\PrimeHostMetrics\receipt
.\scripts\collect-host-metrics.ps1
Get-Content C:\ProgramData\ABEX\PrimeHostMetrics\receipt\host-metrics.json
```

Then set in `.env` (or the deploy environment):

```text
ORQEVIA_HOST_METRICS_DIR=C:\ProgramData\ABEX\PrimeHostMetrics\receipt
```

and restart the interface service. `/interface/v1/telemetry` must then report
cpu/memory/disk/network_latency as OBSERVED with producer `host-collector`
instead of `HOST_COLLECTOR_NOT_CONFIGURED`. Schedule the sampler with Task
Scheduler (for example every minute) under a protected broker account.

## 3. Measured compute profile (raise inference channels 1 -> max 3)

Produce a native `abex.measured-compute.v1` envelope recording real per-model
peak memory and normal concurrency, then pin it:

```powershell
# generate the profile per governance/ABEX_COMPUTE_PROFILE_V1.md
Get-FileHash -Algorithm SHA256 <profile.json>
```

Set:

```text
ORQEVIA_LOCAL_ADMISSION_MODE=measured
ORQEVIA_MEASURED_COMPUTE_PROFILE=<absolute path>
ORQEVIA_MEASURED_COMPUTE_PROFILE_SHA256=<sha256>
ORQEVIA_QUEUE_CONCURRENCY=3
OLLAMA_NUM_PARALLEL=3
```

Constraints enforced in code: 1..3 slots, only 2 or 3 accepted as candidates,
`OLLAMA_NUM_PARALLEL >= ORQEVIA_QUEUE_CONCURRENCY`, and
`normal_concurrency >= ORQEVIA_QUEUE_CONCURRENCY`. Start at 2, verify, then 3.

## 4. Deploy merged source and capture acceptance receipts

```powershell
git -C <clone> pull --ff-only
docker compose pull
docker compose up -d --remove-orphans
docker compose ps
curl.exe -k https://127.0.0.1:8443/interface/v1/health
```

Record: resolved `main` SHA, image tags/digests, container health, and a fresh
restart persistence check. Do not promote to Verified without Lam.

## 5. Activate the 21 registered agents

The registry has 21 agents all `model: unassigned` and
`runtime_activation_verified: false`. Activation is a native ABEX acceptance
step, not a Dell action:

1. Bind each agent to a governed model in `config/agent_registry.json`.
2. Re-run `python -m pytest tests/test_agent_registry.py tests/test_agent_runtime.py -q`.
3. Produce a per-agent native execution receipt
   (submit -> admission -> execution -> retained result).
4. Record the new activation state in a dated non-Verified STATUS.md entry.

Only Lam awards L7 or moves an item into Verified.
