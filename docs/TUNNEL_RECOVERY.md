# Existing Windows tunnel: supervision and acceptance

Implementation is for the discovered OpenAI tunnel-client 0.0.14 interface.
Compose's optional cloudflared profile is a separate transport, not its substitute.
Do not enable both to work around a broken connection. No frozen identity,
transport alias, profile, token, MCP scope or PRIME authority is recreated.

## Installation gate

The current agent cannot read the owner's AppData/Roaming/tunnel-client or
AppData/Local/JARVIS folders, even after scoped read permission was granted.
Owner-context process inventory is also incomplete. No live installation,
scheduled task registration, process termination, tunnel connection or reboot
test has been performed. Installed supervision and boot reliability are BLOCKED
by that access, not PASS. ABEX installation remains owner-PARKED separately.

Before installation, use the same Windows account that owns the approved profile.
Inspect the existing profile and runtime metadata locally; retain only paths,
profile SHA256 and non-secret health evidence. Confirm the same existing tunnel
ID, read-only PRIME target and secret references. Do not print profile contents,
environment variables, API keys or raw client logs. Confirm the exact runtime
binary and profile paths, approved Python runtime and complete process/service
visibility. Resolve an existing client manually before starting this supervisor;
it deliberately refuses to adopt or terminate another client.

The existing operator has a foreground `tunnel-supervise` action. In PowerShell,
after setting the four variables to verified local values, use:

```powershell
& .\scripts\jarvis.ps1 -Action tunnel-supervise -NoOpen `
  -PythonExe $VerifiedPythonPath -TunnelClient $ExistingClientPath `
  -TunnelProfile $ApprovedProfilePath -TunnelProfileSha256 $ApprovedProfileSha256
```

These are required inputs, not invented configuration defaults. The SHA256 is
checked before every child launch. A changed profile stops supervision for review.
The supervisor checks PRIME's existing 127.0.0.1:8000/health for up to 240 seconds
before starting transport. It does not start PRIME or another authority instance.

For unattended owner-session startup, use Windows Task Scheduler under that same
owner with an at-logon trigger, hidden PowerShell (`-NoProfile -WindowStyle Hidden`)
and the verified absolute operator/runtime/profile paths above. Configure one
instance only, no execution time limit, and no unbounded scheduler retries.
Do not store credentials in task arguments. Register/enable only after the profile
and foreground acceptance are verified. This procedure is NOT RUN here.
Before-sign-in boot operation requires an approved service identity with access
to the existing secret mechanism; it is not equivalent to an at-logon task and
is not claimed implemented or accepted. That identity must not introduce a TAP.

## Recovery and observability

The supervisor owns only the child it launches and takes a fixed owner-local
JARVIS file lock. It checks the client's bounded `health` command every ten
seconds with PID cross-check and `--require-control-plane-poll`, never an action
endpoint. Startup has a thirty-second grace; three missed probes trigger a
transport-only restart. Five failures exhaust the episode. Exponential backoff
is 2/4/8/16/32 seconds (sampled at the ten-second monitor cadence); five stable
minutes reset the episode. Exhaustion persists across supervisor restart and
does not automatically reset at reboot or logon. An existing failed episode
requires diagnosis and explicit owner-context recovery review before clearing
its retry budget. Preserve events when restoring service; do not delete evidence.

The existing LocalAppData/JARVIS/tunnel-supervision directory retains status.json
and append-only events.jsonl. Events include process state, readiness observation,
last successful readiness, last failure, reason enum, readiness-recovery count
and recovery result. No subprocess output, profile text or credentials are logged.
The health command proves daemon readiness with at least one control-plane poll;
it is not an independent end-to-end remote request test. Reconnect count represents
observed readiness recoveries, not a provider-attested transport session count.
Unexpected supervisor termination becomes stale evidence within 45 seconds.

The existing operator-status API can read a configured PRIME_TUNNEL_STATUS_FILE.
For Docker, mount the verified host status file/directory read-only and configure
its actual container path during installation. No mount/path was invented here.
Unconfigured monitoring reports NOT_MONITORED; unreadable or stale evidence never
reports tunnel HEALTHY. A transport fault changes the aggregate summary to
DEGRADED while otherwise eligible local work remains ready. Authority/store faults
still take precedence as SAFE_STOP. Health never grants execution permission.

## Acceptance procedures and evidence labels

| Check | Current evidence | Live acceptance procedure |
| --- | --- | --- |
| T1 cold start | BLOCKED: approved owner profile/process visibility unavailable; at-logon/pre-login distinction retained | After approved installation, reboot, record trigger time, PRIME readiness, one client PID and successful client/remote read-only health; prove whether startup required sign-in |
| T2 process death | PASS: recovery-state fixture and mocked driver; live NOT RUN | In an isolated approved tunnel test, stop only the recorded supervisor-owned child; verify one replacement, retained failure/recovery event and unchanged profile hash |
| T3 temporary connection loss | PASS: grace, missed-probe threshold and recovery fixtures; live NOT RUN | On an isolated test connection, interrupt transport without changing authority services; restore it; record unavailable/readiness states, bounded attempts and successful remote read-only health |
| T4 persistent failure | PASS: five failures stop, children terminate, persisted budget survives supervisor restart | With invalid connectivity in the isolated fixture, observe EXHAUSTED and no further launch; never rotate real credentials merely to test failure |
| T5 authority preservation | Existing Harness revalidation/revocation/replay regression remains applicable; live reconnection NOT RUN | Queue an isolated synthetic signed request, expire/revoke it during disconnection, restore transport, and verify the same governed executor rejects it; retain decision/lease records and no execution outcome |
| T6 evidence persistence | PASS: real temporary JSONL/status files survive supervisor recreation | Preserve and reopen owner-local evidence after child/supervisor restart; verify original failures and no credentials; do not clear exhaustion just to obtain a green check |

The Python fixtures simulate process/network conditions; they do not establish
real Windows scheduling, actual control-plane reconnect behavior, ABEX reboot
qualification or an external action result. Do not expand these labels to PASS.
